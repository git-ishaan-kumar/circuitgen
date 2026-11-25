"""Model discovery, recommendations policy, and error classification for CircuitGen (§8)."""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from circuitgen.ai import PROVIDERS
from circuitgen.tui.services.credentials import CredentialService

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error Classification Foundation (§8.1)
# ---------------------------------------------------------------------------

class ProviderError(Exception):
    """Base exception for provider communication and authentication failures."""


class AuthenticationError(ProviderError):
    """API key was rejected or is missing."""


class ModelNotFoundError(ProviderError):
    """Requested model ID does not exist or was not found."""


class AccessDeniedError(ProviderError):
    """API key does not have access or entitlement to this model."""


class RateLimitedError(ProviderError):
    """Provider rate limits exceeded."""


class QuotaExceededError(ProviderError):
    """Provider quota or billing limit reached."""


class TimeoutError(ProviderError):
    """Network connection or request timed out."""


class NetworkError(ProviderError):
    """Network, DNS, or socket connection failure."""


class BadProviderResponseError(ProviderError):
    """Provider response could not be parsed as valid JSON."""


class ModelService:
    """Service for discovering, validating, and selecting provider models."""

    @classmethod
    def get_recommended_model(cls, provider_id: str) -> str:
        """Return the tested default model for 'Automatic' policy."""
        return PROVIDERS.get(provider_id, {}).get("model", "default")

    @classmethod
    def validate_model_id(cls, model_id: str) -> tuple[bool, str]:
        """Validate model ID format without asserting remote availability.
        
        Syntactic check: nonempty, allowed characters [a-zA-Z0-9_.:/-].
        """
        clean = (model_id or "").strip()
        if not clean:
            return False, "Model ID cannot be empty."
        if len(clean) > 128:
            return False, "Model ID is too long (maximum 128 characters)."
        if not re.match(r"^[a-zA-Z0-9_\-.:/]+$", clean):
            return False, "Model ID contains invalid characters. Use letters, numbers, '-', '.', '/', and ':'."
        return True, "Valid model ID format."

    @classmethod
    def discover_models(
        cls,
        provider_id: str,
        api_key: str | None = None,
        timeout: float = 6.0,
    ) -> list[str]:
        """Query provider discovery endpoint for available model IDs.
        
        Never labels models 'Free'. Normalizes provider failures into error classes.
        All requests in automated tests must be mocked.
        """
        if not api_key:
            resolved, _ = CredentialService.resolve_key(provider_id)
            api_key = resolved

        if not api_key:
            raise AuthenticationError(
                f"No API key configured for {provider_id}. Cannot query model list."
            )

        clean_key = api_key.strip()
        try:
            if provider_id == "gemini":
                url = "https://generativelanguage.googleapis.com/v1beta/models"
                req = urllib.request.Request(url, headers={"x-goog-api-key": clean_key})
            elif provider_id == "anthropic":
                url = "https://api.anthropic.com/v1/models"
                req = urllib.request.Request(
                    url,
                    headers={
                        "x-api-key": clean_key,
                        "anthropic-version": "2023-06-01",
                        "User-Agent": "CircuitGen/0.1",
                    },
                )
            else:
                provider_settings = PROVIDERS.get(provider_id)
                if provider_settings is None:
                    raise ProviderError("Unknown AI provider.")
                base_url = provider_settings["url"]
                if "/chat/completions" in base_url:
                    url = base_url.replace("/chat/completions", "/models")
                else:
                    url = base_url
                if provider_id == "openrouter":
                    url += "/user"
                req = urllib.request.Request(
                    url,
                    headers={
                        "Authorization": f"Bearer {clean_key}",
                        "User-Agent": "CircuitGen/0.1",
                    },
                )

            gemini = provider_id == "gemini"
            openrouter_offset = 0
            if provider_id == "openrouter":
                req = urllib.request.Request(f"{url}?limit=100", headers=dict(req.header_items()))
            model_ids = set()
            seen = set()
            for _ in range(50):
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    try:
                        data = json.loads(resp.read().decode("utf-8"))
                    except ValueError:
                        raise BadProviderResponseError("The provider returned an unreadable model list.") from None

                entries = data.get("models" if gemini else "data") if isinstance(data, dict) else None
                if not isinstance(entries, list):
                    raise BadProviderResponseError("The provider returned an unreadable model list.")
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    if entry.get("supports_chat") is False or entry.get("kind") == "EMBEDDING_MODEL":
                        continue
                    methods = entry.get("supportedGenerationMethods")
                    if gemini and methods is not None and (
                        not isinstance(methods, list) or "generateContent" not in methods
                    ):
                        continue
                    architecture = entry.get("architecture")
                    if isinstance(architecture, dict):
                        inputs = architecture.get("input_modalities")
                        outputs = architecture.get("output_modalities")
                        if any(isinstance(values, list) and "text" not in values for values in (inputs, outputs)):
                            continue
                    model_id = entry.get("name" if gemini else "id")
                    if isinstance(model_id, str):
                        model_id = model_id.removeprefix("models/") if gemini else model_id
                        if cls.validate_model_id(model_id)[0]:
                            model_ids.add(model_id)

                if gemini:
                    parameter, cursor = "pageToken", data.get("nextPageToken")
                elif provider_id == "anthropic" and data.get("has_more"):
                    parameter, cursor = "after_id", data.get("last_id")
                    if not cursor:
                        raise BadProviderResponseError("The provider returned an incomplete model list.")
                elif provider_id == "openrouter" and len(entries) >= 100:
                    openrouter_offset += len(entries)
                    req = urllib.request.Request(
                        f"{url}?limit=100&offset={openrouter_offset}", headers=dict(req.header_items()),
                    )
                    continue
                else:
                    break
                if not cursor:
                    break
                if not isinstance(cursor, str) or cursor in seen:
                    raise BadProviderResponseError("The provider returned an incomplete model list.")
                seen.add(cursor)
                query = urllib.parse.urlencode({parameter: cursor})
                req = urllib.request.Request(f"{url}?{query}", headers=dict(req.header_items()))
            else:
                raise BadProviderResponseError("The provider model list exceeded the page limit.")
            return sorted(model_ids)

        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                raise AuthenticationError(
                    f"Authentication rejected by {provider_id} (HTTP {exc.code})."
                ) from exc
            if exc.code == 404:
                raise ModelNotFoundError(
                    f"Model discovery endpoint not found for {provider_id}."
                ) from exc
            if exc.code == 429:
                raise RateLimitedError(
                    f"Rate limit exceeded while querying models from {provider_id}."
                ) from exc
            if exc.code == 503:
                raise ProviderError("Model discovery is temporarily unavailable (HTTP 503).") from None
            raise ProviderError(f"Provider returned HTTP {exc.code} during model discovery.") from exc

        except (urllib.error.URLError, TimeoutError, OSError):
            raise NetworkError("Network unavailable while discovering models.") from None

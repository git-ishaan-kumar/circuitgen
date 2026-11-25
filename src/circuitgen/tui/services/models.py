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
                safe_key = urllib.parse.quote(clean_key, safe="")
                url = f"https://generativelanguage.googleapis.com/v1beta/models?key={safe_key}"
                req = urllib.request.Request(url, headers={"User-Agent": "CircuitGen/0.1"})
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
                provider_settings = PROVIDERS.get(provider_id, {})
                base_url = provider_settings.get("url", "https://api.openai.com/v1/chat/completions")
                if "/chat/completions" in base_url:
                    url = base_url.replace("/chat/completions", "/models")
                else:
                    url = base_url
                req = urllib.request.Request(
                    url,
                    headers={
                        "Authorization": f"Bearer {clean_key}",
                        "User-Agent": "CircuitGen/0.1",
                    },
                )

            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw_bytes = resp.read()
                try:
                    data = json.loads(raw_bytes.decode("utf-8"))
                except (ValueError, UnicodeError):
                    raise BadProviderResponseError("The provider returned an unreadable model list.") from None

            gemini = provider_id == "gemini"
            entries = data.get("models" if gemini else "data") if isinstance(data, dict) else None
            if not isinstance(entries, list):
                raise BadProviderResponseError("The provider returned an unreadable model list.")
            model_ids = set()
            for entry in entries:
                model_id = entry.get("name" if gemini else "id") if isinstance(entry, dict) else None
                if isinstance(model_id, str):
                    model_id = model_id.removeprefix("models/") if gemini else model_id
                    if cls.validate_model_id(model_id)[0]:
                        model_ids.add(model_id)

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
            raise ProviderError(f"Provider returned HTTP {exc.code} during model discovery.") from exc

        except (urllib.error.URLError, TimeoutError, OSError):
            raise NetworkError("Network unavailable while discovering models.") from None

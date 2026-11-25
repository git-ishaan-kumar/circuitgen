"""Secure credential service and provider authentication verification for CircuitGen (§7, §16)."""
from __future__ import annotations

import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

import keyring
from circuitgen.ai import PROVIDERS

logger = logging.getLogger(__name__)

SERVICE_NAME = "circuitgen"

# Verified official provider key-management portals
PROVIDER_KEY_URLS: dict[str, str] = {
    "gemini": "https://aistudio.google.com/app/apikey",
    "openai": "https://platform.openai.com/api-keys",
    "anthropic": "https://console.anthropic.com/settings/keys",
    "deepseek": "https://platform.deepseek.com/api_keys",
    "groq": "https://console.groq.com/keys",
    "mistral": "https://console.mistral.ai/api-keys/",
    "xai": "https://console.x.ai/",
    "openrouter": "https://openrouter.ai/keys",
    "together": "https://api.together.xyz/settings/api-keys",
    "fireworks": "https://fireworks.ai/api-keys",
    "cerebras": "https://cloud.cerebras.ai/",
}


class InsecureBackendError(Exception):
    """Raised when the active keyring backend cannot store credentials securely."""


@dataclass(frozen=True)
class VerificationResult:
    """Outcome of an API key verification check."""

    success: bool
    status: str  # "verified", "rejected", "network_error", "unsupported"
    message: str


class CredentialService:
    """Encapsulates secure OS credential storage and provider key resolution."""

    @classmethod
    def get_backend_name(cls) -> str:
        """Return the class name of the active keyring backend."""
        try:
            return keyring.get_keyring().__class__.__name__
        except Exception:
            return "Unavailable"

    @classmethod
    def is_secure_backend_available(cls) -> bool:
        """Detect whether a functioning, secure OS credential store is available.

        Fails closed on dummy, null, or fallback backends with non-positive priority.
        """
        try:
            backend = keyring.get_keyring()
            name = backend.__class__.__name__.lower()
            priority = getattr(backend, "priority", 0)

            # Insecure / dummy backends to reject
            insecure_indicators = ("fail", "null", "chainer", "file", "plaintext")
            if any(ind in name for ind in insecure_indicators) and priority <= 0:
                return False

            return priority > 0
        except Exception:
            return False

    @classmethod
    def get_provider_env_var(cls, provider_id: str) -> str:
        """Return the environment variable name associated with this provider."""
        provider_info = PROVIDERS.get(provider_id, {})
        return provider_info.get("key", f"{provider_id.upper()}_API_KEY")

    @classmethod
    def get_provider_url(cls, provider_id: str) -> str:
        """Return the verified official API portal URL for the provider."""
        return PROVIDER_KEY_URLS.get(provider_id, "https://aistudio.google.com/app/apikey")

    @classmethod
    def resolve_key(cls, provider_id: str) -> tuple[str | None, str]:
        """Resolve API key following strict precedence:
        1. Environment variable (per provider as defined in ai.py)
        2. Secure OS keyring
        3. None (Not configured)

        Returns: (key_value, source_description)
        """
        # 1. Environment variable
        env_var = cls.get_provider_env_var(provider_id)
        env_key = os.environ.get(env_var, "").strip()
        if env_key:
            return env_key, "environment"

        # 2. Secure OS keyring
        if cls.is_secure_backend_available():
            try:
                stored_key = keyring.get_password(SERVICE_NAME, provider_id)
                if stored_key and stored_key.strip():
                    return stored_key.strip(), "keyring"
            except Exception:
                logger.warning("Could not read secure storage for %s", provider_id)

        return None, "none"

    @classmethod
    def save_key(cls, provider_id: str, key: str, allow_insecure: bool = False) -> None:
        """Store API key into the OS keyring.
        
        Never logs or exposes the secret key in error messages.
        """
        if not cls.is_secure_backend_available() and not allow_insecure:
            backend = cls.get_backend_name()
            env_var = cls.get_provider_env_var(provider_id)
            raise InsecureBackendError(
                f"Secure credential store is unavailable ({backend}). "
                f"Set {env_var} environment variable instead."
            )

        clean_key = key.strip()
        if not clean_key:
            raise ValueError("API key cannot be empty.")

        try:
            keyring.set_password(SERVICE_NAME, provider_id, clean_key)
        except Exception:
            raise RuntimeError("Could not save the API key to secure storage.") from None

    @classmethod
    def delete_key(cls, provider_id: str) -> bool:
        """Remove stored credential for this provider from the keyring.
        
        Returns True if deleted, False if no stored credential existed.
        """
        if not cls.is_secure_backend_available():
            return False

        try:
            existing = keyring.get_password(SERVICE_NAME, provider_id)
            if not existing:
                return False
            keyring.delete_password(SERVICE_NAME, provider_id)
            return True
        except Exception:
            return False

    @classmethod
    def mask_key(cls, key: str) -> str:
        """Return a masked representation of the key for safe UI hints."""
        clean = key.strip()
        if not clean:
            return ""
        if len(clean) <= 8:
            return "•" * len(clean)
        return clean[:4] + "•" * (len(clean) - 8) + clean[-4:]

    @classmethod
    def verify_key(cls, provider_id: str, key: str, timeout: float = 6.0) -> VerificationResult:
        """Verify an API key against the provider API.
        
        Performs minimal non-billed authentication check where available.
        All requests in automated tests must be mocked.
        """
        clean_key = key.strip()
        if not clean_key:
            return VerificationResult(False, "rejected", "API key is empty.")

        from circuitgen.ai import PROVIDER_DISPLAY_NAMES
        provider_name = PROVIDER_DISPLAY_NAMES.get(provider_id, provider_id.title())

        # Construct verification request
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
                # OpenAI and OpenAI-compatible providers
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
                if 200 <= resp.status < 300:
                    return VerificationResult(
                        True,
                        "verified",
                        f"✓ Key verified successfully with {provider_name}.",
                    )
                return VerificationResult(
                    False,
                    "rejected",
                    f"× Key rejected by {provider_name} (HTTP {resp.status}).",
                )

        except urllib.error.HTTPError as exc:
            if exc.code in (401, 403):
                return VerificationResult(
                    False,
                    "rejected",
                    f"× Key rejected by {provider_name}.\nCheck the key and try again.",
                )
            return VerificationResult(
                False,
                "unsupported",
                f"! Provider returned HTTP {exc.code}. You may save without verification.",
            )
        except (urllib.error.URLError, TimeoutError, OSError):
            return VerificationResult(
                False,
                "network_error",
                "! Could not verify the key (network unavailable).\nYou may save it unverified or try again.",
            )
        except Exception:
            return VerificationResult(
                False,
                "network_error",
                "! Could not verify the API key.",
            )

"""Provider-independent natural-language-to-netlist translation for CircuitGen.

Custom components use explicit logical ``pins`` lists, not verified physical pinouts.
No third-party SDK is required; Python's standard library handles HTTP requests.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
import urllib.parse
from typing import Any, Callable

from .engine import CircuitError

DEFAULT_PROVIDER = "gemini"
DEFAULT_MODEL = "gemini-2.5-flash"

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "components": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "type": {"type": "string"},
                    "value": {"type": "string"},
                    "pins": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["id", "type", "value"],
                "additionalProperties": False,
            },
        },
        "nets": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "pins": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["name", "pins"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["components", "nets"],
    "additionalProperties": False,
}

PROMPT = """You are an electrical netlist translator for CircuitGen.
Convert the user's educational circuit description into a complete JSON
netlist. Output only the JSON object; no diagrams, Python, SVG, or commentary.

REGISTERED COMPONENT TYPES (use these exact lowercase type strings):
- Two-terminal: resistor, capacitor, inductor, diode, led, switch, lamp,
  fuse, battery, dc_source, ac_source, current_source.
- Three-/multi-terminal: npn, pnp, nmos, pmos, opamp, ne555, arduino_uno.
- Custom components: types not listed above are supported using an explicit
  component-level "pins" array (see below).

PIN NAMES FOR REGISTERED COMPONENTS:
- battery/dc_source/ac_source/current_source: p (positive), n (negative)
- resistor/capacitor/inductor/switch/lamp/fuse: a, b
- led/diode: a (anode), b (cathode)
- npn/pnp: B, C, E
- nmos/pmos: G, D, S
- opamp: IN+, IN-, OUT, V+, V-
- ne555: VCC, GND, TRIG, THRES, DISCH, RESET, CTRL, OUT
  (IMPORTANT: pin 6 is THRES, NEVER THRESH)
- arduino_uno: D0 through D13, A0 through A5, 3V3, 5V, VIN, GND, RESET

CUSTOM COMPONENT RULES (CRITICAL):
1. If a component type is not registered, provide a "pins" array listing
   unique logical pin names for that component. Never omit this field.
2. Use the SAME case-sensitive pin names in the nets (e.g. S1.SDA).
3. Example generic I2C sensor:
   {"id":"S1","type":"i2c_sensor","value":"generic",
    "pins":["SDA","SCL","VCC","GND"]}
   These names are a logical interface for a user-described generic sensor;
   they are NOT a verified physical package pinout.
4. Pin names may contain letters, digits, underscore, + and - (1-24 chars).
   Keep component types lowercase with underscores, e.g. i2c_sensor.
5. For a *specific* unfamiliar IC/module whose pinout was not supplied,
   do not invent a real-world physical pinout. Use only the logical pins
   clearly specified by the user. Do not claim physical pin numbers.
6. Registered components normally omit "pins" because CircuitGen already
   knows them. If supplied, the list must match the registered pins exactly.

GENERAL NETLIST RULES:
1. Preserve explicitly requested components, values, and connections.
2. Assign a unique ID to every component and unique name to every net.
3. Each physical/logical pin may belong to AT MOST one net.
4. A net connects electrically identical nodes, potentially many pins.
5. Never create different nets for points directly wired together.
6. Never invent intermediate components or silently change a part's type.
7. Unused pins on multi-pin components may remain unconnected: do not
   invent connections simply to fill their pins.
8. Support series, parallel, bridges, feedback, transistors, and ICs.
9. Match polarity and directions, especially LED anode/cathode.
10. Return exactly "components" and "nets" at the top level.
11. For every net terminal reference, use "componentID.pinName" and ensure
    that pinName is defined by the registered symbol or the custom pin list.

EXAMPLE — Arduino Uno with custom I2C sensor:
{
 "components": [
   {"id":"U1","type":"arduino_uno","value":"Arduino Uno"},
   {"id":"S1","type":"i2c_sensor","value":"generic",
    "pins":["SDA","SCL","VCC","GND"]}
 ],
 "nets": [
   {"name":"SDA_LINE","pins":["U1.A4","S1.SDA"]},
   {"name":"SCL_LINE","pins":["U1.A5","S1.SCL"]},
   {"name":"VCC","pins":["U1.5V","S1.VCC"]},
   {"name":"GND","pins":["U1.GND","S1.GND"]}
 ]
}

User description:
"""

PROVIDERS: dict[str, dict[str, str]] = {
    "gemini": {"key": "GEMINI_API_KEY", "model": DEFAULT_MODEL},
    "openai": {"key": "OPENAI_API_KEY", "model": "gpt-4.1-mini",
               "url": "https://api.openai.com/v1/chat/completions"},
    "anthropic": {"key": "ANTHROPIC_API_KEY", "model": "claude-sonnet-4-5",
                  "url": "https://api.anthropic.com/v1/messages"},
    "deepseek": {"key": "DEEPSEEK_API_KEY", "model": "deepseek-chat",
                 "url": "https://api.deepseek.com/chat/completions"},
    "groq": {"key": "GROQ_API_KEY", "model": "llama-3.3-70b-versatile",
             "url": "https://api.groq.com/openai/v1/chat/completions"},
    "mistral": {"key": "MISTRAL_API_KEY", "model": "mistral-small-latest",
                "url": "https://api.mistral.ai/v1/chat/completions"},
    "xai": {"key": "XAI_API_KEY", "model": "grok-3-mini",
            "url": "https://api.x.ai/v1/chat/completions"},
    "openrouter": {"key": "OPENROUTER_API_KEY", "model": "openai/gpt-4.1-mini",
                   "url": "https://openrouter.ai/api/v1/chat/completions"},
    "together": {"key": "TOGETHER_API_KEY", "model": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
                 "url": "https://api.together.xyz/v1/chat/completions"},
    "fireworks": {"key": "FIREWORKS_API_KEY", "model": "accounts/fireworks/models/llama-v3p3-70b-instruct",
                  "url": "https://api.fireworks.ai/inference/v1/chat/completions"},
    "cerebras": {"key": "CEREBRAS_API_KEY", "model": "llama-3.3-70b",
                 "url": "https://api.cerebras.ai/v1/chat/completions"},
}

ALIASES = {"google": "gemini", "claude": "anthropic", "chatgpt": "openai", "grok": "xai"}

PROVIDER_DISPLAY_NAMES: dict[str, str] = {
    "gemini": "Google Gemini",
    "openai": "OpenAI",
    "anthropic": "Anthropic",
    "deepseek": "DeepSeek",
    "groq": "Groq",
    "mistral": "Mistral",
    "xai": "xAI",
    "openrouter": "OpenRouter",
    "together": "Together AI",
    "fireworks": "Fireworks AI",
    "cerebras": "Cerebras",
}


def list_providers() -> list[str]:
    """Return supported provider identifiers."""
    return list(PROVIDERS)


class ClarificationRequired(CircuitError):
    """The provider needs more detail about the intended wiring."""


class ProviderRequestError(CircuitError):
    def __init__(self, message: str, *, status: int | None = None, transient: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.transient = transient


def _post_json(url: str, payload: dict[str, Any], headers: dict[str, str],
               provider: str, *, timeout: float = 120) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            data = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ProviderRequestError(
            f"{provider} API returned HTTP {exc.code}",
            status=exc.code, transient=exc.code in (500, 502, 503, 504),
        ) from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ProviderRequestError(f"{provider} API connection problem", transient=True) from None
    except (ValueError, UnicodeError) as exc:
        raise CircuitError(f"{provider} API returned invalid response JSON") from exc
    if not isinstance(data, dict):
        raise CircuitError(f"{provider} API response was not an object")
    if data.get("error"):
        raise CircuitError(f"{provider} API reported an error")
    return data


def _parse_netlist(raw: str, provider: str, *, clarify: bool = False) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
    try:
        decoded = json.loads(text)
    except (ValueError, TypeError) as exc:
        raise CircuitError(f"{provider} did not return valid netlist JSON") from exc
    if not isinstance(decoded, dict):
        raise CircuitError(f"{provider} JSON was not an object")
    if clarify and set(decoded) == {"question"}:
        question = decoded["question"]
        if isinstance(question, str) and question.strip() and len(question) <= 300:
            raise ClarificationRequired(question.strip())
    if not isinstance(decoded.get("components"), list) or not isinstance(decoded.get("nets"), list):
        raise CircuitError(f"{provider} JSON must contain components and nets arrays")
    return decoded


def _gemini(full_text: str, model: str, key: str, *, timeout: float = 120, clarify: bool = False) -> str:
    payload = {
        "contents": [{"role": "user", "parts": [{"text": full_text}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseJsonSchema": {
                "anyOf": [
                    SCHEMA,
                    {"type": "object", "properties": {"question": {"type": "string"}}, "required": ["question"]},
                ],
            } if clarify else SCHEMA,
        },
    }
    safe_model = urllib.parse.quote(model, safe="-._/")
    data = _post_json(
        f"https://generativelanguage.googleapis.com/v1beta/models/{safe_model}:generateContent",
        payload, {"x-goog-api-key": key}, "gemini", timeout=timeout,
    )
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise CircuitError("Gemini returned no usable text (possibly blocked or truncated)") from exc


def _anthropic(full_text: str, model: str, key: str, *, timeout: float = 120) -> str:
    payload = {
        "model": model,
        "max_tokens": 8192,
        "temperature": 0,
        "system": "Return only the requested JSON netlist. No markdown or commentary.",
        "messages": [{"role": "user", "content": full_text}],
    }
    data = _post_json(
        PROVIDERS["anthropic"]["url"], payload,
        {"x-api-key": key, "anthropic-version": "2023-06-01"}, "anthropic", timeout=timeout,
    )
    if data.get("stop_reason") == "max_tokens":
        raise CircuitError("Anthropic response was truncated; try a simpler circuit")
    blocks = data.get("content", [])
    raw = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
    if not raw.strip():
        raise CircuitError("Anthropic returned no text")
    return raw


def _openai_compatible(full_text: str, provider: str, model: str, key: str, *, timeout: float = 120) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return only one valid JSON object. No markdown."},
            {"role": "user", "content": full_text},
        ],
    }
    data = _post_json(
        PROVIDERS[provider]["url"], payload,
        {"Authorization": f"Bearer {key}"}, provider, timeout=timeout,
    )
    try:
        choice = data["choices"][0]
        if choice.get("finish_reason") == "length":
            raise CircuitError(f"{provider} response was truncated")
        content = choice["message"]["content"]
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(part.get("text", "") for part in content if isinstance(part, dict))
        raise TypeError("No text content")
    except (KeyError, IndexError, TypeError) as exc:
        raise CircuitError(f"{provider} returned no usable text") from exc


def generate_netlist(
    user_prompt: str,
    provider: str = DEFAULT_PROVIDER,
    model: str | None = None,
    correction: str = "",
    api_key: str | None = None,
    *,
    timeout: float = 120,
    retry_transient: bool = False,
    allow_model_fallback: bool = False,
    clarify: bool = False,
    on_model: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Generate a JSON netlist using the selected AI provider.

    Returns an unvalidated dict; pass it to the existing engine validator.
    """
    if not isinstance(user_prompt, str) or not user_prompt.strip():
        raise CircuitError("Circuit description must be a nonempty string")
    if not 0 < timeout <= 600:
        raise ValueError("Request timeout must be greater than 0 and at most 600 seconds")
    provider = ALIASES.get(provider.strip().lower(), provider.strip().lower())
    if provider not in PROVIDERS:
        raise CircuitError(
            f"Unsupported AI provider: {provider}. Available: {', '.join(list_providers())}"
        )
    settings = PROVIDERS[provider]
    chosen_model = model or settings["model"]
    if not isinstance(chosen_model, str) or not chosen_model.strip():
        raise CircuitError("Model must be a nonempty string")

    # Priority: explicit argument -> environment variable -> secure keyring
    key = (api_key or "").strip()
    if not key:
        key = os.environ.get(settings["key"], "").strip()
    if not key:
        try:
            from circuitgen.tui.services.credentials import CredentialService

            resolved, _ = CredentialService.resolve_key(provider)
            if resolved:
                key = resolved.strip()
        except Exception:
            pass

    if not key:
        raise CircuitError(f"{settings['key']} is not set")

    full_text = PROMPT + user_prompt
    if clarify:
        full_text += (
            '\nIf essential wiring is ambiguous, return only {"question":"one short question"}.'
            " Ask only when you cannot determine the intended connections."
        )
    if correction:
        full_text += (
            "\n\nPREVIOUS OUTPUT WAS REJECTED. Return a corrected full netlist. "
            "Do not claim unsupported circuit is possible. Error: " + correction[:900]
        )
    def request(model_id: str) -> str:
        options = {"timeout": timeout} if timeout != 120 else {}
        if provider == "gemini":
            if clarify:
                options["clarify"] = True
            return _gemini(full_text, model_id, key, **options)
        if provider == "anthropic":
            return _anthropic(full_text, model_id, key, **options)
        return _openai_compatible(full_text, provider, model_id, key, **options)

    try:
        raw = request(chosen_model)
    except ProviderRequestError as exc:
        if allow_model_fallback and exc.status == 404 and chosen_model != settings["model"]:
            chosen_model = settings["model"]
            raw = request(chosen_model)
        elif retry_transient and exc.transient:
            raw = request(chosen_model)
        else:
            raise
    netlist = _parse_netlist(raw, provider, clarify=clarify)
    if on_model is not None:
        on_model(chosen_model)
    return netlist

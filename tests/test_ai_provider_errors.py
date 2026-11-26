import io
import asyncio
import json
import socket
import unittest
import urllib.error
from unittest.mock import patch

from circuitgen.ai import ProviderRequestError, _post_json, generate_netlist
from circuitgen.tui.screens.generate import provider_error_message
from circuitgen.tui.app import CircuitGenApp
from circuitgen.tui.screens.generate import GenerateScreen
from circuitgen.tui.services.config import AppConfig, ConfigService
from circuitgen.tui.services.credentials import CredentialService
from circuitgen.tui.widgets import EnhancedInput, JsonEditor, SelectableMenu
from circuitgen.tui.services.models import ModelService


def http_error(status, code="", retry_after=None):
    body = json.dumps({"error": {"code": code, "message": "secret response body"}}).encode()
    headers = {"Retry-After": str(retry_after)} if retry_after is not None else {}
    return urllib.error.HTTPError("https://example.invalid", status, "failed", headers, io.BytesIO(body))


class TestProviderErrors(unittest.TestCase):
    def classify(self, status, code="", retry_after=None):
        with patch("circuitgen.ai.urllib.request.urlopen", side_effect=http_error(status, code, retry_after)):
            with self.assertRaises(ProviderRequestError) as caught:
                _post_json("https://example.invalid", {}, {}, "mock")
        self.assertNotIn("secret response body", str(caught.exception))
        return caught.exception

    def test_access_and_billing_failures_never_retry(self):
        for status, code, kind in ((401, "", "authentication"), (403, "", "access"),
                                   (404, "", "model_unavailable"),
                                   (429, "insufficient_quota", "quota"),
                                   (403, "quota_exceeded", "quota"), (402, "", "quota")):
            error = self.classify(status, code)
            self.assertEqual(error.kind, kind)
            self.assertFalse(error.transient)

    def test_rate_limit_requires_retry_hint_for_automatic_retry(self):
        self.assertFalse(self.classify(429).transient)
        error = self.classify(429, retry_after=1)
        self.assertEqual((error.kind, error.retry_after, error.transient), ("rate_limit", 1.0, True))
        self.assertFalse(self.classify(429, retry_after=20).transient)

    def test_network_and_timeout_are_distinct(self):
        for reason, kind in ((socket.timeout("slow"), "timeout"),
                             (OSError("offline"), "network")):
            with patch("circuitgen.ai.urllib.request.urlopen",
                       side_effect=urllib.error.URLError(reason)):
                with self.assertRaises(ProviderRequestError) as caught:
                    _post_json("https://example.invalid", {}, {}, "mock")
            self.assertEqual(caught.exception.kind, kind)

    def test_temporary_error_retries_once_with_bounded_wait(self):
        response = {"components": [{"id": "R1", "type": "resistor", "value": "1k"}],
                    "nets": [{"name": "N1", "pins": ["R1.a", "R1.b"]}]}
        with (patch("circuitgen.ai._gemini", side_effect=[
                ProviderRequestError("503", status=503, transient=True, retry_after=1.5),
                json.dumps(response)]) as provider,
              patch("circuitgen.ai.time.sleep") as sleep):
            self.assertEqual(generate_netlist("Build a circuit", api_key="test", retry_transient=True), response)
        self.assertEqual(provider.call_count, 2)
        sleep.assert_called_once_with(1.5)

    def test_quota_failure_does_not_retry_or_fallback(self):
        with patch("circuitgen.ai._gemini", side_effect=ProviderRequestError(
                "429", status=429, kind="quota")) as provider:
            with self.assertRaises(ProviderRequestError):
                generate_netlist("Build a circuit", api_key="test", model="manual",
                                 retry_transient=True, allow_model_fallback=True)
        self.assertEqual(provider.call_count, 1)

    def test_model_fallback_requires_opt_in_and_reports_actual_model(self):
        response = {"components": [{"id": "R1", "type": "resistor", "value": "1k"}],
                    "nets": [{"name": "N1", "pins": ["R1.a", "R1.b"]}]}
        missing = ProviderRequestError("404", status=404)
        with patch("circuitgen.ai._gemini", side_effect=missing) as provider:
            with self.assertRaises(ProviderRequestError):
                generate_netlist("Build a circuit", api_key="test", model="manual")
            self.assertEqual(provider.call_count, 1)
        used = []
        with patch("circuitgen.ai._gemini", side_effect=[missing, json.dumps(response)]) as provider:
            generate_netlist("Build a circuit", api_key="test", model="manual",
                             allow_model_fallback=True, on_model=used.append)
            self.assertEqual(provider.call_count, 2)
        self.assertEqual(used, ["gemini-2.5-flash"])

    def test_malformed_http_response_is_not_sent_for_netlist_repair(self):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b"not-json"
        with patch("circuitgen.ai.urllib.request.urlopen", return_value=response) as open_url:
            with self.assertRaises(ProviderRequestError) as caught:
                generate_netlist("Build a circuit", api_key="test", retry_transient=True)
        self.assertEqual(caught.exception.kind, "bad_response")
        self.assertEqual(open_url.call_count, 1)

    def test_cli_messages_are_actionable_without_response_details(self):
        for kind, phrase in (("authentication", "API key"), ("model_unavailable", "Choose another model"),
                             ("quota", "quota"), ("rate_limit", "Try again later"),
                             ("timeout", "timed out"), ("network", "connection")):
            message = provider_error_message(ProviderRequestError("secret response body", kind=kind))
            self.assertIn(phrase, message)
            self.assertNotIn("secret response body", message)

    def test_model_list_cache_is_key_scoped_and_refreshable(self):
        ModelService._cache.clear()
        response = unittest.mock.MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = b'{"models":[{"name":"models/example","supportedGenerationMethods":["generateContent"]}]}'
        with patch("circuitgen.tui.services.models.urllib.request.urlopen", return_value=response) as open_url:
            self.assertEqual(ModelService.discover_models("gemini", api_key="key-one", cache=True), ["example"])
            self.assertEqual(ModelService.discover_models("gemini", api_key="key-one", cache=True), ["example"])
            self.assertEqual(open_url.call_count, 1)
            ModelService.discover_models("gemini", api_key="key-two", cache=True)
            ModelService.discover_models("gemini", api_key="key-one", cache=False)
            self.assertEqual(open_url.call_count, 3)
        ModelService._cache.clear()

    def test_quota_error_keeps_generate_draft_and_does_not_save(self):
        async def run():
            config = AppConfig(onboarding_status="completed", default_output_dir=".")
            with (patch.object(ConfigService, "load", return_value=config),
                  patch.object(CredentialService, "resolve_key", return_value=("test-key", "environment")),
                  patch.object(ModelService, "discover_models", return_value=["gemini-2.5-flash"]),
                  patch("circuitgen.tui.screens.generate.generate_netlist",
                        side_effect=ProviderRequestError("secret body", status=429, kind="quota")) as request):
                app = CircuitGenApp()
                async with app.run_test(size=(80, 24)) as pilot:
                    app.push_screen(GenerateScreen(config))
                    await pilot.pause()
                    page = app.screen
                    page.query_one(JsonEditor).text = "Build a circuit"
                    page.query_one("#generate-filename", EnhancedInput).value = "phase12-no-write.svg"
                    menu = page.query_one(SelectableMenu)
                    menu.selected_index = 0
                    menu.focus()
                    await pilot.press("enter")
                    await app.workers.wait_for_complete()
                    await pilot.pause()
                    self.assertIs(app.screen, page)
                    self.assertIn("quota", str(page.query_one("#generate-status").content))
                    self.assertNotIn("secret body", str(page.query_one("#generate-status").content))
                    self.assertEqual(page.query_one(JsonEditor).text, "Build a circuit")
                    self.assertEqual(page.query_one("#generate-filename", EnhancedInput).value,
                                     "phase12-no-write.svg")
                    self.assertEqual(request.call_count, 1)
        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()

"""Automated tests for CircuitGen Phase 4 — Credential Service, API-Key Input, and Mocked Verification."""
from __future__ import annotations

import asyncio
import io
import os
import tempfile
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from circuitgen.ai import generate_netlist
from circuitgen.engine import CircuitError
from circuitgen.tui.app import CircuitGenApp
from circuitgen.tui.screens.setup_key import SetupKeyScreen
from circuitgen.tui.screens.setup_step_placeholder import SetupStepPlaceholderScreen
from circuitgen.tui.services.config import AppConfig, ConfigService
from circuitgen.tui.services.credentials import (
    CredentialService,
    InsecureBackendError,
    VerificationResult,
)
from circuitgen.tui.widgets.selectable_menu import SelectableMenu
from textual.widgets import Input, Static


class InMemoryKeyring:
    """In-memory keyring for deterministic, isolated unit testing."""

    priority = 5

    def __init__(self) -> None:
        self._storage: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self._storage.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self._storage[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        key = (service, username)
        if key in self._storage:
            del self._storage[key]
        else:
            raise Exception("Password not found")


class InsecureDummyKeyring:
    """Keyring backend that simulates insecure or unavailable OS storage."""

    priority = 0


@pytest.fixture
def fake_keyring():
    """Patch keyring to use in-memory store."""
    ring = InMemoryKeyring()
    with patch("keyring.get_keyring", return_value=ring), \
         patch("keyring.get_password", side_effect=ring.get_password), \
         patch("keyring.set_password", side_effect=ring.set_password), \
         patch("keyring.delete_password", side_effect=ring.delete_password):
        yield ring


@pytest.fixture
def temp_config_dir():
    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        old_env = os.environ.get("CIRCUITGEN_CONFIG_DIR")
        os.environ["CIRCUITGEN_CONFIG_DIR"] = str(temp_dir)
        ConfigService.reset_cache()
        try:
            yield temp_dir
        finally:
            ConfigService.reset_cache()
            if old_env is not None:
                os.environ["CIRCUITGEN_CONFIG_DIR"] = old_env
            else:
                os.environ.pop("CIRCUITGEN_CONFIG_DIR", None)


class TestCredentialServiceUnit:
    """Test credential service storage, resolution priority, masking, and security checks."""

    def test_save_read_delete_key(self, fake_keyring):
        test_key = "TEST_KEY_DO_NOT_USE"
        CredentialService.save_key("gemini", test_key)

        resolved, source = CredentialService.resolve_key("gemini")
        assert resolved == test_key
        assert source == "keyring"

        deleted = CredentialService.delete_key("gemini")
        assert deleted is True

        resolved_after, source_after = CredentialService.resolve_key("gemini")
        assert resolved_after is None
        assert source_after == "none"

    def test_environment_variable_takes_precedence_over_keyring(self, fake_keyring):
        CredentialService.save_key("gemini", "keyring-key-12345")

        with patch.dict(os.environ, {"GEMINI_API_KEY": "env-key-99999"}):
            resolved, source = CredentialService.resolve_key("gemini")
            assert resolved == "env-key-99999"
            assert source == "environment"

        # When env var removed, falls back to keyring
        with patch.dict(os.environ, {}, clear=True):
            resolved, source = CredentialService.resolve_key("gemini")
            assert resolved == "keyring-key-12345"
            assert source == "keyring"

    def test_ai_generator_resolves_key_from_keyring_without_mutating_env(self, fake_keyring):
        CredentialService.save_key("gemini", "keyring-stored-secret")

        with patch.dict(os.environ, {}, clear=True):
            assert "GEMINI_API_KEY" not in os.environ
            with patch("circuitgen.ai._gemini", return_value='{"components":[],"nets":[]}') as mock_gemini:
                generate_netlist("resistor R1 10k", provider="gemini")
                mock_gemini.assert_called_once()
                # Verify key passed to underlying provider function is the keyring key
                _, _, passed_key = mock_gemini.call_args[0]
                assert passed_key == "keyring-stored-secret"
                # Global os.environ must NOT be polluted
                assert "GEMINI_API_KEY" not in os.environ

    def test_mask_key_helper(self):
        assert CredentialService.mask_key("") == ""
        assert CredentialService.mask_key("short") == "•••••"
        masked = CredentialService.mask_key("sk-ant-api03-1234567890abcdef")
        assert masked.startswith("sk-a")
        assert masked.endswith("cdef")
        assert "1234567890" not in masked

    def test_insecure_backend_fails_closed(self):
        insecure_ring = InsecureDummyKeyring()
        with patch("keyring.get_keyring", return_value=insecure_ring):
            assert CredentialService.is_secure_backend_available() is False
            with pytest.raises(InsecureBackendError) as exc_info:
                CredentialService.save_key("gemini", "TEST_KEY_DO_NOT_USE")
            assert "Secure credential store is unavailable" in str(exc_info.value)
            assert "GEMINI_API_KEY" in str(exc_info.value)

    def test_secrets_never_leak_into_config_file(self, fake_keyring, temp_config_dir):
        test_key = "TOP_SECRET_API_KEY_12345"
        CredentialService.save_key("gemini", test_key)

        config = AppConfig(default_provider="gemini")
        ConfigService.save(config, override_dir=temp_config_dir)

        config_path = temp_config_dir / "config.json"
        raw_text = config_path.read_text(encoding="utf-8")
        assert test_key not in raw_text

    def test_mocked_key_verification_rejected(self):
        # Mock HTTP 401
        http_error = urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)
        with patch("urllib.request.urlopen", side_effect=http_error):
            res = CredentialService.verify_key("gemini", "invalid-key")
            assert res.success is False
            assert res.status == "rejected"
            assert "Key rejected" in res.message
            assert "invalid-key" not in res.message

    def test_mocked_key_verification_network_error(self):
        # Mock connection failure
        url_error = urllib.error.URLError("Connection refused")
        with patch("urllib.request.urlopen", side_effect=url_error):
            res = CredentialService.verify_key("gemini", "any-key")
            assert res.success is False
            assert res.status == "network_error"
            assert "network unavailable" in res.message

    def test_mocked_key_verification_success(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__.return_value = mock_resp
        with patch("urllib.request.urlopen", return_value=mock_resp):
            res = CredentialService.verify_key("gemini", "valid-fake-key")
            assert res.success is True
            assert res.status == "verified"
            assert "Key verified successfully" in res.message


class TestSetupKeyScreenInteraction:
    """Test SetupKeyScreen (S2) interactions, masked password input, verification, and wipe on exit."""

    def test_setup_s2_screen_renders_masked_input(self, temp_config_dir, fake_keyring):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                # Mount SetupKeyScreen directly for test
                screen = SetupKeyScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                assert isinstance(app.screen, SetupKeyScreen)
                step_indicator = app.screen.query(".breadcrumb-right").first().render()
                assert "Step 3 of 4" in str(step_indicator)

                key_input = app.screen.query_one("#key-input", Input)
                assert key_input.password is True

                menu = app.screen.query_one("#key-action-menu", SelectableMenu)
                assert [item.key for item in menu.items] == [
                    "verify",
                    "save_unverified",
                    "how_to_get",
                    "skip",
                ]

        asyncio.run(_run())

    def test_setup_s2_how_to_get_shows_official_portal_url(self, temp_config_dir, fake_keyring):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupKeyScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                menu = app.screen.query_one("#key-action-menu", SelectableMenu)
                menu.selected_index = 2  # "how_to_get"
                menu.focus()
                await pilot.press("enter")
                await pilot.pause()

                status = app.screen.query_one("#key-status-message", Static).render()
                assert "aistudio.google.com/app/apikey" in str(status)

        asyncio.run(_run())

    def test_setup_s2_save_unverified_saves_and_clears_secret(self, temp_config_dir, fake_keyring):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupKeyScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                key_input = app.screen.query_one("#key-input", Input)
                key_input.value = "UNVERIFIED_TEST_KEY_123"

                menu = app.screen.query_one("#key-action-menu", SelectableMenu)
                menu.selected_index = 1  # "save_unverified"
                menu.focus()
                await pilot.press("enter")
                await pilot.pause()

                # Key was saved to keyring
                resolved, source = CredentialService.resolve_key("gemini")
                assert resolved == "UNVERIFIED_TEST_KEY_123"
                assert source == "keyring"

                # Secret was cleared from input widget memory
                assert key_input.value == ""

                # Advanced to Step 4
                assert isinstance(app.screen, SetupStepPlaceholderScreen)
                assert app.screen.step == 4

        asyncio.run(_run())

    def test_setup_s2_verify_rejected_displays_actionable_error(self, temp_config_dir, fake_keyring):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupKeyScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                key_input = app.screen.query_one("#key-input", Input)
                key_input.value = "BAD_KEY_XYZ"

                # Mock verification rejection
                with patch.object(
                    CredentialService,
                    "verify_key",
                    return_value=VerificationResult(False, "rejected", "× Key rejected by Google Gemini.\nCheck the key and try again."),
                ):
                    menu = app.screen.query_one("#key-action-menu", SelectableMenu)
                    menu.selected_index = 0  # "verify"
                    menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()

                    # Stays on SetupKeyScreen
                    assert isinstance(app.screen, SetupKeyScreen)
                    status = app.screen.query_one("#key-status-message", Static).render()
                    assert "Key rejected by Google Gemini" in str(status)

                    # Key input retains entered value so user can edit or fix typos
                    assert key_input.value == "BAD_KEY_XYZ"

                    # Nothing stored in keyring
                    resolved, _ = CredentialService.resolve_key("gemini")
                    assert resolved is None

        asyncio.run(_run())

    def test_setup_s2_verify_success_saves_and_advances(self, temp_config_dir, fake_keyring):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupKeyScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                key_input = app.screen.query_one("#key-input", Input)
                key_input.value = "GOOD_VERIFIED_KEY"

                with patch.object(
                    CredentialService,
                    "verify_key",
                    return_value=VerificationResult(True, "verified", "✓ Key verified successfully with Google Gemini."),
                ):
                    menu = app.screen.query_one("#key-action-menu", SelectableMenu)
                    menu.selected_index = 0  # "verify"
                    menu.focus()
                    await pilot.press("enter")
                    await pilot.pause()

                    # Stored in keyring
                    resolved, source = CredentialService.resolve_key("gemini")
                    assert resolved == "GOOD_VERIFIED_KEY"
                    assert source == "keyring"

                    # Input cleared
                    assert key_input.value == ""

                    # Advanced to Step 4
                    assert isinstance(app.screen, SetupStepPlaceholderScreen)

        asyncio.run(_run())

    def test_setup_s2_back_wipes_secret_from_input(self, temp_config_dir, fake_keyring):
        async def _run():
            app = CircuitGenApp()
            async with app.run_test(size=(100, 30)) as pilot:
                screen = SetupKeyScreen(provider_id="gemini")
                await app.push_screen(screen)
                await pilot.pause()

                key_input = app.screen.query_one("#key-input", Input)
                key_input.value = "SECRET_SHOULD_BE_WIPED"

                # Press Esc to go back
                await pilot.press("escape")
                await pilot.pause()

                # Secret wiped
                assert key_input.value == ""

        asyncio.run(_run())

"""Settings screens for CircuitGen."""
from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Header, Select, Static

from circuitgen.ai import PROVIDER_DISPLAY_NAMES, list_providers
from circuitgen.export import OUTPUT_FORMATS
from ..services.config import AppConfig, ConfigService
from ..services.credentials import CredentialService
from ..services.models import ModelService, ProviderError
from ..widgets import EnhancedInput, MenuItem, PathPickerModal, SelectableMenu


THEME_LABELS = {
    "pcb-green": "PCB Green",
    "midnight-blue": "Midnight Blue",
    "light": "Light",
    "monochrome": "Monochrome",
    "terminal": "Regular terminal",
    "none": "No color",
}

FORMS = {
    "Generation": [
        ("fallback_policy", "Model fallback", [("Off", "off"), ("Try the provider's default model", "auto")]),
        ("retry_transient", "Retry temporary failures once", bool),
        ("essential_clarifications", "Ask when wiring is unclear", bool),
        ("request_timeout", "Request timeout (seconds)", int),
    ],
    "Output": [
        ("default_output_dir", "Output directory", str),
        ("output_format", "File format", [(name.upper(), name) for name in OUTPUT_FORMATS]),
        ("overwrite_confirmation", "Confirm before replacing files", bool),
        ("auto_open", "Open schematic after saving", bool),
        ("save_netlist", "Save JSON alongside schematic", bool),
    ],
    "Schematic Preferences": [
        ("background", "Background", str),
        ("component_color", "Component color", str),
        ("wire_color", "Wire color", str),
        ("text_color", "Text color", str),
        ("show_component_ids", "Show component IDs", bool),
        ("show_component_values", "Show component values", bool),
    ],
    "Interface": [
        ("interface_theme", "Theme", [(label, name) for name, label in THEME_LABELS.items()]),
        ("reduced_motion", "Reduce motion", bool),
    ],
}


class SettingsPage(Screen[None]):
    BINDINGS = [Binding("escape", "back", "Back")]
    title_text = "Settings"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static(f"CircuitGen / {self.title_text}", classes="breadcrumb-left")
                yield Static("─" * 62, classes="rule")
                yield from self.content()
                yield Static("", id="settings-status", classes="status-message", markup=False)
                yield Static("↑↓ Navigate  ·  Enter Select  ·  Esc Back  ·  Ctrl+Q Quit", classes="keys-reminder")

    def content(self) -> ComposeResult:
        raise NotImplementedError

    def action_back(self) -> None:
        self.app.pop_screen()

    def status(self, message: str) -> None:
        self.query_one("#settings-status", Static).update(message)

    def save(self, config: AppConfig) -> bool:
        try:
            ConfigService.save(config)
        except OSError:
            self.status("Could not save settings.")
            return False
        self.app.apply_preferences(config)
        return True


class ConfirmSettings(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]

    def __init__(self, prompt: str, action: str) -> None:
        super().__init__()
        self.prompt, self.confirm_label = prompt, action

    def compose(self) -> ComposeResult:
        with Vertical(classes="modal-dialog"):
            yield Static(self.prompt, classes="modal-title")
            yield SelectableMenu([
                MenuItem("cancel", "Cancel", ""),
                MenuItem("confirm", self.confirm_label, ""),
            ])

    def on_mount(self) -> None:
        self.query_one(SelectableMenu).focus()

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        self.dismiss(event.item.key == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class SettingsScreen(SettingsPage):
    def content(self) -> ComposeResult:
        yield SelectableMenu([MenuItem(name, name, "") for name in (
            "AI Providers", "Generation", "Output", "Schematic Preferences",
            "Interface", "Reset Settings", "Run Setup Again", "Back",
        )])

    def on_mount(self) -> None:
        self.query_one(SelectableMenu).focus()

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        choice = event.item.key
        if choice == "AI Providers":
            self.app.push_screen(ProviderSettings())
        elif choice in FORMS:
            self.app.push_screen(PreferenceForm(choice))
        elif choice == "Reset Settings":
            self.app.push_screen(
                ConfirmSettings("Restore defaults? Stored API keys will be kept.", "Restore defaults"),
                self._reset,
            )
        elif choice == "Run Setup Again":
            from .setup_welcome import SetupWelcomeScreen
            self.app.push_screen(SetupWelcomeScreen(restart=True))
        elif choice == "Back":
            self.action_back()

    def _reset(self, confirmed: bool | None) -> None:
        if confirmed and self.save(AppConfig(onboarding_status=ConfigService.load().onboarding_status)):
            self.status("Default settings restored.")


class PreferenceForm(SettingsPage):
    def __init__(self, category: str) -> None:
        super().__init__()
        self.category = category
        self.title_text = f"Settings / {category}"
        config = ConfigService.load()
        self.values = {name: getattr(config, name) for name, _, _ in FORMS[category]}
        if category == "Interface" and config.terminal_colors == "none":
            self.values["interface_theme"] = "none"

    def content(self) -> ComposeResult:
        if self.category == "Generation":
            yield Static("Trying another model may cost money.", classes="privacy-note")
        if self.category == "Interface":
            yield Static("Reduce motion turns off interface animations.", classes="privacy-note")
        yield SelectableMenu(self._items())

    def _items(self) -> list[MenuItem]:
        items = []
        for name, label, kind in FORMS[self.category]:
            value = self.values[name]
            if kind is bool:
                text = "On" if value else "Off"
            elif isinstance(kind, list):
                text = next((label for label, choice in kind if choice == value), kind[0][0])
            else:
                text = str(value) if value is not None else "Default"
            items.append(MenuItem(name, label, text))
        return [*items, MenuItem("save", "Save changes", ""), MenuItem("cancel", "Cancel", "")]

    def _update(self, name: str, value) -> None:
        self.values[name] = value
        menu = self.query_one(SelectableMenu)
        menu.set_items(self._items(), menu.selected_index)

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        name = event.item.key
        if name == "cancel":
            self.action_back()
            return
        if name == "save":
            config = ConfigService.load()
            values = self.values.copy()
            if self.category == "Interface":
                no_color = values["interface_theme"] == "none"
                values["terminal_colors"] = "none" if no_color else "auto"
                if no_color:
                    values["interface_theme"] = config.interface_theme
            if self.save(replace(config, **values)):
                self.action_back()
            return

        _, label, kind = next(field for field in FORMS[self.category] if field[0] == name)
        value = self.values[name]
        if kind is bool:
            self._update(name, not value)
        elif isinstance(kind, list):
            choices = [MenuItem(choice, label, "") for label, choice in kind]
            self.app.push_screen(
                ChoicePage(label, choices, value),
                lambda choice: self._update(name, choice) if choice is not None else None,
            )
        elif name == "background" or name.endswith("_color"):
            from .color_picker import ColorPicker

            def choose_color(color: str | None) -> None:
                if color is not None:
                    self._update(name, color or None)

            self.app.push_screen(ColorPicker(label, value, background=name == "background"), choose_color)
        else:
            self.app.push_screen(
                PreferenceInput(label, str(value), directory=name == "default_output_dir", number=kind is int),
                lambda new_value: self._update(name, new_value) if new_value is not None else None,
            )


class PreferenceInput(SettingsPage):
    def __init__(self, label: str, value: str, *, directory: bool = False, number: bool = False) -> None:
        super().__init__()
        self.title_text = f"Settings / {label}"
        self.value = value
        self.directory = directory
        self.number = number

    def content(self) -> ComposeResult:
        yield EnhancedInput(value=self.value, id="preference-value")
        options = [MenuItem("apply", "Apply", "")]
        if self.directory:
            options.append(MenuItem("browse", "Browse folders", ""))
        yield SelectableMenu([*options, MenuItem("cancel", "Cancel", "")])

    def on_input_submitted(self) -> None:
        self._apply()

    def _apply(self) -> None:
        value = self.query_one(EnhancedInput).value.strip()
        if not value:
            self.status("Enter a value.")
        elif self.number and (not value.isascii() or not value.isdecimal() or len(value) > 3 or not 1 <= int(value) <= 600):
            self.status("Enter 1 to 600 seconds.")
        else:
            self.dismiss(int(value) if self.number else value)

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        if event.item.key == "apply":
            self._apply()
        elif event.item.key == "browse":
            field = self.query_one(EnhancedInput)
            self.app.push_screen(
                PathPickerModal(initial_path=Path(field.value or "."), mode="directory"),
                lambda path: setattr(field, "value", str(path)) if path else None,
            )
        else:
            self.dismiss(None)

    def action_back(self) -> None:
        self.dismiss(None)


class ProviderSettings(SettingsPage):
    title_text = "Settings / AI Providers"

    def __init__(self, draft: AppConfig | None = None) -> None:
        super().__init__()
        self.draft = draft
        config = draft or ConfigService.load()
        if draft is not None:
            self.title_text = "Generate / Provider and Model"
        self.provider = config.default_provider
        self.model = config.explicit_model if config.model_mode == "manual" else None

    def content(self) -> ComposeResult:
        yield Static("Default provider", classes="input-field-label")
        yield Select(
            [(PROVIDER_DISPLAY_NAMES[provider], provider) for provider in list_providers()],
            value=self.provider, allow_blank=False, id="default-provider",
        )
        yield Static("Model ID (blank uses the provider default)", classes="input-field-label")
        yield EnhancedInput(
            value=self.model or "",
            placeholder=ModelService.get_recommended_model(self.provider),
            id="default-model",
        )
        yield Static("", id="key-source", markup=False)
        yield SelectableMenu([
            MenuItem("save", "Use for this schematic" if self.draft is not None else "Save changes", ""),
            MenuItem("discover", "Browse models", ""),
            MenuItem("test", "Test connection", ""),
            MenuItem("key", "Manage API key", ""),
            MenuItem("back", "Cancel", ""),
        ])

    def on_mount(self) -> None:
        self._show_key_source()

    def on_screen_resume(self) -> None:
        if self.is_mounted:
            self._show_key_source()

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.value in list_providers() and event.value != self.provider:
            self.provider = str(event.value)
            config = self.draft or ConfigService.load()
            self.model = (
                config.explicit_model
                if self.provider == config.default_provider and config.model_mode == "manual"
                else None
            )
            field = self.query_one("#default-model", EnhancedInput)
            field.value = self.model or ""
            field.placeholder = ModelService.get_recommended_model(self.provider)
            self.status("")
            self._show_key_source()

    def _show_key_source(self) -> None:
        _, source = CredentialService.resolve_key(self.provider)
        key = {
            "keyring": "Stored securely",
            "environment": f"From {CredentialService.get_provider_env_var(self.provider)}",
        }.get(source, "Not configured")
        self.query_one("#key-source", Static).update(f"API key: {key}")

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        choice = event.item.key
        if choice == "save":
            self._save_provider()
        elif choice in ("discover", "test"):
            self._check_provider(self.provider, choice)
        elif choice == "key":
            self.app.push_screen(KeySettings(self.provider))
        else:
            self.action_back()

    @work(exclusive=True, group="provider-request")
    async def _save_provider(self) -> None:
        provider = self.provider
        field = self.query_one("#default-model", EnhancedInput)
        raw_model = field.value.strip()
        model = raw_model.removeprefix("models/") if provider == "gemini" else raw_model
        if raw_model:
            valid, message = ModelService.validate_model_id(model)
            if not valid:
                self.status(message)
                return
        if model and model != self.model:
            self.status("Checking the provider's model list...")
            try:
                models = await asyncio.to_thread(ModelService.discover_models, provider)
            except ProviderError as exc:
                self.status(str(exc))
                return
            if provider != self.provider or raw_model != field.value.strip() or self.app.screen is not self:
                self.status("")
                return
            if model not in models:
                self.status("The provider did not list that ID. Check it or use Browse models.")
                return
        config = replace(self.draft or ConfigService.load(), default_provider=provider,
                         explicit_model=model or None, model_mode="manual" if model else "automatic")
        if self.draft is not None:
            self.dismiss(config)
        elif self.save(config):
            self.action_back()

    def action_back(self) -> None:
        if self.draft is not None:
            self.dismiss(None)
        else:
            super().action_back()

    @work(exclusive=True, group="provider-request")
    async def _check_provider(self, provider: str, action: str) -> None:
        self.status("Contacting provider...")
        if action == "test":
            key, _ = CredentialService.resolve_key(provider)
            if not key:
                self.status("Add an API key first.")
                return
            response = await asyncio.to_thread(CredentialService.verify_key, provider, key)
            if self.provider == provider:
                self.status(response.message)
            return
        try:
            models = await asyncio.to_thread(ModelService.discover_models, provider)
        except ProviderError as exc:
            self.status(str(exc))
            return
        if self.provider == provider and self.app.screen is self:
            self.status("")
            self.app.push_screen(ModelChoices(models), self._select_model)

    def _select_model(self, model: str | None) -> None:
        if model:
            self.model = model
            self.query_one("#default-model", EnhancedInput).value = model


class ChoicePage(SettingsPage):
    def __init__(self, title: str, choices: list[MenuItem], selected: str | None = None) -> None:
        super().__init__()
        self.title_text = f"Settings / {title}"
        self.choices = choices
        self.initial_index = next((i for i, item in enumerate(choices) if item.key == selected), 0)

    def content(self) -> ComposeResult:
        yield SelectableMenu(self.choices, initial_index=self.initial_index, max_visible=10)

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        self.dismiss(event.item.key)

    def action_back(self) -> None:
        self.dismiss(None)


class ModelChoices(ChoicePage):
    def __init__(self, models: list[str]) -> None:
        super().__init__("Browse Models", [MenuItem(model, model, "") for model in models])

    def content(self) -> ComposeResult:
        if self.choices:
            yield Static("A listed model may still require access or payment.")
            yield from super().content()
        else:
            yield Static("The provider returned no models.")


class KeySettings(SettingsPage):
    def __init__(self, provider: str) -> None:
        super().__init__()
        self.provider = provider
        self.title_text = f"Settings / API Keys / {PROVIDER_DISPLAY_NAMES[provider]}"

    def content(self) -> ComposeResult:
        _, source = CredentialService.resolve_key(self.provider)
        self._shown_source = source
        if source == "environment":
            yield Static(f"Managed by {CredentialService.get_provider_env_var(self.provider)} outside CircuitGen.")
            options = []
        elif source == "keyring":
            options = [MenuItem("replace", "Replace API key", ""), MenuItem("remove", "Remove stored key", "")]
        else:
            options = [MenuItem("replace", "Add API key", "")]
        yield SelectableMenu([*options, MenuItem("back", "Back", "")])

    def on_screen_resume(self) -> None:
        if self.is_mounted and CredentialService.resolve_key(self.provider)[1] != self._shown_source:
            self.refresh(recompose=True)

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        from .setup_key import SetupKeyScreen

        choice = event.item.key
        if choice == "back":
            self.action_back()
            return
        _, source = CredentialService.resolve_key(self.provider)
        if source == "environment":
            self.status("This key is managed outside CircuitGen.")
        elif choice == "replace":
            self.app.push_screen(SetupKeyScreen(self.provider, settings=True))
        elif choice == "remove":
            self.app.push_screen(
                ConfirmSettings("Remove CircuitGen's stored key? It will still work at the provider.", "Remove key"),
                self._remove_key,
            )

    def _remove_key(self, confirmed: bool | None) -> None:
        if confirmed and CredentialService.resolve_key(self.provider)[1] != "environment":
            if CredentialService.delete_key(self.provider):
                self.refresh(recompose=True)
            else:
                self.status("Could not remove the stored key.")

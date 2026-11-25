"""Generate a schematic from a circuit description."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future
from functools import partial
from pathlib import Path
from threading import Thread
from typing import Awaitable, Callable, TypeVar

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Header, Static
from textual.worker import Worker, get_current_worker

from circuitgen.ai import ClarificationRequired, PROVIDER_DISPLAY_NAMES, ProviderRequestError, generate_netlist
from circuitgen.api import from_netlist
from circuitgen.engine import CircuitError
from ..services.config import AppConfig, ConfigService
from ..services.credentials import CredentialService
from ..services.models import ModelService, ProviderError
from ..widgets import EnhancedInput, JsonEditor, MenuItem, PathPickerModal, SelectableMenu
from .render import RenderSuccessScreen, confirm_output, schematic_path, write_outputs
from .settings import ProviderSettings


T = TypeVar("T")


async def run_generation_stage(operation: Callable[[], T]) -> T:
    result: Future[T] = Future()

    def run() -> None:
        if result.set_running_or_notify_cancel():
            try:
                result.set_result(operation())
            except Exception as exc:
                result.set_exception(exc)

    # A cancelled generation can leave an HTTP request waiting for its timeout.
    # The background stages never write files, so quitting need not wait for them.
    Thread(target=run, daemon=True).start()
    return await asyncio.wrap_future(result)


class GenerateScreen(Screen[None]):
    BINDINGS = [Binding("escape", "back", "Back or cancel")]

    def __init__(self, config: AppConfig | None = None) -> None:
        super().__init__()
        self.config = config or ConfigService.load()
        self.generation: Worker | None = None
        self.progress: GenerationProgress | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                with Horizontal(classes="breadcrumb-row"):
                    yield Static("CircuitGen / Generate", classes="breadcrumb-left")
                yield Static("─" * 62, classes="rule")
                yield Static("Describe your circuit", classes="input-field-label")
                yield JsonEditor(language=None, id="generate-description")
                yield Static(self._provider_label(), id="generate-provider", markup=False)
                yield Static("Output directory", classes="input-field-label")
                yield EnhancedInput(value=self.config.default_output_dir, id="generate-directory")
                yield Static("Filename", classes="input-field-label")
                yield EnhancedInput(value=f"circuit.{self.config.output_format}", id="generate-filename")
                yield SelectableMenu(self._actions(), id="generate-menu")
                yield Static("", id="generate-status", classes="status-message", markup=False)
                yield Static("Tab Next field  ·  Esc Back or cancel  ·  Ctrl+Q Quit", classes="keys-reminder")

    def on_mount(self) -> None:
        self.query_one(JsonEditor).focus()

    def _provider_label(self) -> str:
        provider = self.config.default_provider
        model = self.config.explicit_model or ModelService.get_recommended_model(provider)
        return f"{PROVIDER_DISPLAY_NAMES[provider]} · {model}"

    def _actions(self) -> list[MenuItem]:
        return [
            MenuItem("generate", "Generate schematic", ""),
            MenuItem("provider", "Change provider / model", ""),
            MenuItem("browse", "Browse output folders", ""),
            MenuItem("back", "Back to home", ""),
        ]

    def set_status(self, message: str) -> None:
        self.query_one("#generate-status", Static).update(message)

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        choice = event.item.key
        if choice == "generate":
            self._submit()
        elif choice == "provider":
            self.app.push_screen(ProviderSettings(self.config), self._use_provider)
        elif choice == "browse":
            field = self.query_one("#generate-directory", EnhancedInput)
            self.app.push_screen(
                PathPickerModal(initial_path=field.value.strip() or ".", mode="directory"),
                lambda path: setattr(field, "value", str(path)) if path else None,
            )
        else:
            self.action_back()

    def _use_provider(self, config: AppConfig | None) -> None:
        if config is not None:
            self.config = config
            self.query_one("#generate-provider", Static).update(self._provider_label())
            self.set_status("")

    def _submit(self) -> None:
        description = self.query_one(JsonEditor).text.strip()
        directory = self.query_one("#generate-directory", EnhancedInput).value.strip()
        filename = self.query_one("#generate-filename", EnhancedInput).value.strip()
        if not description or not directory or not filename:
            self.set_status("Enter a circuit description, output directory, and filename.")
            return

        config = self.config
        key, _ = CredentialService.resolve_key(config.default_provider)
        if not key:
            self.set_status("Add an API key using Change provider / model, then try again.")
            return
        try:
            dest = schematic_path(directory, filename, config.output_format)
        except (OSError, ValueError):
            self.set_status("Enter a valid output directory and filename.")
            return
        sidecar = dest.with_suffix(".json") if config.save_netlist else None
        targets = [dest, sidecar] if sidecar else [dest]
        confirm_output(
            self, targets, config.overwrite_confirmation,
            lambda approved: self._start(description, config, key, dest, sidecar, approved),
        )

    def _set_busy(self, busy: bool) -> None:
        for field in self.query("Input, TextArea"):
            field.disabled = busy
        menu = self.query_one(SelectableMenu)
        menu.set_items([MenuItem("cancel", "Cancel generation", "")] if busy else self._actions())
        menu.focus()

    def _start(self, description: str, config: AppConfig, key: str, dest: Path,
               sidecar: Path | None, approved: set[Path]) -> None:
        self._set_busy(True)
        self.set_status("")
        self.progress = GenerationProgress(dest, self.action_back)
        mounted = self.app.push_screen(self.progress)
        self.generation = self._generate(description, config, key, dest, sidecar, approved, mounted)

    def _progress(self, completed: int, text: str) -> None:
        if self.progress is not None:
            self.progress.update_stage(completed, text)

    def _close_progress(self) -> None:
        if self.progress is not None and self.app.screen is self.progress:
            self.app.pop_screen()
        self.progress = None

    @work(exclusive=True)
    async def _generate(self, description: str, config: AppConfig, key: str, dest: Path,
                        sidecar: Path | None, approved: set[Path], mounted: Awaitable) -> None:
        default_model = ModelService.get_recommended_model(config.default_provider)
        actual_model = config.explicit_model if config.model_mode == "manual" else default_model

        def report_model(model: str) -> None:
            nonlocal actual_model
            actual_model = model

        try:
            await mounted
            try:
                models = await run_generation_stage(partial(
                    ModelService.discover_models, config.default_provider, api_key=key,
                ))
            except ProviderError as exc:
                self.set_status(f"Could not check models for this API key. {exc}")
                return
            if actual_model not in models:
                self.set_status("The selected model is not listed for this API key. Use Browse models to choose another.")
                return

            self._progress(1, "Waiting for the provider to return a netlist…")
            try:
                netlist = await run_generation_stage(partial(
                    generate_netlist, description,
                    provider=config.default_provider,
                    model=actual_model,
                    api_key=key, timeout=config.request_timeout, retry_transient=config.retry_transient,
                    allow_model_fallback=config.fallback_policy == "auto" and default_model in models,
                    clarify=config.essential_clarifications, on_model=report_model,
                ))
            except ClarificationRequired:
                self.set_status("The provider needs more wiring details. Edit the description and try again.")
                return
            except ProviderRequestError as exc:
                message = {
                    401: "The provider rejected the API key.",
                    403: "The provider denied access. Check the key and model.",
                    404: "The provider listed this model but rejected it for generation. Choose another model.",
                    429: "The provider is limiting requests. Try again later.",
                    503: "The provider is temporarily unavailable (HTTP 503). Try again later.",
                }.get(exc.status, str(exc))
                self.set_status(message)
                return
            except CircuitError:
                self.set_status("The provider did not return a usable netlist. Try again or edit the description.")
                return
            except Exception:
                self.set_status("Could not get a netlist from the provider. Try again.")
                return

            self._progress(2, "Validating and rendering the netlist…")

            def render_output():
                result = from_netlist(netlist, style=config.schematic_style(), output_format=config.output_format)
                return result, result.encode()

            try:
                result, payload = await run_generation_stage(render_output)
            except (CircuitError, ValueError, RuntimeError) as exc:
                self.set_status(f"Could not render the netlist: {exc}")
                return
            except Exception:
                self.set_status("Could not export the schematic. Check the output settings and try again.")
                return

            if not self.app.is_running:
                return
            self._progress(3, "Saving schematic…")
            await self.app.wait_for_refresh()
            if not self.app.is_running:
                return
            ok, notice = write_outputs(payload, dest, result.netlist, sidecar, approved)
            if not ok:
                self.set_status(notice)
                return

            success = RenderSuccessScreen(
                dest, "", len(result.model.components), len(result.model.nets), result.netlist,
                ai_source=(PROVIDER_DISPLAY_NAMES[config.default_provider], actual_model),
                another=lambda: self.app.switch_screen(GenerateScreen(config)),
            )
            self.set_status("")
            self._close_progress()
            self.app.switch_screen(success)
            success.call_after_refresh(lambda: success.show_saved_status(notice, config.auto_open))
        finally:
            if self.generation is get_current_worker():
                self.generation = None
                if self.app.is_running:
                    self._close_progress()
                if self.is_mounted and self.app.screen is self:
                    self._set_busy(False)

    def action_back(self) -> None:
        if self.generation is not None:
            worker, self.generation = self.generation, None
            worker.cancel()
            self._close_progress()
            self._set_busy(False)
            self.set_status("Generation cancelled.")
        else:
            self.app.pop_screen()


class GenerationProgress(ModalScreen[None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]
    CHECKPOINTS = ("Check model", "Get netlist", "Render", "Save")

    def __init__(self, dest: Path, cancel: Callable[[], None]) -> None:
        super().__init__()
        self.dest, self.cancel = dest, cancel

    def compose(self) -> ComposeResult:
        with Container(id="home-container"):
            with Vertical(id="home-card"):
                yield Static("Generating schematic", classes="setup-title")
                with Horizontal(id="generation-progress"):
                    for index, label in enumerate(self.CHECKPOINTS):
                        classes = "generation-checkpoint current" if index == 0 else "generation-checkpoint"
                        yield Static(f"{index + 1} {label}", classes=classes)
                yield Static("Step 1 of 4 · Checking models for your API key…",
                             id="generation-stage", classes="status-message")
                yield Static(f"Output: {self.dest}", markup=False)
                yield SelectableMenu([MenuItem("cancel", "Cancel generation", "")])
                yield Static("Esc Cancel  ·  Ctrl+Q Quit", classes="keys-reminder")

    def update_stage(self, completed: int, text: str) -> None:
        for index, (block, label) in enumerate(zip(self.query(".generation-checkpoint").results(Static), self.CHECKPOINTS)):
            block.set_class(index < completed, "complete")
            block.set_class(index == completed, "current")
            block.update(f"✓ {label}" if index < completed else f"{index + 1} {label}")
        self.query_one("#generation-stage", Static).update(f"Step {completed + 1} of 4 · {text}")

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        self.cancel()

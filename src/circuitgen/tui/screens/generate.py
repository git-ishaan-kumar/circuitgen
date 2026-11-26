"""Generate a schematic from a circuit description."""
from __future__ import annotations

import asyncio
from functools import partial
from pathlib import Path
from typing import Awaitable, Callable

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Header, Input, Static
from textual.worker import Worker, get_current_worker

from circuitgen.ai import (ClarificationRequired, NetlistGenerationError,
                           PROVIDER_DISPLAY_NAMES, ProviderRequestError,
                           RequestDecisionError, decide_request, generate_netlist)
from circuitgen.api import from_netlist
from circuitgen.engine import CircuitError
from ..services.config import AppConfig, ConfigService
from ..services.credentials import CredentialService
from ..services.models import ModelService, ProviderError
from ..services.background import run_background_stage as run_generation_stage
from ..widgets import EnhancedInput, JsonEditor, MenuItem, PathPickerModal, SelectableMenu
from .render import (RenderSuccessScreen, ViewNetlistScreen, confirm_output,
                     schematic_path, write_outputs)
from .settings import ProviderSettings


class GenerateScreen(Screen[None]):
    BINDINGS = [Binding("escape", "back", "Back or cancel")]

    def __init__(self, config: AppConfig | None = None) -> None:
        super().__init__()
        self.config = config or ConfigService.load()
        self.generation: Worker | None = None
        self.progress: GenerationProgress | None = None
        self.clarification_answer = ""
        self.clarification_source = ""
        self.assumptions: list[str] = []
        self.clarification_rounds = 0

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
        if not description or not filename:
            self.set_status("Enter a circuit description and filename.")
            return
        if description != self.clarification_source:
            self.clarification_answer = ""
            self.assumptions = []
            self.clarification_rounds = 0
        decision = decide_request(description)
        if decision.status in ("refused", "out_of_scope"):
            self.set_status(str(RequestDecisionError(decision.status)))
            return
        if decision.status == "needs_clarification" and not self.clarification_answer:
            if not self.config.essential_clarifications:
                self.set_status("Wiring is unclear. Edit the description or enable clarifications in Settings.")
                return
            self.app.push_screen(ClarificationScreen(decision.question, decision.assumption),
                                 lambda choice: self._use_clarification(description, choice))
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
            lambda approved: self._start(
                description + (f"\nClarification: {self.clarification_answer}" if self.clarification_answer else ""),
                config, key, dest, sidecar, approved),
        )

    def _use_clarification(self, description: str, choice: tuple[str, bool] | None) -> None:
        if choice is None:
            return
        answer, assumed = choice
        if not answer:
            self.set_status("Cannot determine the wiring without inventing it. Edit the description.")
            return
        self.clarification_source = description
        self.clarification_answer = answer
        self.clarification_rounds += 1
        if assumed:
            self.assumptions.append(answer)
        self._submit()

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

    def _show_netlist_failure(self, netlist: dict, message: str) -> None:
        self._close_progress()
        self._set_busy(False)
        self.set_status(message)
        self.app.push_screen(ViewNetlistScreen(
            netlist,
            source_file="Render failed",
            notice=message,
            back_label="Back to Generate",
        ))

    def _close_progress(self) -> None:
        if self.progress is not None and self.app.screen is self.progress:
            self.app.pop_screen()
        self.progress = None

    @work(exclusive=True, description="Generate schematic")
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
            except ClarificationRequired as exc:
                self._close_progress()
                self._set_busy(False)
                if not config.essential_clarifications:
                    self.set_status("Wiring is unclear. Edit the description or enable clarifications in Settings.")
                    return
                if self.clarification_rounds >= 2:
                    self.set_status("More wiring details are needed. Edit the description and try again.")
                    return
                self.app.push_screen(ClarificationScreen(exc.question, exc.assumption),
                                     lambda choice: self._use_clarification(
                                         self.query_one(JsonEditor).text.strip(), choice))
                return
            except RequestDecisionError as exc:
                self.set_status(str(exc))
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
            except NetlistGenerationError as exc:
                self._show_netlist_failure(
                    exc.netlist,
                    f"The provider returned an invalid netlist after correction attempts: {exc}",
                )
                return
            except CircuitError:
                self.set_status("The provider did not return a usable netlist. Try again or edit the description.")
                return
            except Exception:
                self.set_status("Could not get a netlist from the provider. Try again.")
                return

            self._progress(2, "Validating and rendering the netlist…")

            def render_output():
                result = from_netlist(netlist, output=None, style=config.schematic_style(),
                                      output_format=config.output_format)
                return result, result.encode()

            try:
                result, payload = await run_generation_stage(render_output)
            except Exception as exc:
                self._show_netlist_failure(netlist, f"Could not render the netlist: {exc}")
                return

            if not self.app.is_running:
                return
            self._progress(3, "Saving schematic…")
            await asyncio.sleep(0)
            if not self.app.is_running or self.generation is not get_current_worker():
                return
            ok, notice = write_outputs(payload, dest, result.netlist, sidecar, approved)
            if not ok:
                self.set_status(notice)
                return
            self._progress(4, "Schematic saved.")
            await asyncio.sleep(0.25)
            if not self.app.is_running:
                return

            success = RenderSuccessScreen(
                dest, "", len(result.model.components), len(result.model.nets), result.netlist,
                ai_source=(PROVIDER_DISPLAY_NAMES[config.default_provider], actual_model),
                assumptions=tuple(self.assumptions),
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


class ClarificationScreen(ModalScreen[tuple[str, bool] | None]):
    BINDINGS = [Binding("escape", "cancel", "Edit description")]

    def __init__(self, question: str, assumption: str = "") -> None:
        super().__init__()
        self.question = question
        self.assumption = assumption

    def compose(self) -> ComposeResult:
        with Container(id="generation-progress-card"):
            yield Static("More information needed", classes="setup-title")
            yield Static(self.question, markup=False)
            yield EnhancedInput(placeholder="Type your answer", id="clarification-answer")
            yield SelectableMenu([
                MenuItem("answer", "Continue with answer", ""),
                MenuItem("skip", "Skip", ""),
                MenuItem("edit", "Edit description", ""),
            ])
            yield Static("Tab Next field  ·  Esc Edit  ·  Ctrl+Q Quit", classes="keys-reminder")

    def on_mount(self) -> None:
        self.query_one("#clarification-answer", EnhancedInput).focus()

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        if event.item.key == "answer":
            answer = self.query_one("#clarification-answer", EnhancedInput).value.strip()
            if answer:
                self.dismiss((answer, False))
        elif event.item.key == "skip":
            self.dismiss((self.assumption, bool(self.assumption)))
        else:
            self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        answer = event.value.strip()
        if answer:
            self.dismiss((answer, False))

    def action_cancel(self) -> None:
        self.dismiss(None)


class GenerationProgress(ModalScreen[None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel", priority=True)]
    CHECKPOINTS = ("Check model", "Get netlist", "Render", "Save")

    def __init__(self, dest: Path, cancel: Callable[[], None]) -> None:
        super().__init__()
        self.dest, self.cancel = dest, cancel
        self.completed = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="generation-card"):
            yield Static("Generating schematic", classes="setup-title")
            yield Static("Step 1 of 4 · Checking models for your API key…",
                         id="generation-stage", classes="status-message")
            with Horizontal(id="generation-progress-bar"):
                for index in range(len(self.CHECKPOINTS)):
                    classes = "generation-segment current" if index == 0 else "generation-segment"
                    yield Static("", classes=classes)
            with Horizontal(id="generation-checkpoints"):
                for index, label in enumerate(self.CHECKPOINTS):
                    classes = "generation-checkpoint current" if index == 0 else "generation-checkpoint"
                    yield Static(label, classes=classes)
            yield SelectableMenu([MenuItem("cancel", "Cancel generation", "")])
            yield Static("Esc Cancel  ·  Ctrl+Q Quit", id="generation-shortcuts", classes="keys-reminder")

    def update_stage(self, completed: int, text: str) -> None:
        completed = max(0, min(completed, len(self.CHECKPOINTS)))
        self.completed = completed
        for index, label in enumerate(self.query(".generation-checkpoint").results(Static)):
            label.set_class(index < completed, "complete")
            label.set_class(index == completed, "current")
            label.update(f"✓ {self.CHECKPOINTS[index]}" if index < completed else self.CHECKPOINTS[index])
        for index, segment in enumerate(self.query(".generation-segment").results(Static)):
            segment.set_class(index < completed, "complete")
            segment.set_class(index == completed, "current")
        status = "Schematic saved." if completed == len(self.CHECKPOINTS) else text
        step = "Complete" if completed == len(self.CHECKPOINTS) else f"Step {completed + 1} of 4"
        self.query_one("#generation-stage", Static).update(f"{step} · {status}")
        self.query_one(SelectableMenu).display = completed < len(self.CHECKPOINTS)
        self.query_one("#generation-shortcuts", Static).update(
            "Esc Cancel  ·  Ctrl+Q Quit" if completed < len(self.CHECKPOINTS) else "Ctrl+Q Quit"
        )

    def on_selectable_menu_selected(self, event: SelectableMenu.Selected) -> None:
        self.action_cancel()

    def action_cancel(self) -> None:
        if self.completed >= len(self.CHECKPOINTS):
            return
        self.cancel()

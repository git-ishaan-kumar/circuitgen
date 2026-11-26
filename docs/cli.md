# CircuitGen CLI

This guide describes the 0.2.0 source version. The Python package is named `circuitgen`; its terminal command is `circuit`. An older published release may still use the old command until 0.2.0 is published.

## Install and start

Use Python 3.10 or newer. From this repository, run `python -m pip install -e .`. Once 0.2.0 is published, `python -m pip install circuitgen` or `pipx install circuitgen` installs the same package. Run `circuit` to open the terminal interface. `python -m circuitgen` is also available when the launcher is not on PATH. Run `circuit doctor` for installation checks. On Windows, `python -m circuitgen setup-path --check` checks whether the launcher's folder is on PATH; `python -m circuitgen setup-path` offers to add it.

The first launch offers setup for an AI provider, API key, and model. You can skip it and use Render or Validate offline. Settings lets you run setup again later. Keys saved in the app go to the operating system's secure credential store, when available. You can also set the provider's environment variable, such as `GEMINI_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY`. Environment variables take precedence over stored keys. CircuitGen does not put API keys in its settings file. If secure storage is unavailable, use an environment variable.

Generate supports Gemini, OpenAI, Anthropic, DeepSeek, Groq, Mistral, xAI, OpenRouter, Together, Fireworks, and Cerebras. Provider access, quotas, pricing, and available models depend on your account. Browse models in Settings to query a provider's model list where supported. A listed model can still fail when requested. A connection test checks the key; it does not prove that a particular model is available or free.

## Use the terminal interface

- **Generate** sends a circuit description to the selected AI provider, checks the returned netlist, then renders it. It needs an API key and network access. A failed render shows the generated JSON in the built-in netlist viewer so you can inspect or copy it.
- **Render** opens a JSON netlist file or accepts pasted JSON and exports a schematic. It needs no AI key or network access.
- **Validate** checks a JSON netlist from a file or pasted text without creating a schematic. It needs no AI key or network access.
- **Settings** stores output, generation, appearance, and interface preferences. Choose SVG, PNG, or PDF for output. Reset Settings keeps stored API keys.
- **Help** shows examples, shortcuts, and common fixes.

Use arrows and Enter for menus. Tab and Shift+Tab move between fields. Esc goes back or cancels the current action. Ctrl+Q quits. In the circuit description editor, Enter continues a numbered or bulleted list; Enter or Backspace on an empty list item removes its marker. The JSON editor inserts ordinary newlines. Text fields support Ctrl+A, Ctrl+C, and Ctrl+V. Copy and paste also depend on the terminal: some terminals intercept these shortcuts. Right-click text to copy it or blank space to paste into a focused field. If the screen is cramped, use a terminal at least 80 columns by 24 rows.

Generate and Render ask before replacing an existing output file, unless overwrite confirmation is disabled in Settings. They can create a missing output folder after confirmation. A blank output directory uses the current working directory. The saved file extension controls SVG, PNG, or PDF output. Render can optionally save the JSON netlist next to the schematic. For difficult routing failures, the app keeps the netlist available for inspection; it does not silently drop connections.

## Direct commands

Run `circuit --help` for the command list or `circuit help render` for one command.

```sh
circuit generate "A 9V battery connected to an LED through a 330 ohm resistor." -o led.svg
circuit render circuit.json -o circuit.png
circuit validate circuit.json
circuit config --show
```

| Command | Inputs and options | Result |
| --- | --- | --- |
| `generate` | Description argument **or** `--stdin`; `--provider ID`, `--model ID`, `-o/--output FILE`, `--force`, `--no-color` | Generates a netlist using AI and saves a schematic. Provider and model default to Settings. |
| `render` | JSON file **or** `--stdin`; `-o/--output FILE`, `--force`, `--no-color` | Validates and saves a schematic offline. |
| `validate` | JSON file **or** `--stdin`; `--no-color` | Checks a netlist offline; saves nothing. |
| `config` | `--show`, `--no-color` | Shows preferences without API keys. Without `--show`, opens Settings in a terminal; when piped, it prints the same safe settings JSON. |
| `help` | Optional topic: `generate`, `render`, `validate`, `config`; `--no-color` | Prints command help. |
| `doctor` | `--debug` | Runs read-only installation and terminal checks. |
| `setup-path` | `--check`, `--yes` | Checks or configures the Windows user PATH. `--yes` skips its confirmation prompt. |

Top-level `--version` prints the installed version; top-level `--debug` shows full errors when launching the app. `--no-color` requests plain output. The direct commands default to `circuit.<format>` in the current working directory, using the format selected in Settings. Use a `.svg`, `.png`, or `.pdf` extension with `-o` to choose a format. Direct commands refuse to replace an existing file unless you pass `--force`.

`--stdin` replaces the positional input, rather than adding to it. For example:

```sh
cat circuit.json | circuit validate --stdin
cat circuit.json | circuit render --stdin -o circuit.pdf
```

Direct commands return exit code 0 on success, 1 for input, validation, provider, or file errors, and 2 for invalid command syntax. `render` and `validate` remain usable without provider credentials. See the [README](../README.md) for the Python API, netlist format, and schematic customization.

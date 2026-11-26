# CircuitGen

A Python library and CLI for generating circuit schematics from text descriptions or netlists.

CircuitGen takes a circuit netlist, places components, routes wires, and exports clean SVG schematics. It includes AI translation that converts natural-language prompts into valid netlists using a chosen provider.

## Installation

### Recommended: Using pipx (CLI application)
If you want to use the `circuitgen` interactive CLI tool directly in your terminal, we recommend installing via [pipx](https://pypa.github.io/pipx/), which isolates dependencies and automatically ensures scripts are on your system `PATH`:

```bash
pipx install circuitgen
```

### Standard: Using pip
To install CircuitGen as a library or CLI in your Python environment:

```bash
pip install circuitgen
```

Or install from source:

```bash
git clone https://github.com/git-ishaan-kumar/circuitgen.git
cd circuitgen
pip install -e .
```

Requires Python 3.10 or higher.

## Running CircuitGen

You can launch the interactive terminal interface using either:

```bash
circuitgen
```

Or using the universal cross-platform Python module entrypoint:

```bash
python -m circuitgen
```

Both entrypoints run the exact same CLI. If your terminal cannot find the `circuitgen` command, `python -m circuitgen` always works without requiring PATH changes.

### PATH Troubleshooting

If you installed via `pip install circuitgen` (or `--user`) and typing `circuitgen` produces `"command not found"` or `'circuitgen' is not recognized`:

* **Windows:**
  * Python's user scripts directory is usually located at:
    * Python Launcher / Store: `%LOCALAPPDATA%\Python\pythoncore-...\Scripts`
    * Standard CPython: `%APPDATA%\Python\Python3X\Scripts`
    * You can check your exact scripts directory by running:
      ```powershell
      python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
      ```
  * In **Git Bash** or **PowerShell**, add this directory to your user `PATH` environment variable in Windows Settings, or run `python -m circuitgen`.
  * Alternatively, run `pipx ensurepath` if using `pipx`.

* **macOS:**
  * Pip user binaries are usually in `~/Library/Python/3.X/bin` (or `/opt/homebrew/bin`).
  * Add it to your shell configuration (`~/.zshrc` or `~/.bash_profile`):
    ```bash
    export PATH="$HOME/Library/Python/$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')/bin:$PATH"
    ```
  * Or use `python3 -m circuitgen`.

* **Linux:**
  * Pip user binaries are usually in `~/.local/bin`.
  * Add it to your shell configuration (`~/.bashrc` or `~/.zshrc`):
    ```bash
    export PATH="$HOME/.local/bin:$PATH"
    ```
  * Or use `python3 -m circuitgen`.

## Quickstart

### 1. From a Netlist (Offline, No API Key)

```python
from circuitgen import from_netlist

netlist = {
    "components": [
        {"id": "V1", "type": "battery", "value": "9V"},
        {"id": "R1", "type": "resistor", "value": "330Ω"},
        {"id": "D1", "type": "led", "value": "red"},
    ],
    "nets": [
        {"name": "VCC", "pins": ["V1.p", "R1.a"]},
        {"name": "MID", "pins": ["R1.b", "D1.a"]},
        {"name": "GND", "pins": ["D1.b", "V1.n"]},
    ],
}

# Save to the working directory, using circuit.svg when no output is given
result = from_netlist(netlist)
print(f"Saved schematic to {result.output_path}")

# Or access the SVG string directly in memory
svg_markup = from_netlist(netlist, output=None).svg
```

Relative output filenames are saved from the current working directory.
Omitting `output` or passing `output=""` uses `circuit.svg` there. Pass
`output=None` to keep the result in memory without saving a file. In the CLI,
a blank output directory uses the current working directory, which is also the
default for new settings.

### Export formats and appearance

SVG is the default, with the same transparent background and styling as earlier
versions. CircuitGen also exports PNG images and single-page raster PDF files.
All three formats work offline from a netlist.

```python
from circuitgen import SchematicStyle, from_netlist, render

style = SchematicStyle(
    background="white",
    component_color="#213149",
    wire_color="#246548",
    text_color="#17243c",
    show_component_ids=True,
    show_component_values=False,
)

result = from_netlist(netlist, output="circuit.png", style=style)
result.save("circuit.pdf")
pdf_bytes = render(netlist, style=style, output_format="pdf")
```

- `from_netlist()`, `generate()`, and `render()` accept `style=SchematicStyle(...)` and
  `output_format="svg"`, `"png"`, or `"pdf"`. When saving, CircuitGen infers the
  format from a recognized filename extension unless you pass `output_format`.
- `render()` and `CircuitResult.encode()` return SVG as text and PNG or PDF as
  bytes. `CircuitResult.svg` always contains SVG markup, regardless of the
  chosen output format.
- Background accepts `"transparent"`, `"white"`, `"black"`, or a six-digit hex
  color. Color overrides accept six-digit hex colors. Omitted overrides keep
  the existing renderer colors. The original `color` and `optimize` arguments
  still work.
- Hiding component IDs or values leaves pin labels, net labels, and polarity
  marks visible. PDF is image-based. Most PDF viewers display transparent
  areas against a white page.

### 2. From Natural Language (AI)

Set your provider's API key in your environment first:

```bash
export GEMINI_API_KEY="your-key-here"
# or for OpenAI: export OPENAI_API_KEY="your-key-here"
# or for Anthropic: export ANTHROPIC_API_KEY="your-key-here"
```

Then generate:

```python
from circuitgen import generate

result = generate(
    "A 9V battery powering a red LED with a 330 ohm current limiting resistor",
    provider="gemini",
    output="ai_circuit.svg",
)

print(result.netlist)
print(result.output_path)
```

Supported providers: `gemini`, `openai`, `anthropic`, `deepseek`, `groq`, `mistral`, `xai`, `openrouter`, `together`, `fireworks`, `cerebras`.

`generate()` also accepts `timeout` in seconds, `retry_transient=True` for one
retry after a temporary failure, and `allow_model_fallback=True` to try the
same provider's default model when a selected model returns HTTP 404. Retries
and fallback are opt-in in the Python API. With `clarify=True`, a provider
request for essential wiring information raises `ClarificationRequired`.
`decide_request(description)` reports clear requests as `ready`, ambiguous wiring as
`needs_clarification`, unrelated requests as `out_of_scope`, and clearly harmful
purposes as `refused`. The same checks run before every provider call. A refusal
or out-of-scope result raises `RequestDecisionError`, with its reason in `.status`.
For a clarification, use the exception's `.question` to ask the user, then
include their answer in a revised description. An available `.assumption` may
be used only after telling the user what it is; it is empty when Skip cannot
produce a defensible circuit.

If the AI returns a netlist that stays invalid after correction attempts,
`generate_netlist()` raises `NetlistGenerationError`. If a generated or supplied
netlist cannot be rendered, `generate()`, `from_netlist()`, and `render()` raise
`NetlistRenderError`. Both are `CircuitError` subclasses and expose the netlist
in their `.netlist` attribute, so you can save or share the exact data that
caused a validation or routing error. `render()` attaches it when given a
netlist dictionary:

```python
import json
from circuitgen import NetlistRenderError, generate

try:
    generate("Create an Arduino sensor circuit")
except NetlistRenderError as error:
    print(json.dumps(error.netlist, indent=2))
```

In the CLI, a rendering failure opens the generated JSON in CircuitGen's netlist
viewer, where you can inspect or copy it without creating an extra file.

### 3. Validation

Check if a netlist is valid without rendering:

```python
from circuitgen import validate

check = validate(netlist)
if check.valid:
    print("Netlist is valid!")
else:
    print("Errors found:", check.errors)
```

### 4. Component Symbols

List built-in symbols:

```python
from circuitgen import list_symbols

print(list_symbols())
```

Built-in component types and standard pin names:

| Type | Description | Pin Names |
| --- | --- | --- |
| `resistor` | Two-terminal resistor | `a`, `b` |
| `capacitor` | Two-terminal capacitor | `a`, `b` |
| `inductor` | Two-terminal inductor | `a`, `b` |
| `diode` | Diode | `a` (anode), `b` (cathode) |
| `led` | LED | `a` (anode), `b` (cathode) |
| `switch` | SPST switch | `a`, `b` |
| `lamp` | Lamp | `a`, `b` |
| `fuse` | Fuse | `a`, `b` |
| `battery` | DC battery | `p` (positive), `n` (negative) |
| `dc_source` | DC power source | `p`, `n` |
| `ac_source` | AC power source | `p`, `n` |
| `current_source` | Current source | `p`, `n` |
| `npn` | NPN BJT | `B` (base), `C` (collector), `E` (emitter) |
| `pnp` | PNP BJT | `B` (base), `C` (collector), `E` (emitter) |
| `nmos` | N-channel MOSFET | `G` (gate), `D` (drain), `S` (source) |
| `pmos` | P-channel MOSFET | `G` (gate), `D` (drain), `S` (source) |
| `opamp` | Operational amplifier | `IN+`, `IN-`, `OUT`, `V+`, `V-` |
| `ne555` | 555 timer IC | `GND`, `TRIG`, `OUT`, `RESET`, `CTRL`, `THRES`, `DISCH`, `VCC` |
| `arduino_uno` | Arduino Uno board | `D0`–`D13`, `A0`–`A5`, `3V3`, `5V`, `VIN`, `GND`, `RESET` |
| `ground` | Explicit ground symbol | `gnd` |

#### Custom Components

You can define custom ICs or breakout boards by providing an explicit `pins` list:

```python
{
    "id": "U1",
    "type": "custom_ic",
    "value": "SensorModule",
    "pins": ["VCC", "GND", "SDA", "SCL"]
}
```

*Note: Custom pin lists define logical connection points for the schematic, not physical pin layouts of a specific chip package.*

## Interactive settings

To generate a schematic in the TUI, choose **Generate** from Home, enter a
circuit description, and choose the output directory and filename. Use
**Change provider / model** to choose a provider for this schematic. After
saving, **Open schematic** launches your viewer and **View netlist** opens a
copyable JSON view. Press Esc during generation to return to your draft.
Generate checks the model list with the active API key before sending the
description. Use **Browse models** if your configured model is missing from
that list. A listed model can still be unavailable for a particular request.
When essential wiring is unclear, Generate asks one question with **Continue**,
**Skip**, and **Edit description**. Skip proceeds only when the screen can state
an assumption; assumptions appear on the success screen. Unrelated or refused
requests stop before saving a netlist or schematic.

Right-click text to copy it. Right-click blank space to paste into the focused
editable field. API-key fields accept paste and keep their contents masked.

Open **Settings** from Home. Use the arrow keys to highlight a row and Enter
to toggle it, open its choices, or edit its value. Choose **Save changes**
to keep your edits. Esc returns to the previous screen. Ctrl+Q exits immediately.

| Category | Options |
| --- | --- |
| AI Providers | Choose a provider and enter an exact model ID or use Browse models. A blank model field uses the provider default. CircuitGen checks new manually entered IDs against the provider's model list when you save. Test the connection or manage stored keys here. |
| Generation | Control same-provider model fallback, one retry for temporary errors, essential clarification questions, and the request timeout. |
| Output | Choose the output directory and SVG, PNG, or PDF. Control overwrite prompts, opening after save, and saving a JSON copy from Render. |
| Schematic Preferences | Set the background, component, wire, and text colors. Use the color grid or paste a hex code. Choose whether to show component IDs and values. |
| Interface | Choose PCB Green, Midnight Blue, Light, Monochrome, Regular terminal, or No color. Reduce motion turns off interface animations. |
| Reset Settings | Restore defaults after confirmation while keeping stored API keys. |
| Run Setup Again | Reopen onboarding to revisit the AI provider, key, and model. |

Keys set through environment variables are managed outside CircuitGen. Stored
keys use the OS credential store. Connection testing checks credentials
without generating a schematic. It does not establish model access or pricing.

Render saves optional JSON next to the schematic. When that path is the source
netlist, Render uses `.netlist.json` to avoid replacing the source.

## Electrical Rule Checking (CLI)

Run conservative electrical checks (floating pins, polarity issues) on a netlist:

```bash
python -m circuitgen.erc path/to/netlist.json
```

Or output JSON:

```bash
python -m circuitgen.erc path/to/netlist.json --json
```

## Notes & Limitations

- CircuitGen is a schematic renderer, not a circuit simulator (like SPICE) or PCB layout tool (like KiCad).
- Wire routing is orthogonal (Manhattan) and deterministic.
- Multi-pin nets use continuous routed wires, including supply and return rails.
  Wire jumps mark crossings between separate nets, and dots mark junctions.
  Add a `ground` component and connect its `gnd` pin if you want a ground
  symbol. The symbol has no effect on connectivity beyond its assigned net.
- If no layout can be verified, rendering reports a routing error.
- Manual netlist workflows are 100% offline and do not require network access or API keys.

## License

MIT

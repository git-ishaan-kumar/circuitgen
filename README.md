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

`circuitgen` with no arguments opens the interactive terminal app. For netlists, drawings, and checks — from a shell, a script, or CI — use one of the commands:

| Command | What it does |
| --- | --- |
| `circuitgen render NETLIST` | Draw a netlist as an SVG schematic |
| `circuitgen validate NETLIST` | Check structure and connectivity without drawing |
| `circuitgen erc NETLIST` | Run electrical rule checks |
| `circuitgen symbols [KIND]` | List built-in symbols, or draw one as an SVG |

```bash
circuitgen render examples/wheatstone.json -o wheatstone.svg
circuitgen render - < netlist.json > schematic.svg
circuitgen render examples/wheatstone.json --color '#336699' --optimize
circuitgen validate examples/controller.json --json
circuitgen erc examples/erc_issues.json --fail-on-warning
circuitgen symbols ne555 --rotation 90 -o ne555.svg
```

`NETLIST` is a file path or `-` for standard input. Results go to stdout unless `-o` is given, and the summary goes to stderr, so redirection stays clean. Exit codes are `0` for success, `1` when the netlist was read but is not a usable circuit, and `2` for wrong arguments or an unreadable input:

```bash
circuitgen validate netlist.json && circuitgen render netlist.json -o out.svg
```

The app can also be launched through the universal cross-platform Python module entrypoint:

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

# Render directly or save to a file
result = from_netlist(netlist, output="circuit.svg")
print(f"Saved schematic to {result.output_path}")

# Or access the SVG string directly in memory
svg_markup = result.svg
```

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

## Electrical Rule Checking (CLI)

Run conservative electrical checks (floating pins, polarity issues) on a netlist:

```bash
circuitgen erc path/to/netlist.json
```

Or output JSON, and fail the shell command when anything is wrong:

```bash
circuitgen erc path/to/netlist.json --json
circuitgen erc path/to/netlist.json --fail-on-warning
```

The standalone module entrypoint works too:

```bash
python -m circuitgen.erc path/to/netlist.json --json
```

## Notes & Limitations

- CircuitGen is a schematic renderer, not a circuit simulator (like SPICE) or PCB layout tool (like KiCad).
- Wire routing is orthogonal (Manhattan) and deterministic.
- Manual netlist workflows are 100% offline and do not require network access or API keys.
- `circuitgen validate` checks structure and connectivity only; `circuitgen render` additionally proves that the drawing it emits is geometrically consistent.

## License

MIT

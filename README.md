<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/banner-dark.png">
    <source media="(prefers-color-scheme: light)" srcset="assets/banner-light.png">
    <img src="assets/banner-light.png" alt="CircuitGen" width="460">
  </picture>
  <br>
  Generate circuit schematics from text descriptions or netlists.
</p>

<p align="center">
  <a href="https://github.com/git-ishaan-kumar/circuitgen"><img alt="GitHub" src="https://img.shields.io/badge/GitHub-24292f?style=for-the-badge&logo=github&logoColor=white"></a>
  <a href="https://pypi.org/project/circuitgen/"><img alt="PyPI" src="https://img.shields.io/badge/PyPI-3775a9?style=for-the-badge&logo=pypi&logoColor=white"></a>
</p>

<p align="center">
  <a href="https://pypi.org/project/circuitgen/"><img alt="PyPI version" src="https://img.shields.io/pypi/v/circuitgen?label=PyPI"></a>
  <a href="https://pypi.org/project/circuitgen/"><img alt="Python 3.10 and newer" src="https://img.shields.io/badge/python-3.10%2B-blue"></a>
  <a href="LICENSE"><img alt="MIT License" src="https://img.shields.io/badge/license-MIT-green"></a>
</p>



## Overview

CircuitGen is a Python library and CLI for generating circuit schematics from text descriptions or netlists.

<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="assets/example-dark.svg">
    <source media="(prefers-color-scheme: light)" srcset="assets/example-light.svg">
    <img src="assets/example-light.svg" alt="Battery, resistor, and LED schematic generated with CircuitGen" width="440">
  </picture>
</p>



## Features

- **Natural Language Generation**
  > Generate schematics from written circuit descriptions using your preferred AI provider.
- **Automatic Layout and Routing**
  > Place components and route wires automatically from a netlist.
- **Interactive CLI**
  > Generate, render, and validate circuits directly from your terminal.
- **Offline Rendering**
  > Render existing netlists without an API key or internet connection.
- **Flexible Export**
  > Save schematics as SVG, PNG, or PDF with customizable appearance.



## Quickstart

### Python library

```sh
pip install circuitgen
```

### CLI

```sh
pip install circuitgen
circuit
```

<p><sub>If the CLI fails to start or behaves unexpectedly, run <code>python -m circuit doctor</code> to check your setup.</sub></p>



## Python example

```python
from circuitgen import generate

generate(
    "A 9 V battery connected in series with a 470 Ω resistor and a red LED.",
    provider="gemini",
    model="gemini-3.5-flash-lite",
    output="circuit.svg"
)
```

<p><sub>Requires a configured API key.</sub></p>
<p><sub>AI output can be wrong or invalid. Choose a model suited to your task and review generated circuits.</sub></p>



## Command-line interface

<p align="center">
  <img src="assets/cli-preview.png" alt="CircuitGen interactive command-line interface" width="680" style="border-radius:8px">
</p>



## License

Released under the [MIT License](LICENSE).

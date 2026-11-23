"""Tests for schematic ink colouring."""

import unittest

from circuitgen.colors import apply_ink_color, normalize_color
from circuitgen.engine import make_svg_from_netlist


def netlist(value: str) -> dict:
    return {
        "components": [
            {"id": "V1", "type": "battery", "value": "9V"},
            {"id": "D1", "type": "led", "value": value},
        ],
        "nets": [
            {"name": "A", "pins": ["V1.p", "D1.a"]},
            {"name": "B", "pins": ["D1.b", "V1.n"]},
        ],
    }


class TestInkColor(unittest.TestCase):
    def test_label_text_that_looks_like_a_colour_is_untouched(self):
        artwork = make_svg_from_netlist(netlist("#ff0000"), color="#336699")
        self.assertIn('#ff0000', artwork)
        self.assertIn('class="value"', artwork)

    def test_declared_ink_is_recoloured(self):
        artwork = make_svg_from_netlist(netlist("red"), color="#336699")
        self.assertIn("stroke:#336699", artwork)
        self.assertNotIn("stroke:#27354d", artwork)

    def test_default_and_custom_ink_differ_only_in_ink(self):
        default = make_svg_from_netlist(netlist("red"))
        custom = make_svg_from_netlist(netlist("red"), color="#336699")
        self.assertEqual(default, custom.replace("#336699", "#000000"))

    def test_white_fills_are_preserved(self):
        svg = '<svg><style>.x{fill:#ffffff;stroke:#123456}</style><rect fill="#ffffff"/></svg>'
        recoloured = apply_ink_color(svg, "#abcdef")
        self.assertEqual(recoloured.count("#ffffff"), 2)
        self.assertIn("stroke:#abcdef", recoloured)
        self.assertNotIn("#123456", recoloured)

    def test_eight_digit_hex_is_not_half_replaced(self):
        svg = '<svg><style>.x{fill:#ffffff00}</style></svg>'
        self.assertEqual(apply_ink_color(svg, "#abcdef"), svg)

    def test_invalid_colour_is_rejected(self):
        for bad in ("red", "#12345", "#1234567", "", None, 42):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                normalize_color(bad)

    def test_normalize_color_accepts_six_digits(self):
        self.assertEqual(normalize_color("#A1B2C3"), "#A1B2C3")


if __name__ == "__main__":
    unittest.main()

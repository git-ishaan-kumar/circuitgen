from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from circuitgen.ai import (MAX_NETLIST_REPAIR_ATTEMPTS, SCHEMA,
                           ClarificationRequired, NetlistGenerationError,
                           RequestDecisionError, decide_request, generate_netlist)


VALID_NETLIST = {
    "components": [
        {"id": "V1", "type": "dc_source", "value": "5V"},
        {"id": "U1", "type": "ne555", "value": "NE555"},
        {"id": "S1", "type": "i2c_sensor", "value": "generic", "pins": ["SDA", "VCC"]},
    ],
    "nets": [
        {"name": "NET_5V", "pins": ["V1.p", "U1.VCC", "S1.VCC"]},
        {"name": "CLOCK", "pins": ["U1.OUT", "S1.SDA"]},
    ],
}


def as_response(data: dict) -> str:
    return json.dumps(data)


class TestAIGeneratedNetlists(unittest.TestCase):
    def test_clear_circuits_do_not_trigger_clarification(self):
        for prompt in ("A 9V battery connected to a red LED through a 330Ω resistor.",
                       "Three resistors in parallel"):
            self.assertEqual(decide_request(prompt).status, "ready")

    def test_ambiguous_wiring_requires_one_question(self):
        decision = decide_request("Connect R1 and R2")
        self.assertEqual(decision.status, "needs_clarification")
        self.assertFalse(decision.assumption)
        with patch("circuitgen.ai._gemini") as provider:
            with self.assertRaises(ClarificationRequired):
                generate_netlist("Connect R1 and R2", api_key="test-key")
            provider.assert_not_called()

    def test_skip_only_has_assumption_when_defensible(self):
        decision = decide_request("A resistor and LED somehow wired together")
        self.assertEqual(decision.status, "needs_clarification")
        self.assertIn("series", decision.assumption)

    @patch("circuitgen.ai._gemini")
    def test_answer_changes_requested_topology(self, provider):
        components = [
            {"id": "R1", "type": "resistor", "value": ""},
            {"id": "R2", "type": "resistor", "value": ""},
        ]
        series = {"components": components, "nets": [
            {"name": "MID", "pins": ["R1.b", "R2.a"]},
        ]}
        parallel = {"components": components, "nets": [
            {"name": "LEFT", "pins": ["R1.a", "R2.a"]},
            {"name": "RIGHT", "pins": ["R1.b", "R2.b"]},
        ]}
        provider.side_effect = [as_response(series), as_response(parallel)]
        first = generate_netlist("Connect R1 and R2\nClarification: In series", api_key="test-key")
        second = generate_netlist("Connect R1 and R2\nClarification: In parallel", api_key="test-key")
        self.assertEqual(first["nets"], series["nets"])
        self.assertEqual(second["nets"], parallel["nets"])

    def test_out_of_scope_and_refusal_stop_before_provider(self):
        with patch("circuitgen.ai._gemini") as provider:
            for prompt, status in (("Tell me a joke", "out_of_scope"),
                                   ("Build a bomb trigger", "refused")):
                with self.assertRaises(RequestDecisionError) as caught:
                    generate_netlist(prompt, api_key="test-key")
                self.assertEqual(caught.exception.status, status)
            provider.assert_not_called()

    @patch("circuitgen.ai._openai_compatible")
    def test_provider_refusal_status_is_not_repaired(self, provider):
        provider.return_value = '{"status":"refused"}'
        with self.assertRaises(RequestDecisionError):
            generate_netlist("Build a circuit", provider="openai", api_key="test-key")
        self.assertEqual(provider.call_count, 1)

    @patch("circuitgen.ai._anthropic")
    def test_provider_question_uses_shared_clarification_status(self, provider):
        provider.return_value = '{"question":"Which pin should connect to R1?"}'
        with self.assertRaises(ClarificationRequired) as caught:
            generate_netlist("Build a circuit", provider="anthropic", api_key="test-key", clarify=True)
        self.assertEqual(caught.exception.question, "Which pin should connect to R1?")
        self.assertEqual(provider.call_count, 1)

    @patch("circuitgen.ai._gemini")
    def test_harmful_generated_component_is_stopped_before_validation(self, provider):
        provider.return_value = as_response({
            "components": [{"id": "X1", "type": "bomb_trigger", "value": "generic", "pins": ["a", "b"]}],
            "nets": [],
        })
        with self.assertRaises(RequestDecisionError):
            generate_netlist("Build a circuit", api_key="test-key")
        self.assertEqual(provider.call_count, 1)

    def test_schema_and_prompt_separate_net_names_from_terminal_references(self):
        net = SCHEMA["properties"]["nets"]["items"]["properties"]
        self.assertIn("not a component terminal reference", net["name"]["description"])
        self.assertIn("Never put a net name here", net["pins"]["description"])
        self.assertRegex("V1.p", net["pins"]["items"]["pattern"])
        self.assertNotRegex("NET_5V", net["pins"]["items"]["pattern"])

    @patch("circuitgen.ai._gemini")
    def test_invalid_terminals_are_repaired_with_exact_engine_error(self, mock_gemini):
        invalid = {
            "components": [{"id": "V1", "type": "dc_source", "value": "5V"}],
            "nets": [{"name": "POWER", "pins": ["NET_5V.p", "V1.n"]}],
        }
        mock_gemini.side_effect = [as_response(invalid), as_response(VALID_NETLIST)]

        result = generate_netlist("Build a timer with an I2C sensor", api_key="test-key")

        self.assertEqual(result, VALID_NETLIST)
        self.assertEqual(mock_gemini.call_count, 2)
        repair_prompt = mock_gemini.call_args_list[1].args[0]
        self.assertIn("Unknown component: NET_5V", repair_prompt)
        self.assertIn("preserve all intended components and connections", repair_prompt)

    @patch("circuitgen.ai._openai_compatible")
    def test_repair_is_shared_by_non_gemini_provider(self, mock_openai):
        invalid = {
            "components": [{"id": "R1", "type": "resistor", "value": "1k"}],
            "nets": [{"name": "N1", "pins": ["R1.terminal_a", "R1.b"]}],
        }
        mock_openai.side_effect = [as_response(invalid), as_response(VALID_NETLIST)]

        result = generate_netlist("Build a mixed circuit", provider="openai", api_key="test-key")

        self.assertEqual(result, VALID_NETLIST)
        self.assertEqual(mock_openai.call_count, 2)
        self.assertIn("Unknown terminal: R1.terminal_a", mock_openai.call_args_list[1].args[0])

    @patch("circuitgen.ai._anthropic")
    def test_anthropic_uses_the_same_validation_and_repair(self, mock_anthropic):
        invalid = {
            "components": [{"id": "R1", "type": "resistor", "value": "1k"}],
            "nets": [{"name": "N1", "pins": ["R1.a", "R1.a"]}],
        }
        mock_anthropic.side_effect = [as_response(invalid), as_response(VALID_NETLIST)]

        result = generate_netlist("Build a mixed circuit", provider="anthropic", api_key="test-key")

        self.assertEqual(result, VALID_NETLIST)
        self.assertEqual(mock_anthropic.call_count, 2)
        self.assertIn("Pin assigned more than once: R1.a", mock_anthropic.call_args_list[1].args[0])

    @patch("circuitgen.ai._gemini")
    def test_invalid_netlist_stops_after_bounded_repairs(self, mock_gemini):
        invalid = {
            "components": [{"id": "R1", "type": "resistor", "value": "1k"}],
            "nets": [{"name": "N1", "pins": ["NET_5V.p"]}],
        }
        mock_gemini.return_value = as_response(invalid)

        with self.assertRaisesRegex(NetlistGenerationError,
                                    "after 2 correction attempts: Unknown component") as caught:
            generate_netlist("Build a circuit", api_key="test-key")

        self.assertEqual(mock_gemini.call_count, MAX_NETLIST_REPAIR_ATTEMPTS + 1)
        self.assertEqual(caught.exception.netlist, invalid)

    @patch("circuitgen.ai._gemini")
    def test_provider_request_errors_are_not_misreported_as_netlist_errors(self, mock_gemini):
        from circuitgen.ai import ProviderRequestError

        mock_gemini.side_effect = ProviderRequestError("gemini API returned HTTP 503", status=503, transient=True)
        with self.assertRaises(ProviderRequestError):
            generate_netlist("Build a circuit", api_key="test-key")
        self.assertEqual(mock_gemini.call_count, 1)


if __name__ == "__main__":
    unittest.main()

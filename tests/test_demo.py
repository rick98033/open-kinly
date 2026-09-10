from __future__ import annotations

from importlib.resources import as_file, files
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator

from open_kinly.catalog import load_catalog
from open_kinly.compiler import CompileError, compile_program
from open_kinly.language import build_schema, build_system_prompt
from open_kinly.runtime import ToyPhone, allow_toy_capabilities, execute


ROOT = Path(__file__).resolve().parents[1]


class DemoTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        resource = files("open_kinly").joinpath("toy_catalog.yaml")
        with as_file(resource) as path:
            cls.catalog = load_catalog(path)
        cls.program = json.loads(
            (ROOT / "examples" / "l5_program.json").read_text(encoding="utf-8")
        )

    def test_golden_program_is_schema_valid_and_lowers_to_expected_graph(self) -> None:
        Draft202012Validator(build_schema(self.catalog)).validate(self.program)
        plan = compile_program(self.program, self.catalog)
        self.assertEqual(
            [node["depends_on"] for node in plan["nodes"]],
            [[], ["c1"], ["c1"], [], ["c1"]],
        )
        self.assertEqual(plan["nodes"][1]["arguments"]["level"]["kind"], "result")
        self.assertEqual(plan["nodes"][4]["arguments"]["amount"]["value"], 25)

    def test_sufficient_battery_materializes_fanout_and_skips_guard(self) -> None:
        plan = compile_program(self.program, self.catalog)
        phone = ToyPhone(battery_percent=80)
        outcome = execute(
            plan, dispatch=phone.dispatch, authorize=allow_toy_capabilities
        )
        self.assertEqual(outcome["status"], "completed")
        self.assertEqual(
            [node["state"] for node in outcome["nodes"]],
            ["completed", "completed", "completed", "completed", "skipped"],
        )
        self.assertEqual(outcome["nodes"][1]["arguments"], {"level": 80})
        self.assertEqual(outcome["nodes"][2]["arguments"], {"level": 80})

    def test_low_battery_runs_guarded_action(self) -> None:
        plan = compile_program(self.program, self.catalog)
        phone = ToyPhone(battery_percent=3)
        outcome = execute(
            plan, dispatch=phone.dispatch, authorize=allow_toy_capabilities
        )
        self.assertEqual([node["state"] for node in outcome["nodes"]], ["completed"] * 5)
        self.assertEqual(outcome["nodes"][4]["arguments"], {"amount": 25})

    def test_producer_failure_does_not_block_independent_action(self) -> None:
        plan = compile_program(self.program, self.catalog)
        phone = ToyPhone()

        def dispatch(capability: str, arguments: dict) -> dict:
            if capability == "device_battery.get_status":
                return {"ok": False, "error_code": "HARDWARE_UNAVAILABLE"}
            return phone.dispatch(capability, arguments)

        outcome = execute(plan, dispatch=dispatch, authorize=allow_toy_capabilities)
        self.assertEqual(outcome["status"], "partial")
        self.assertEqual(
            [node["state"] for node in outcome["nodes"]],
            ["failed", "dependency_failed", "dependency_failed", "completed", "dependency_failed"],
        )

    def test_forward_reference_is_rejected_by_semantic_compiler(self) -> None:
        invalid = json.loads(json.dumps(self.program))
        invalid["calls"][1]["arguments"]["level"]["ref"]["call"] = 2
        with self.assertRaisesRegex(CompileError, "earlier call"):
            compile_program(invalid, self.catalog)

    def test_prompt_contains_approved_direct_reference_rule(self) -> None:
        prompt = build_system_prompt(self.catalog)
        self.assertIn(
            "Use an argument's ref form when the user asks to pass an earlier "
            "call's result to that argument; never replace the result with a literal.",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from syntec_lad.compiler import compile_plan
from syntec_lad.edition import AXIS_GENERATION
from syntec_lad.errors import LadValidationError
from syntec_lad.plan_lint import lint_plan


def axis_plan() -> dict:
    return {
        "schema": "syntec-lad-plan/v1",
        "programs": [
            {
                "name": "MAIN",
                "networks": [
                    {
                        "condition": {"always": True},
                        "actions": [
                            {"op": "AXMOVE", "axis": "AX1", "data": "R0100"}
                        ],
                    }
                ],
            }
        ],
    }


class EditionGateTests(unittest.TestCase):
    def test_public_edition_rejects_axis_generation(self) -> None:
        if AXIS_GENERATION:
            self.skipTest("Alpha edition enables PLC-axis generation")
        with self.assertRaises(LadValidationError) as raised:
            compile_plan(axis_plan())
        self.assertIn("HARD-DISABLED", str(raised.exception))
        self.assertIn("collision", str(raised.exception))
        result = lint_plan(axis_plan())
        self.assertFalse(result["ok"])
        self.assertIn(
            "axis_not_supported",
            {item["rule"] for item in result["issues"]},
        )
        message = " ".join(
            item["detail"] for item in result["issues"]
        )
        self.assertIn("硬性禁止", message)
        self.assertIn("人身伤害", message)


if __name__ == "__main__":
    unittest.main()

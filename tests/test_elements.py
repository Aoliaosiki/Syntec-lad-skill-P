"""Smoke coverage for the eight element families plus optional PLC-axis records.

This verifies that the compiler can emit a file containing I/O, A, C, S, R,
TM and CT records, that Python readback sees every family, and that the native
LadDLL accepts the result when it is installed.  The Alpha edition adds three
AX records to the same plan.
"""

from __future__ import annotations

import unittest

from syntec_lad.compiler import compile_plan
from syntec_lad.edition import AXIS_GENERATION
from syntec_lad.inspection import inspect_document
from syntec_lad.native import find_lad_dll, validate_document
from syntec_lad.resources import resource_report


def element_plan() -> dict:
    networks = [
        {
            "comment": "I -> O",
            "condition": {"contact": "I000"},
            "actions": [{"op": "OUT", "operand": "O000"}],
        },
        {
            "comment": "A -> A",
            "condition": {"contact": "A000"},
            "actions": [{"op": "OUT", "operand": "A001"}],
        },
        {
            "comment": "S -> A (S is read-only)",
            "condition": {"contact": "S000"},
            "actions": [{"op": "OUT", "operand": "A002"}],
        },
        {
            "comment": "C command bit",
            "condition": {"always": True},
            "actions": [{"op": "OUT", "operand": "C000"}],
        },
        {
            "comment": "R data register",
            "condition": {"always": True},
            "actions": [{"op": "MOV", "src": "#00001", "dst": "R0050"}],
        },
        {
            "comment": "Timer",
            "condition": {"contact": "I001"},
            "actions": [
                {"op": "TIM", "timer": "TM000", "unit": "100ms", "preset": "#00010"}
            ],
        },
        {
            "comment": "Counter",
            "condition": {"contact": "I002"},
            "actions": [{"op": "CNTUP", "counter": "CT000", "preset": "#00005"}],
        },
    ]
    if AXIS_GENERATION:
        networks.extend(
            [
                {
                    "comment": "PLC axis move",
                    "condition": {"always": True},
                    "actions": [{"op": "AXMOVE", "axis": "AX1", "data": "R0100"}],
                },
                {
                    "comment": "PLC axis run",
                    "condition": {"always": True},
                    "actions": [{"op": "AXRUN", "axis": "AX2", "program": "#0001"}],
                },
                {
                    "comment": "PLC axis stop",
                    "condition": {"always": True},
                    "actions": [{"op": "AXSTOP", "axis": "AX3"}],
                },
            ]
        )
    return {
        "schema": "syntec-lad-plan/v1",
        "programs": [{"name": "MAIN", "networks": networks}],
    }


class ElementSmokeTests(unittest.TestCase):
    def test_all_element_families_round_trip(self) -> None:
        document = compile_plan(element_plan())
        report = resource_report(document, path="<mem>")
        families = report["families"]
        for family in ("I", "O", "A", "C", "S", "R", "TM", "CT"):
            self.assertGreater(
                families[family]["count"],
                0,
                f"{family} family was not emitted",
            )
        r_addresses = {entry["addr"] for entry in families["R"]["used"]}
        self.assertIn("R50", r_addresses)
        if AXIS_GENERATION:
            self.assertTrue({"R100", "R101", "R102", "R103"} <= r_addresses)
        else:
            self.assertFalse({"R100", "R101", "R102", "R103"} & r_addresses)
        self.assertEqual(inspect_document(document)["integrity"]["issues"], [])

    def test_native_accepts_all_element_families(self) -> None:
        document = compile_plan(element_plan())
        try:
            find_lad_dll()
        except Exception as exc:  # pragma: no cover - depends on host install
            self.skipTest(f"native LadDLL unavailable: {exc}")
        validate_document(document)


if __name__ == "__main__":
    unittest.main()

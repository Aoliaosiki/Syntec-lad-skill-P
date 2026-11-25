from __future__ import annotations

import unittest

from syntec_lad.comments import comment_coverage, render_comments
from syntec_lad.compiler import compile_plan


def _plan(
    networks: list[dict],
    *,
    variables: list[dict] | None = None,
    comment: str | None = None,
) -> dict:
    program = {"name": "MAIN", "networks": networks}
    if comment:
        program["comment"] = comment
    plan = {
        "schema": "syntec-lad-plan/v1",
        "programs": [program],
    }
    if variables is not None:
        plan["variables"] = variables
    return plan


def _networks() -> list[dict]:
    return [
        {
            "condition": {"contact": "I000"},
            "actions": [{"op": "OUT", "operand": "O001"}],
        }
    ]


class CommentCoverageTests(unittest.TestCase):
    def test_uncommented_interface_points_are_l1_missing(self) -> None:
        result = comment_coverage(compile_plan(_plan(_networks())))
        missing = {item["addr"] for item in result["missing"] if item["level"] == "L1"}
        self.assertEqual({"I0", "O1"}, missing)
        self.assertEqual(result["summary"]["l1_total"], 2)
        self.assertEqual(result["summary"]["l1_commented"], 0)
        self.assertFalse(result["ok"])

    def test_variable_comments_raise_l1_coverage(self) -> None:
        document = compile_plan(
            _plan(
                _networks(),
                variables=[
                    {"name": "I000", "short": "启动"},
                    {"name": "O001", "short": "油压"},
                ],
            )
        )
        result = comment_coverage(document)
        self.assertEqual(result["summary"]["l1_commented"], 2)
        self.assertEqual(result["summary"]["l1_coverage"], 1.0)
        self.assertFalse(
            [item for item in result["missing"] if item["level"] == "L1"]
        )

    def test_program_header_is_tracked_as_l2(self) -> None:
        without_header = comment_coverage(compile_plan(_plan(_networks())))
        self.assertEqual(without_header["summary"]["l2_programs_with_header"], 0)
        with_header = comment_coverage(
            compile_plan(_plan(_networks(), comment="润滑控制"))
        )
        self.assertEqual(with_header["summary"]["l2_programs_with_header"], 1)

    def test_subprogram_uses_ct3_header(self) -> None:
        document = compile_plan(
            {
                "schema": "syntec-lad-plan/v1",
                "programs": [
                    {
                        "name": "MAIN",
                        "comment": "主程序",
                        "networks": _networks(),
                    },
                    {
                        "name": "SUB1",
                        "comment": "子程序",
                        "networks": [
                            {
                                "condition": {"contact": "I010"},
                                "actions": [{"op": "OUT", "operand": "O010"}],
                            }
                        ],
                    },
                ],
            }
        )
        result = comment_coverage(document)
        self.assertEqual(result["summary"]["l2_programs"], 2)
        self.assertEqual(result["summary"]["l2_programs_with_header"], 2)

    def test_r_interface_and_hold_zones_are_l1(self) -> None:
        document = compile_plan(
            _plan(
                [
                    {
                        "condition": {"always": True},
                        "actions": [{"op": "MOV", "src": "#1", "dst": "R0200"}],
                    }
                ]
            )
        )
        result = comment_coverage(document)
        addresses = {item["addr"] for item in result["missing"] if item["level"] == "L1"}
        self.assertIn("R200", addresses)

    def test_internal_a_bits_are_not_required(self) -> None:
        document = compile_plan(
            _plan(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [{"op": "SET", "operand": "A050"}],
                    }
                ]
            )
        )
        result = comment_coverage(document)
        addresses = {item["addr"] for item in result["missing"] if item["level"] == "L1"}
        self.assertNotIn("A50", addresses)

    def test_render_reports_levels(self) -> None:
        text = render_comments(comment_coverage(compile_plan(_plan(_networks()))))
        self.assertIn("L1", text)
        self.assertIn("L2", text)


if __name__ == "__main__":
    unittest.main()



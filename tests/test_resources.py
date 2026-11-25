from __future__ import annotations

import unittest
from pathlib import Path

from syntec_lad.compiler import compile_plan
from syntec_lad.resources import (
    free_ranges,
    render_resources,
    resource_report,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _plan(networks: list[dict], *, resources: list[dict] | None = None) -> dict:
    plan = {
        "schema": "syntec-lad-plan/v1",
        "programs": [{"name": "MAIN", "networks": networks}],
    }
    if resources is not None:
        plan["resources"] = resources
    return plan


class ResourceReportTests(unittest.TestCase):
    def test_lists_used_io_and_read_write_roles(self) -> None:
        document = compile_plan(
            _plan(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [{"op": "OUT", "operand": "O001"}],
                    }
                ]
            )
        )
        result = resource_report(document, path="<mem>")
        used = {entry["addr"]: entry for entry in result["families"]["I"]["used"]}
        self.assertIn("I0", used)
        self.assertEqual(used["I0"]["reads"], 1)
        self.assertEqual(used["I0"]["writes"], 0)
        outputs = {entry["addr"]: entry for entry in result["families"]["O"]["used"]}
        self.assertEqual(outputs["O1"]["writes"], 1)

    def test_comment_is_attached_from_type4_block(self) -> None:
        document = compile_plan(
            {
                "schema": "syntec-lad-plan/v1",
                "variables": [{"name": "I000", "short": "启动", "long": "操作面板启动按钮"}],
                "programs": [
                    {
                        "name": "MAIN",
                        "networks": [
                            {
                                "condition": {"contact": "I000"},
                                "actions": [{"op": "OUT", "operand": "O001"}],
                            }
                        ],
                    }
                ],
            }
        )
        result = resource_report(document, path="<mem>")
        entry = result["families"]["I"]["used"][0]
        self.assertEqual(entry["addr"], "I0")
        self.assertIn("启动", entry["comment"])

    def test_writes_to_s_are_flagged(self) -> None:
        document = compile_plan(
            _plan(
                [
                    {
                        "condition": {"always": True},
                        "actions": [{"op": "OUT", "operand": "S001"}],
                    }
                ]
            )
        )
        result = resource_report(document, path="<mem>")
        checks = {item["check"] for item in result["warnings"]}
        self.assertIn("read_only_write", checks)
        self.assertFalse(result["ok"])

    def test_free_ranges_merge_contiguous_gaps(self) -> None:
        block = free_ranges([0, 1, 4], upper=7)
        self.assertEqual(block["ranges"], [[2, 3], [5, 7]])
        self.assertEqual(block["count"], 2)

    def test_io_table_comparison_reports_both_directions(self) -> None:
        document = compile_plan(
            _plan(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [{"op": "OUT", "operand": "O001"}],
                    }
                ]
            )
        )
        result = resource_report(
            document,
            io_points={"I0": "I0\t启动", "I5": "I5\t未接"},
            io_path="points.csv",
            path="<mem>",
        )
        self.assertEqual(result["io_table"]["missing_from_table"], ["O1"])
        self.assertEqual(result["io_table"]["unused_in_ladder"], ["I5"])

    def test_padded_io_table_matches_short_ladder_address(self) -> None:
        document = compile_plan(
            _plan(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [{"op": "OUT", "operand": "O001"}],
                    }
                ]
            )
        )
        result = resource_report(
            document,
            io_points={"I000": "I000\t启动", "O001": "O001\t油泵"},
            io_path="points.csv",
            path="<mem>",
        )
        self.assertEqual(result["io_table"]["missing_from_table"], [])
        self.assertEqual(result["io_table"]["unused_in_ladder"], [])

    def test_render_markdown_lists_free_candidates(self) -> None:
        document = compile_plan(
            _plan(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [{"op": "OUT", "operand": "O001"}],
                    }
                ]
            )
        )
        text = render_resources(resource_report(document, path="<mem>"))
        self.assertIn("空闲候选", text)
        self.assertIn("未分配的地址只是候选", text)

    def test_demo_example_scans(self) -> None:
        from syntec_lad.model import LadDocument

        document = LadDocument.load(EXAMPLES / "demo.lad")
        result = resource_report(document, path=str(EXAMPLES / "demo.lad"))
        self.assertGreater(result["summary"]["addresses_used"], 0)

    def test_r_entries_carry_zone_and_summary(self) -> None:
        document = compile_plan(
            _plan(
                [
                    {
                        "condition": {"always": True},
                        "actions": [{"op": "MOV", "src": "#1", "dst": "R2100"}],
                    }
                ]
            )
        )
        result = resource_report(document, path="<mem>")
        entry = result["families"]["R"]["used"][0]
        self.assertEqual(entry["addr"], "R2100")
        self.assertEqual(entry["zone_id"], "R2100-R3100")
        self.assertEqual(entry["owner"], "user_conditional")
        self.assertFalse(entry["bit_access"])
        zones = result["summary"]["register_zones"]
        self.assertEqual(zones[0]["zone_id"], "R2100-R3100")
        self.assertEqual(zones[0]["writes"], 1)
        text = render_resources(result)
        self.assertIn("R 分区占用", text)


if __name__ == "__main__":
    unittest.main()



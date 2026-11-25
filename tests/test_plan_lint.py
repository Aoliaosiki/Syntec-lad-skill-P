from __future__ import annotations

import unittest

from syntec_lad.plan_lint import lint_change, lint_plan, render_plan_lint


def _plan(networks: list[dict]) -> dict:
    return {
        "schema": "syntec-lad-plan/v1",
        "programs": [{"name": "MAIN", "networks": networks}],
    }


def _out(operand: str) -> dict:
    return {"op": "OUT", "operand": operand}


def _rules(result: dict) -> list[str]:
    return [item["rule"] for item in result["issues"]]


class PlanLintTests(unittest.TestCase):
    def test_different_conditions_pass(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [_out("O001")],
                    },
                    {
                        "condition": {"contact": "I001"},
                        "actions": [_out("O002")],
                    },
                ]
            )
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["issues"], [])

    def test_reordered_condition_is_mergeable(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {
                            "all": [
                                {"contact": "I000"},
                                {
                                    "any": [
                                        {"contact": "I001"},
                                        {"contact": "I002"},
                                    ]
                                },
                            ]
                        },
                        "actions": [_out("O001")],
                    },
                    {
                        "condition": {
                            "all": [
                                {
                                    "any": [
                                        {"contact": "I002"},
                                        {"contact": "I001"},
                                    ]
                                },
                                {"contact": "I000"},
                            ]
                        },
                        "actions": [_out("O002")],
                    },
                ]
            )
        )
        self.assertIn("mergeable_condition", _rules(result))

    def test_distributed_condition_is_mergeable(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {
                            "all": [
                                {"contact": "I000"},
                                {
                                    "any": [
                                        {"contact": "I001"},
                                        {"contact": "I002"},
                                    ]
                                },
                            ]
                        },
                        "actions": [_out("O001")],
                    },
                    {
                        "condition": {
                            "any": [
                                {
                                    "all": [
                                        {"contact": "I002"},
                                        {"contact": "I000"},
                                    ]
                                },
                                {
                                    "all": [
                                        {"contact": "I000"},
                                        {"contact": "I001"},
                                    ]
                                },
                            ]
                        },
                        "actions": [_out("O002")],
                    },
                ]
            )
        )
        self.assertIn("mergeable_condition", _rules(result))

    def test_unconditional_networks_are_mergeable(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {"always": True},
                        "actions": [_out("O001")],
                    },
                    {
                        "condition": {"always": True},
                        "actions": [_out("O002")],
                    },
                ]
            )
        )
        self.assertIn("mergeable_condition", _rules(result))
        self.assertIn("无条件", result["issues"][0]["detail"])

    def test_mixed_action_width_is_mergeable_when_condition_fits(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [_out("O001")],
                    },
                    {
                        "condition": {"contact": "I000"},
                        "actions": [
                            {
                                "op": "TIM",
                                "timer": "TM000",
                                "preset": "#10",
                            }
                        ],
                    },
                ]
            )
        )
        self.assertIn("mergeable_condition", _rules(result))
        self.assertNotIn("mergeable_condition_too_wide", _rules(result))

    def test_mixed_widths_inside_one_network_are_clean_when_condition_fits(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [
                            _out("O001"),
                            {
                                "op": "TIM",
                                "timer": "TM000",
                                "preset": "#10",
                            },
                        ],
                    }
                ]
            )
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["issues"], [])

    def test_wide_condition_cannot_share_a_mixed_action_bus(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {
                            "all": [
                                {"contact": f"I{index:03d}"}
                                for index in range(1, 10)
                            ]
                        },
                        "actions": [
                            _out("O001"),
                            {
                                "op": "TIM",
                                "timer": "TM000",
                                "preset": "#10",
                            },
                        ],
                    }
                ]
            )
        )
        self.assertIn("mixed_action_too_wide", _rules(result))

    def test_flow_action_is_not_reported_as_mergeable(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [{"op": "MSG", "target": "HELLO"}],
                    },
                    {
                        "condition": {"contact": "I000"},
                        "actions": [_out("O001")],
                    },
                ]
            )
        )
        self.assertNotIn("mergeable_condition", _rules(result))
        self.assertIn("flow_action_not_mergeable", _rules(result))

    def test_render_mentions_rule_names(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [_out("O001")],
                    },
                    {
                        "condition": {"contact": "I000"},
                        "actions": [_out("O002")],
                    },
                ]
            )
        )
        text = render_plan_lint(result)
        self.assertIn("mergeable_condition", text)
        self.assertIn("N0001/N0002", text)


class ResourcePlanTests(unittest.TestCase):
    def test_plan_without_resources_keeps_legacy_behaviour(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [_out("O001")],
                    }
                ]
            )
        )
        self.assertTrue(result["ok"])
        self.assertNotIn("resource_missing", _rules(result))

    def test_suggested_source_blocks_build(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"contact": "I000"},
                    "actions": [_out("O001")],
                }
            ]
        )
        plan["resources"] = [
            {"addr": "I0", "source": "suggested"},
            {"addr": "O1", "source": "user"},
        ]
        result = lint_plan(plan)
        self.assertFalse(result["ok"])
        self.assertIn("resource_unverified", _rules(result))

    def test_confirmed_sources_pass(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"contact": "I000"},
                    "actions": [_out("O001")],
                }
            ]
        )
        plan["resources"] = [
            {"addr": "I0", "source": "io-table", "symbol": "啟動"},
            {"addr": "O1", "source": "user", "symbol": "油泵"},
        ]
        result = lint_plan(plan)
        self.assertTrue(result["ok"])
        self.assertEqual(result["issues"], [])

    def test_missing_interface_point_warns(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"contact": "I000"},
                    "actions": [_out("O001")],
                }
            ]
        )
        plan["resources"] = [{"addr": "I0", "source": "user"}]
        result = lint_plan(plan)
        self.assertIn("resource_missing", _rules(result))

    def test_read_only_write_is_an_error(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"always": True},
                    "actions": [{"op": "MOV", "src": "#1", "dst": "R0081"}],
                }
            ]
        )
        plan["resources"] = [{"addr": "R81", "source": "user"}]
        result = lint_plan(plan)
        self.assertFalse(result["ok"])
        self.assertIn("resource_readonly_write", _rules(result))

    def test_duplicate_and_invalid_source_are_errors(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"contact": "I000"},
                    "actions": [_out("O001")],
                }
            ]
        )
        plan["resources"] = [
            {"addr": "I0", "source": "user"},
            {"addr": "I000", "source": "made-up"},
            {"addr": "O1", "source": "user"},
        ]
        result = lint_plan(plan)
        rules = _rules(result)
        self.assertIn("resource_duplicate", rules)
        self.assertIn("resource_source_invalid", rules)


class ResourceChangeTests(unittest.TestCase):
    def _change(self, networks: list[dict], *, resources: list[dict] | None = None) -> dict:
        change = {
            "schema": "syntec-lad-change/v1",
            "base_sha256": "0" * 64,
            "operations": [
                {
                    "op": "insert",
                    "at_record": 0,
                    "expected_sha256": "0" * 64,
                    "networks": networks,
                }
            ],
        }
        if resources is not None:
            change["resources"] = resources
        return change

    def test_change_with_confirmed_resources_passes(self) -> None:
        result = lint_change(
            self._change(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [{"op": "OUT", "operand": "O001"}],
                    }
                ],
                resources=[
                    {"addr": "I0", "source": "io-table"},
                    {"addr": "O1", "source": "user"},
                ],
            )
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"]["kind"], "change")
        self.assertEqual(result["source"]["operations"], 1)

    def test_change_with_suggested_blocks(self) -> None:
        result = lint_change(
            self._change(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [{"op": "OUT", "operand": "O001"}],
                    }
                ],
                resources=[{"addr": "I0", "source": "suggested"}],
            )
        )
        self.assertFalse(result["ok"])
        self.assertIn("resource_unverified", _rules(result))

    def test_change_without_resources_keeps_legacy_behaviour(self) -> None:
        result = lint_change(
            self._change(
                [
                    {
                        "condition": {"contact": "I000"},
                        "actions": [{"op": "OUT", "operand": "O001"}],
                    }
                ]
            )
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["issues"], [])

    def test_render_handles_change_document(self) -> None:
        text = render_plan_lint(lint_change(self._change([])))
        self.assertIn("Change", text)


if __name__ == "__main__":
    unittest.main()

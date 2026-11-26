from __future__ import annotations

import unittest

from syntec_lad.edition import AXIS_GENERATION
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


class ProgramTitleTests(unittest.TestCase):
    def _sub_plan(self, name: str, comment: str | None) -> dict:
        program = {
            "name": name,
            "networks": [
                {
                    "condition": {"contact": "I000"},
                    "actions": [_out("O001")],
                }
            ],
        }
        if comment is not None:
            program["comment"] = comment
        return {
            "schema": "syntec-lad-plan/v1",
            "programs": [
                {"name": "MAIN", "networks": []},
                program,
            ],
        }

    def test_short_categorical_title_passes(self) -> None:
        result = lint_plan(self._sub_plan("9", "【刀库】-伺服刀库"))
        self.assertEqual(result["issues"], [])

    def test_long_note_after_first_line_is_allowed(self) -> None:
        result = lint_plan(
            self._sub_plan(
                "9",
                "【刀库】-伺服刀库\n职责：刀盘旋转与刀套翻转\n"
                "互锁：主轴停止、刀库门关闭后才允许转动",
            )
        )
        self.assertEqual(result["issues"], [])

    def test_missing_title_warns(self) -> None:
        result = lint_plan(self._sub_plan("9", None))
        self.assertIn("program_title_missing", _rules(result))

    def test_long_sentence_title_warns(self) -> None:
        result = lint_plan(
            self._sub_plan("9", "当刀库计数到达设定值后自动切换到下一刀位并输出提示")
        )
        rules = _rules(result)
        self.assertIn("program_title_too_long", rules)
        self.assertIn("program_title_without_category", rules)

    def test_sentence_punctuation_warns(self) -> None:
        result = lint_plan(
            self._sub_plan("9", "【刀库】-伺服刀库，负责换刀")
        )
        self.assertIn("program_title_sentence", _rules(result))

    def test_editor_number_in_title_warns(self) -> None:
        result = lint_plan(self._sub_plan("9", "(9)【刀库】-伺服刀库"))
        self.assertIn("program_title_numbered", _rules(result))

    def test_trailing_editor_number_in_title_warns(self) -> None:
        result = lint_plan(self._sub_plan("9", "【刀库】-伺服刀库 (9)"))
        self.assertIn("program_title_numbered", _rules(result))

    def test_non_ascii_label_is_an_error(self) -> None:
        result = lint_plan(self._sub_plan("刀库", "【刀库】-伺服刀库"))
        self.assertFalse(result["ok"])
        self.assertIn("program_name_invalid", _rules(result))


class MCodeAndAxisScaffoldingTests(unittest.TestCase):
    def test_wait_mcode_without_c38_warns(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {
                            "all": [
                                {"contact": "S029"},
                                {
                                    "compare": {
                                        "relation": "=",
                                        "value": "R0001",
                                        "other": "#00050",
                                    }
                                },
                            ]
                        },
                        "actions": [_out("A150")],
                    }
                ]
            )
        )
        self.assertIn("mcode_wait_without_c38", _rules(result))

    def test_wait_mcode_with_c38_passes(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {
                            "all": [
                                {"contact": "S029"},
                                {
                                    "compare": {
                                        "relation": "=",
                                        "value": "R0001",
                                        "other": "#00050",
                                    }
                                },
                            ]
                        },
                        "actions": [_out("A150")],
                    },
                    {
                        "condition": {"contact": "A150"},
                        "actions": [_out("C038")],
                    },
                ]
            )
        )
        self.assertNotIn("mcode_wait_without_c38", _rules(result))

    def test_non_wait_mcode_does_not_require_c38(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {
                            "all": [
                                {"contact": "S029"},
                                {
                                    "compare": {
                                        "relation": "=",
                                        "value": "R0001",
                                        "other": "#00008",
                                    }
                                },
                            ]
                        },
                        "actions": [_out("A108")],
                    }
                ]
            )
        )
        self.assertNotIn("mcode_wait_without_c38", _rules(result))

    @unittest.skipUnless(AXIS_GENERATION, "axis generation is disabled in public edition")
    def test_axis_scaffolding_is_required(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"always": True},
                    "actions": [{"op": "AXMOVE", "axis": "AX3", "data": "R263"}],
                }
            ]
        )
        plan["resources"] = []
        rules = _rules(lint_plan(plan))
        self.assertIn("axis_trigger_unconditional", rules)
        self.assertIn("axis_move_data_unregistered", rules)
        self.assertIn("axis_stop_missing", rules)

    @unittest.skipUnless(AXIS_GENERATION, "axis generation is disabled in public edition")
    def test_axis_scaffolding_can_pass(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"contact": "A211"},
                    "actions": [{"op": "AXMOVE", "axis": "AX3", "data": "R263"}],
                },
                {
                    "condition": {"contact": "A217"},
                    "actions": [{"op": "AXSTOP", "axis": "AX3"}],
                },
            ]
        )
        plan["machine"] = {"pr17": 2}
        plan["resources"] = [
            {"addr": f"R{index}", "source": "user"}
            for index in range(263, 267)
        ]
        rules = _rules(lint_plan(plan))
        self.assertNotIn("axis_trigger_unconditional", rules)
        self.assertNotIn("axis_move_data_unregistered", rules)
        self.assertNotIn("axis_stop_missing", rules)

    @unittest.skipUnless(AXIS_GENERATION, "axis generation is disabled in public edition")
    def test_axis_move_requires_pr17_declaration(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"contact": "A211"},
                    "actions": [{"op": "AXMOVE", "axis": "AX3", "data": "R263"}],
                },
                {
                    "condition": {"contact": "A217"},
                    "actions": [{"op": "AXSTOP", "axis": "AX3"}],
                },
            ]
        )
        plan["resources"] = [
            {"addr": f"R{index}", "source": "user"}
            for index in range(263, 267)
        ]
        self.assertIn("axis_unit_undeclared", _rules(lint_plan(plan)))

        plan["machine"] = {"pr17": 2, "axis_data_unit": "blu"}
        self.assertNotIn("axis_unit_undeclared", _rules(lint_plan(plan)))

    @unittest.skipUnless(AXIS_GENERATION, "axis generation is disabled in public edition")
    def test_axis_move_rejects_constant_mode_and_reserved_values(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"contact": "A001"},
                    "actions": [
                        {"op": "MOV", "src": "#25000", "dst": "R263"},
                        {"op": "MOV", "src": "#1000", "dst": "R264"},
                        {"op": "MOV", "src": "#2", "dst": "R265"},
                        {"op": "MOV", "src": "#7", "dst": "R266"},
                        {"op": "AXMOVE", "axis": "AX3", "data": "R263"},
                    ],
                },
                {
                    "condition": {"contact": "A217"},
                    "actions": [{"op": "AXSTOP", "axis": "AX3"}],
                },
            ]
        )
        plan["machine"] = {"pr17": 2}
        plan["resources"] = [
            {"addr": f"R{index}", "source": "user"}
            for index in range(263, 267)
        ]
        rules = _rules(lint_plan(plan))
        self.assertIn("axis_move_mode_invalid", rules)
        self.assertIn("axis_move_reserved_nonzero", rules)

    @unittest.skipUnless(AXIS_GENERATION, "axis generation is disabled in public edition")
    def test_axis_stop_on_reset_warns(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {
                        "all": [{"contact": "C036"}, {"contact": "C037"}]
                    },
                    "actions": [{"op": "AXSTOP", "axis": "AX3"}],
                }
            ]
        )
        self.assertIn("axis_stop_reset", _rules(lint_plan(plan)))

    def test_mcode_decode_without_s029_warns(self) -> None:
        result = lint_plan(
            _plan(
                [
                    {
                        "condition": {
                            "compare": {
                                "relation": "=",
                                "value": "R0001",
                                "other": "#00050",
                            }
                        },
                        "actions": [_out("A150")],
                    },
                    {
                        "condition": {"contact": "A150"},
                        "actions": [_out("C038")],
                    },
                ]
            )
        )
        self.assertIn("mcode_decode_without_s029", _rules(result))

    def test_register_bitwise_overwrite_warns(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"contact": "I000"},
                    "actions": [
                        {"op": "MOV", "src": "#0", "dst": "R256"},
                    ],
                }
            ]
        )
        plan["resources"] = [
            {"addr": "I000", "source": "user"},
            {"addr": "R256.01", "source": "user"},
            {"addr": "R256.02", "source": "user"},
        ]
        self.assertIn("register_bitwise_overwrite", _rules(lint_plan(plan)))

    @unittest.skipUnless(AXIS_GENERATION, "axis generation is disabled in public edition")
    def test_axis_move_reports_missing_data_write(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"contact": "A211"},
                    "actions": [{"op": "AXMOVE", "axis": "AX3", "data": "R263"}],
                },
                {
                    "condition": {"contact": "A217"},
                    "actions": [{"op": "AXSTOP", "axis": "AX3"}],
                },
            ]
        )
        plan["resources"] = [
            {"addr": f"R{index}", "source": "user"}
            for index in range(263, 267)
        ]
        result = lint_plan(plan)
        self.assertIn("axis_move_data_order", _rules(result))
        issue = next(
            item for item in result["issues"]
            if item["rule"] == "axis_move_data_order"
        )
        for address in ("R263", "R264", "R265", "R266"):
            self.assertIn(address, issue["detail"])

    @unittest.skipUnless(AXIS_GENERATION, "axis generation is disabled in public edition")
    def test_axis_move_accepts_prior_data_write(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"contact": "A001"},
                    "actions": [
                        {"op": "MOV", "src": "#01000", "dst": "R263"},
                        {"op": "MOV", "src": "#01500", "dst": "R264"},
                        {"op": "MOV", "src": "#00001", "dst": "R265"},
                        {"op": "MOV", "src": "#00000", "dst": "R266"},
                    ],
                },
                {
                    "condition": {"contact": "A211"},
                    "actions": [{"op": "AXMOVE", "axis": "AX3", "data": "R263"}],
                },
                {
                    "condition": {"contact": "A217"},
                    "actions": [{"op": "AXSTOP", "axis": "AX3"}],
                },
            ]
        )
        rules = _rules(lint_plan(plan))
        self.assertNotIn("axis_move_data_order", rules)

    @unittest.skipUnless(AXIS_GENERATION, "axis generation is disabled in public edition")
    def test_axis_move_accepts_same_rung_data_write_before_element(self) -> None:
        plan = _plan(
            [
                {
                    "condition": {"contact": "A001"},
                    "actions": [
                        {"op": "MOV", "src": "#01000", "dst": "R263"},
                        {"op": "MOV", "src": "#01500", "dst": "R264"},
                        {"op": "MOV", "src": "#00001", "dst": "R265"},
                        {"op": "MOV", "src": "#00000", "dst": "R266"},
                        {"op": "AXMOVE", "axis": "AX3", "data": "R263"},
                    ],
                },
                {
                    "condition": {"contact": "A217"},
                    "actions": [{"op": "AXSTOP", "axis": "AX3"}],
                },
            ]
        )
        rules = _rules(lint_plan(plan))
        self.assertNotIn("axis_move_data_order", rules)


if __name__ == "__main__":
    unittest.main()

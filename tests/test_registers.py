from __future__ import annotations

import unittest

from syntec_lad.plan_lint import lint_plan
from syntec_lad.registers import (
    describe_at_value,
    describe_register,
    load_register_zone_data,
    load_register_zones,
    register_zone,
    write_assessment,
)


def _plan(networks: list[dict], *, resources: list[dict] | None = None) -> dict:
    plan = {
        "schema": "syntec-lad-plan/v1",
        "programs": [{"name": "MAIN", "networks": networks}],
    }
    if resources is not None:
        plan["resources"] = resources
    return plan


def _mov(dst: str) -> dict:
    return {
        "condition": {"always": True},
        "actions": [{"op": "MOV", "src": "#1", "dst": dst}],
    }


def _rules(result: dict) -> set[str]:
    return {item["rule"] for item in result["issues"]}


class RegisterZoneTableTests(unittest.TestCase):
    def test_zones_cover_r0_to_r65535_without_gaps(self) -> None:
        zones = load_register_zones()
        cursor = 0
        for zone in zones:
            self.assertEqual(zone["start"], cursor, zone["id"])
            self.assertGreaterEqual(zone["end"], zone["start"])
            cursor = zone["end"] + 1
        self.assertEqual(cursor, 65536)

    def test_known_zones(self) -> None:
        self.assertEqual(register_zone(2050)["id"], "R2050-R2090")
        self.assertEqual(register_zone(2100)["id"], "R2100-R3100")
        self.assertEqual(register_zone(700)["id"], "R640-R1023")
        self.assertEqual(register_zone(20000)["id"], "R20000-R65535")
        self.assertIsNone(register_zone(65536))

    def test_describe_marks_owner_and_permissions(self) -> None:
        conditional = describe_register("R2100")
        self.assertIsNotNone(conditional)
        self.assertEqual(conditional["owner"], "user_conditional")
        self.assertEqual(conditional["retain"], None)
        self.assertIn("Pr3228", " ".join(conditional["conditions"]))

        system = describe_register("R8001")
        self.assertIsNotNone(system)
        self.assertEqual(system["owner"], "system")
        self.assertEqual(system["plc_access"], "readonly")
        self.assertEqual(system["macro_access"], "readwrite")

        user = describe_register("R20000")
        self.assertIsNotNone(user)
        self.assertEqual(user["owner"], "user")
        self.assertEqual(user["macro_access"], "readonly")

    def test_bit_access_is_rejected_above_r639(self) -> None:
        self.assertTrue(describe_register("R300.0")["bit_access"])
        self.assertFalse(describe_register("R700.0")["bit_access"])
        self.assertEqual(write_assessment("R700.0")["severity"], "error")

    def test_write_assessment_distinguishes_readonly_and_per_address(self) -> None:
        self.assertEqual(write_assessment("R81")["severity"], "error")
        self.assertEqual(write_assessment("R8001")["severity"], "error")
        self.assertEqual(write_assessment("R8256")["severity"], "error")
        self.assertEqual(write_assessment("R0")["severity"], "warning")
        self.assertEqual(write_assessment("R520")["severity"], "ok")
        self.assertEqual(write_assessment("R50")["severity"], "ok")

    def test_at_value_mapping(self) -> None:
        shared = describe_at_value("@108001")
        self.assertEqual(shared["target_register"], "R8001")
        self.assertEqual(shared["kind"], "r_mapped")
        self.assertEqual(shared["mapping"], "r_offset")
        self.assertEqual(shared["offset"], 100000)
        self.assertTrue(any("COR 16" in note for note in shared["notes"]))

        cloud = describe_at_value("@120000")
        self.assertEqual(cloud["target_register"], "R20000")

        low = describe_at_value("@401")
        self.assertEqual(low["target_register"], "R1")
        self.assertEqual(low["offset"], 400)

        mid = describe_at_value("@10000")
        self.assertEqual(mid["target_register"], "R0")
        self.assertEqual(mid["offset"], 10000)
        self.assertEqual(describe_at_value("@14095")["target_register"], "R4095")
        self.assertEqual(describe_at_value("@165535")["target_register"], "R65535")

        indirect = describe_at_value("R@R100")
        self.assertEqual(indirect["kind"], "indirect_register")
        self.assertEqual(indirect["official_syntax"], "R@R100")
        self.assertIn("间接寻址", indirect["note"])
        self.assertEqual(describe_at_value("@R100")["kind"], "indirect_register")

    def test_at_global_variables_that_are_not_r(self) -> None:
        for value, kind in (
            ("@0", "vacant"),
            ("@1", "variable"),
            ("@100", "variable"),
            ("@400", "variable"),
            ("@656", "variable"),
            ("@1000", "system"),
            ("@1001", "variable"),
            ("@60000", "extended"),
            ("@79999", "extended"),
            ("@14096", "unmapped"),
        ):
            with self.subTest(value=value):
                info = describe_at_value(value)
                self.assertIsNotNone(info)
                self.assertEqual(info["kind"], kind)
                self.assertIsNone(info["target_register"])
                self.assertIsNone(info["register"])

    def test_at_writable_ranges_are_documented(self) -> None:
        data = load_register_zone_data()
        ranges = data["at_writable_ranges"]
        self.assertIn([50, 80], ranges)
        self.assertIn([5800, 7999], ranges)
        self.assertIn([15000, 65535], ranges)
        self.assertNotIn([5800, 8255], ranges)


class RegisterPlanLintTests(unittest.TestCase):
    def test_bit_write_above_639_is_an_error(self) -> None:
        result = lint_plan(_plan([_mov("R700.0")]))
        self.assertFalse(result["ok"])
        self.assertIn("r_bit_access_invalid", _rules(result))

    def test_readonly_system_zone_is_an_error(self) -> None:
        result = lint_plan(_plan([_mov("R8256")]))
        self.assertFalse(result["ok"])
        self.assertIn("resource_readonly_write", _rules(result))

    def test_per_address_system_write_is_a_warning(self) -> None:
        result = lint_plan(_plan([_mov("R0")]))
        self.assertIn("r_system_write", _rules(result))
        self.assertTrue(result["ok"])

    def test_known_system_write_exception_passes(self) -> None:
        result = lint_plan(_plan([_mov("R520")]))
        self.assertNotIn("r_system_write", _rules(result))

    def test_retain_true_on_nonretain_zone_is_an_error(self) -> None:
        plan = _plan(
            [_mov("R50")],
            resources=[{"addr": "R50", "source": "user", "retain": True}],
        )
        result = lint_plan(plan)
        self.assertFalse(result["ok"])
        self.assertIn("r_retain_mismatch", _rules(result))

    def test_conditional_zone_requires_note(self) -> None:
        plan = _plan(
            [_mov("R2100")],
            resources=[{"addr": "R2100", "source": "user"}],
        )
        result = lint_plan(plan)
        self.assertIn("r_conditional_zone", _rules(result))

    def test_conditional_zone_note_passes(self) -> None:
        plan = _plan(
            [_mov("R2100")],
            resources=[
                {
                    "addr": "R2100",
                    "source": "user",
                    "note": "Pr3228=0，用户自定义；已确认未启用刀具管理",
                }
            ],
        )
        result = lint_plan(plan)
        self.assertNotIn("r_conditional_zone", _rules(result))


if __name__ == "__main__":
    unittest.main()

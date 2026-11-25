"""Register-zone knowledge for SYNTEC PLC ``R`` addresses.

The bundled JSON is the machine-readable form of the R allocation table.  It
answers the question the plain address index cannot: *may the ladder write this
register, does it survive power-off, can it be bit-addressed, and is it a
system interface or user space?*

This module also separates two things that are easy to confuse:

* ``@R100`` in a ladder operand is indirect addressing: the value inside R100
  is used as the register number.  The official editor syntax is ``R@R100``;
  ``@R100`` is accepted as a compatibility alias.
* ``@108001`` in a macro/HMI is a global variable mapped to R8001, not an
  indirect ladder operand.  The ``@`` namespace is piecewise: only
  ``@401~@655``, ``@10000~@14095`` and ``@100000~@165535`` map to R.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from .errors import LadValidationError

REGISTER_ZONE_SCHEMA = "syntec-lad-register-zones/v1"

_R_RE = re.compile(r"^@?R(\d{1,5})(?:\.(\d{1,2}))?$", re.IGNORECASE)
_AT_R_RE = re.compile(r"^@R(\d{1,5})(?:\.(\d{1,2}))?$", re.IGNORECASE)
_R_AT_R_RE = re.compile(r"^R@R(\d{1,5})(?:\.(\d{1,2}))?$", re.IGNORECASE)
_AT_RE = re.compile(r"^@(\d{1,6})$")
_AT_RULE_RE = re.compile(r"^@(\d+)(?:~@(\d+))?$")

OWNER_LABELS = {
    "system": "CNC 系统接口",
    "system-app": "系统加值应用",
    "user": "使用者自定义",
    "user_conditional": "条件占用 / 使用者自定义",
}

ACCESS_LABELS = {
    "readonly": "只读",
    "readwrite": "读写",
    "per_address": "逐条定义",
    "conditional": "依条件",
}


def _candidate_paths() -> list[Path]:
    package_root = Path(__file__).resolve().parent
    return [
        package_root / "data" / "register-zones.json",
        package_root.parent / "references" / "register-zones.json",
        Path.cwd() / "syntec_lad" / "data" / "register-zones.json",
    ]


def default_register_zone_path() -> Path:
    for path in _candidate_paths():
        if path.is_file():
            return path
    looked_at = "\n".join(f"  - {path}" for path in _candidate_paths())
    raise LadValidationError(
        "bundled register-zone table not found; looked at:\n" + looked_at
    )


@lru_cache(maxsize=4)
def _load_cached(path_text: str) -> dict[str, Any]:
    path = Path(path_text)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except OSError as exc:
        raise LadValidationError(f"cannot read register-zone table {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise LadValidationError(f"invalid register-zone JSON {path}: {exc}") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("zones"), list):
        raise LadValidationError(f"register-zone table {path} has no zones array")
    return raw


def load_register_zone_data(path: str | Path | None = None) -> dict[str, Any]:
    selected = Path(path) if path is not None else default_register_zone_path()
    return _load_cached(str(selected.resolve()))


def load_register_zones(path: str | Path | None = None) -> list[dict[str, Any]]:
    return load_register_zone_data(path)["zones"]


def parse_register(value: str) -> tuple[int, int | None] | None:
    """Return ``(index, bit)`` for ``R2050`` / ``R600.1``.

    Indirect forms (``R@R600`` / ``@R600``) belong to
    :func:`describe_at_value`, not to a plain register lookup.
    """

    match = _R_RE.fullmatch(str(value).strip())
    if not match:
        return None
    bit = match.group(2)
    return int(match.group(1)), int(bit) if bit is not None else None


def register_zone(index: int, path: str | Path | None = None) -> dict[str, Any] | None:
    if index < 0 or index > 65535:
        return None
    for zone in load_register_zones(path):
        if int(zone["start"]) <= index <= int(zone["end"]):
            return zone
    return None


def _in_ranges(index: int, ranges: list[list[int]] | None) -> bool:
    for pair in ranges or []:
        if len(pair) >= 2 and int(pair[0]) <= index <= int(pair[1]):
            return True
    return False


def describe_register(
    value: str,
    *,
    path: str | Path | None = None,
) -> dict[str, Any] | None:
    parsed = parse_register(value)
    if parsed is None:
        return None
    index, bit = parsed
    zone = register_zone(index, path)
    if zone is None:
        return None
    data = load_register_zone_data(path)
    bit_limit = data.get("bit_address_limit")
    bit_allowed = bool(zone.get("bit_access"))
    bit_note = ""
    if bit is not None and not bit_allowed:
        bit_note = (
            f"R{index}.{bit:02d} 非法：{zone['name']} 不支持位存取；"
            "需要位标志请用 A 位（或者该区明确允许时再用 Rxxx.y）"
        )
    elif bit is None and not bit_allowed:
        bit_note = f"{zone['name']} 整字读写，不能写 R{index}.y"
    if bit_limit is not None and bit is not None and index > int(bit_limit):
        bit_allowed = False
        bit_note = (
            f"R{bit_limit} 以上不支持位存取；R{index}.{bit:02d} 会被编辑器拒绝"
        )
    return {
        "addr": f"R{index}" + (f".{bit:02d}" if bit is not None else ""),
        "index": index,
        "bit": bit,
        "zone_id": zone["id"],
        "zone_name": zone["name"],
        "owner": zone["owner"],
        "owner_label": OWNER_LABELS.get(zone["owner"], zone["owner"]),
        "plc_access": zone["plc_access"],
        "plc_access_label": ACCESS_LABELS.get(zone["plc_access"], zone["plc_access"]),
        "macro_access": zone["macro_access"],
        "macro_access_label": ACCESS_LABELS.get(zone["macro_access"], zone["macro_access"]),
        "bit_access": bit_allowed,
        "bit_note": bit_note,
        "retain": zone.get("retain"),
        "retain_note": zone.get("retain_note"),
        "purpose": zone.get("purpose"),
        "conditions": list(zone.get("conditions") or []),
        "notes": list(zone.get("notes") or []),
        "source": zone.get("source"),
    }


def write_assessment(
    value: str,
    *,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Return ``ok`` / ``warning`` / ``error`` for a ladder write to ``value``."""

    parsed = parse_register(value)
    if parsed is None:
        return {
            "severity": "ok",
            "detail": "not an R register",
            "register": None,
        }
    index, bit = parsed
    info = describe_register(value, path=path)
    if info is None:
        return {
            "severity": "error",
            "detail": f"R{index} 超出 R0~R65535",
            "register": None,
        }
    if bit is not None and not info["bit_access"]:
        return {
            "severity": "error",
            "detail": info["bit_note"] or f"R{index} 不支持位存取",
            "register": info,
        }
    zone = register_zone(index, path) or {}
    access = zone.get("plc_access")
    if access == "readonly":
        return {
            "severity": "error",
            "detail": (
                f"R{index} 属于 {zone.get('name')}：阶梯程序只读；"
                + ("宏程序可读写。" if zone.get("macro_access") == "readwrite" else "宏程序也只读。")
            ),
            "register": info,
        }
    if access == "per_address":
        if _in_ranges(index, zone.get("plc_access_exceptions")):
            return {
                "severity": "ok",
                "detail": f"R{index} 在 {zone.get('name')} 的已知可写例外内",
                "register": info,
            }
        return {
            "severity": "warning",
            "detail": (
                f"R{index} 属于 {zone.get('name')}，权限逐条定义；"
                "写入前必须查接口说明或权限表，不能因为看着空就写"
            ),
            "register": info,
        }
    return {
        "severity": "ok",
        "detail": f"R{index} 属于 {zone.get('name')}，阶梯程序可读写",
        "register": info,
    }


def _at_rule(number: int, data: dict[str, Any]) -> dict[str, Any] | None:
    for rule in data.get("at_value_rules") or []:
        match = _AT_RULE_RE.fullmatch(str(rule.get("pattern", "")))
        if not match:
            continue
        start = int(match.group(1))
        end = int(match.group(2) or start)
        if start <= number <= end:
            return rule
    return None


def describe_at_value(
    value: str,
    *,
    path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Explain a macro/HMI ``@`` value.

    Only part of the ``@`` namespace maps to R registers.  ``@1~@400``,
    ``@656~@1999`` and ``@60000~@79999`` are independent variables and must
    not be reported as R aliases.
    """

    text = str(value).strip()
    indirect = _R_AT_R_RE.fullmatch(text) or _AT_R_RE.fullmatch(text)
    if indirect:
        index = int(indirect.group(1))
        bit = indirect.group(2)
        syntax = "R@R" if text.upper().startswith("R@R") else "@R"
        return {
            "kind": "indirect_register",
            "addr": f"{syntax}{index}" + (f".{bit}" if bit else ""),
            "official_syntax": f"R@R{index}",
            "target_register": f"R{index}",
            "note": (
                "这是阶梯图的间接寻址操作数。官方写法是 "
                f"R@R{index}：先读 R{index} 的值，再把该值当作要访问的寄存器号。"
                "它不是宏程序的 @ 公用变量。"
            ),
            "register": describe_register(f"R{index}", path=path),
        }
    match = _AT_RE.fullmatch(text)
    if not match:
        return None
    number = int(match.group(1))
    data = load_register_zone_data(path)
    rule = _at_rule(number, data)
    if rule is None:
        return {
            "kind": "unmapped",
            "addr": f"@{number}",
            "mapping": None,
            "offset": None,
            "target_register": None,
            "at_writable": None,
            "rule": None,
            "notes": [
                f"@{number} 不在已记录的公用变量或 R 映射区间；"
                "不要自行猜测它对应哪个 R。"
            ],
            "register": None,
        }

    kind = rule["kind"]
    if kind != "r_mapped":
        return {
            "kind": kind,
            "addr": f"@{number}",
            "mapping": None,
            "offset": None,
            "target_register": None,
            "at_writable": None,
            "rule": rule,
            "notes": [rule.get("note", "")] if rule.get("note") else [],
            "register": None,
        }

    offset = int(rule["offset"])
    r_index = number - offset
    writable = _in_ranges(r_index, data.get("at_writable_ranges"))
    info = describe_register(f"R{r_index}", path=path)
    notes = [
        f"映射公式：R = @ - {offset}，所以 @{number} = R{r_index}。",
    ]
    if r_index > 7999:
        notes.append("DOS 版本只支持 R0~R7999；这个 @ 值在 DOS 上不可用。")
    if 8001 <= r_index <= 8500:
        notes.append(
            "部分控制器版本已限制通过 @ 变量修改 R8001~R8500"
            "（会报 COR 16 不合法的变量存取）；要改参数请走 Pr5001~Pr5500。"
        )
    if not writable:
        notes.append(
            f"R{r_index} 不在 @ 变量可写区间内；宏/人机界面只能读，写入可能无效。"
        )
    return {
        "kind": "r_mapped",
        "addr": f"@{number}",
        "mapping": "r_offset",
        "offset": offset,
        "target_register": f"R{r_index}",
        "at_writable": writable,
        "rule": rule,
        "notes": notes,
        "register": info,
    }


def render_register_zone(info: dict[str, Any]) -> str:
    """Render one ``describe_register`` result as compact Chinese text."""

    lines = [
        f"{info['addr']}  {info['zone_name']}  [{info['zone_id']}]",
        f"归属    : {info['owner_label']}",
        f"阶梯权限: {info['plc_access_label']}    宏/人机界面: {info['macro_access_label']}",
    ]
    retain = info.get("retain")
    if retain is True:
        retain_text = "是"
    elif retain is False:
        retain_text = "否"
    else:
        retain_text = info.get("retain_note") or "条件保持"
    lines.append(f"掉电保持: {retain_text}")
    lines.append(f"位存取  : {'可以' if info['bit_access'] else '不可以'}")
    if info.get("purpose"):
        lines.append(f"用途    : {info['purpose']}")
    if info.get("conditions"):
        lines.append("条件    : " + "；".join(info["conditions"]))
    if info.get("bit_note"):
        lines.append("位提示  : " + info["bit_note"])
    for note in info.get("notes") or []:
        lines.append("注意    : " + note)
    return "\n".join(lines)


def render_at_value(info: dict[str, Any]) -> str:
    if info["kind"] == "indirect_register":
        return f"{info['addr']}: {info['note']}"
    kind = info["kind"]
    if kind == "r_mapped":
        lines = [
            f"{info['addr']} -> {info['target_register']}"
            f"（R = @ - {info['offset']}）"
        ]
    elif kind == "vacant":
        lines = [f"{info['addr']}  空白 VACANT，不对应 R"]
    elif kind == "variable":
        rule = info.get("rule") or {}
        type_text = rule.get("type", "Double")
        access = rule.get("access", "R/W")
        lines = [f"{info['addr']}  公用变量（{type_text}，{access}），不对应 R"]
    elif kind == "system":
        lines = [f"{info['addr']}  系统变数，不对应 R"]
    elif kind == "extended":
        lines = [f"{info['addr']}  扩充公用变量（Double，R/W），不对应 R"]
    else:
        lines = [f"{info['addr']}  未记录区间，不对应 R"]
    register = info.get("register")
    if register:
        lines.append(
            f"{register['addr']}  {register['zone_name']}  "
            f"阶梯 {register['plc_access_label']} / 宏 {register['macro_access_label']}"
        )
    for note in info.get("notes") or []:
        lines.append("注意: " + note)
    return "\n".join(lines)


__all__ = [
    "ACCESS_LABELS",
    "OWNER_LABELS",
    "REGISTER_ZONE_SCHEMA",
    "default_register_zone_path",
    "describe_at_value",
    "describe_register",
    "load_register_zone_data",
    "load_register_zones",
    "parse_register",
    "register_zone",
    "render_at_value",
    "render_register_zone",
    "write_assessment",
]

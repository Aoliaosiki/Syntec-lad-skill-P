"""Resource inventory for Syntec ladder programs.

The report answers three questions without inventing anything:

* which addresses does this program already use
* what do those addresses mean (from the type-4 comments)
* which addresses are still untouched

Nothing here allocates.  A row becomes authoritative only after a human copies
it into ``syntec-lad-plan/v1`` ``resources`` with a ``source`` of ``user`` or
``io-table``.  ``plan_lint`` rejects anything still marked ``suggested``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from .inspection import inspect_document
from .model import LadDocument
from .registers import (
    describe_register,
    write_assessment,
)

RESOURCE_SCHEMA = "syntec-lad-resources/v1"

FAMILY_ORDER = ("I", "O", "A", "C", "S", "TM", "CT", "R")

FAMILY_LIMITS = {
    "I": 511,
    "O": 511,
    "A": 511,
    "C": 511,
    "S": 511,
    "TM": 255,
    "CT": 255,
    "R": 65535,
}

COIL_MNEMONICS = {"OUT", "OUTI", "PLS", "PLF", "SET", "RST"}
DATA_WRITE_MNEMONICS = {"MOV", "ADD", "SUB", "MUL", "DIV", "AND", "OR", "XOR"}
TIMER_MNEMONICS = {"TIM"}
COUNTER_MNEMONICS = {
    "CNTUP",
    "CNTDOWN",
    "CNTRESET",
    "CNTRINGUP",
    "CNTRINGDOWN",
}

ADDR_RE = re.compile(r"@?\b(I|O|A|C|S|TM|CT|R)(\d{1,5})(?:\.(\d{1,2}))?\b")

#: Zones where the ladder program must not write.  Only rules stated directly in
#: ``references/panming/address-map.md`` are encoded here; anything ambiguous is
#: left to the crosscheck/human review instead of being guessed.
READ_ONLY_ZONES = (
    {
        "family": "S",
        "from": 0,
        "to": 511,
        "reason": "S 是 CNC→PLC 只读状态区，阶梯程序不能写",
    },
    {
        "family": "I",
        "from": 0,
        "to": 511,
        "reason": "I 是实体输入接点，阶梯程序只读",
    },
    {
        "family": "R",
        "from": 81,
        "to": 100,
        "reason": "R81~R100 对应系统参数 3401~3420，参数画面单向写入，阶梯只读",
    },
    {
        "family": "R",
        "from": 8000,
        "to": 8255,
        "reason": "R8000~R8255 宏程序可读写，阶梯程序只读",
    },
)

ZONE_NOTES = (
    {"family": "R", "from": 0, "to": 79, "reason": "CNC 系统接口区，按手册定义使用"},
    {"family": "R", "from": 40, "to": 49, "reason": "PLC 警报讯息区"},
    {"family": "R", "from": 103, "to": 192, "reason": "铣床刀号数据 T1~T90"},
    {"family": "R", "from": 193, "to": 255, "reason": "掉电保持区（数值）"},
    {"family": "R", "from": 256, "to": 511, "reason": "可位存取，掉电不保持"},
)


def normalize_address(family: str, index: str | int, bit: str | int | None = None) -> str:
    text = f"{family.upper()}{int(index)}"
    if bit is not None and str(bit) != "":
        text = f"{text}.{int(bit):02d}"
    return text


def parse_address(value: str) -> tuple[str, int, int | None] | None:
    match = ADDR_RE.fullmatch(value.strip().upper())
    if not match:
        return None
    family = match.group(1)
    bit = match.group(3)
    return family, int(match.group(2)), int(bit) if bit is not None else None


def _iter_comment_addresses(
    comments: Iterable[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    """Map address -> {"raw": comment text, "symbol": ..., "short": ...}."""

    mapping: dict[str, dict[str, str]] = {}
    for block in comments:
        if block.get("type") != 4:
            continue
        text = str(block.get("text") or "")
        if not text.strip():
            continue
        parts = [part.strip() for part in text.split("\t")]
        for match in ADDR_RE.finditer(text.upper()):
            address = normalize_address(match.group(1), match.group(2), match.group(3))
            symbol = ""
            short = ""
            if parts and parse_address(parts[0]) is not None:
                symbol = parts[0]
                short = parts[1] if len(parts) > 1 else ""
            mapping.setdefault(
                address,
                {
                    "raw": text.strip(),
                    "symbol": symbol,
                    "short": short,
                },
            )
    return mapping


def _new_entry(address: str) -> dict[str, Any]:
    parsed = parse_address(address)
    if parsed is None:
        family, index, bit = address.rstrip("0123456789"), 0, None
    else:
        family, index, bit = parsed
    entry = {
        "addr": address,
        "family": family,
        "index": index,
        "bit": bit,
        "reads": 0,
        "writes": 0,
        "programs": [],
        "networks": [],
        "mnemonics": [],
        "comment": "",
        "symbol": "",
        "short": "",
    }
    if family == "R":
        info = describe_register(address)
        if info is not None:
            entry["register"] = info
            entry["zone_id"] = info["zone_id"]
            entry["zone_name"] = info["zone_name"]
            entry["owner"] = info["owner"]
            entry["owner_label"] = info["owner_label"]
            entry["plc_access"] = info["plc_access"]
            entry["plc_access_label"] = info["plc_access_label"]
            entry["bit_access"] = info["bit_access"]
            entry["retain"] = info["retain"]
    return entry


def scan_document(document: LadDocument) -> dict[str, Any]:
    inspection = inspect_document(document)
    rows = {row["record_start"]: row for row in inspection["rows"]}
    comments = _iter_comment_addresses(inspection["comments"])
    entries: dict[str, dict[str, Any]] = {}

    for candidate in inspection["network_candidates"]:
        cells: list[dict[str, Any]] = []
        for record in range(candidate["record_start"], candidate["record_end"] + 1):
            row = rows.get(record)
            if row and row["kind"] == "code":
                cells.extend(row["cells"])
        program = candidate.get("program")
        for cell in cells:
            mnemonic = str(cell.get("mnemonic") or "").upper()
            operands = [
                str(item.get("value") or "").strip()
                for item in (cell.get("operands") or [])
            ]

            def touch(address: str, is_write: bool) -> None:
                entry = entries.setdefault(address, _new_entry(address))
                if is_write:
                    entry["writes"] += 1
                else:
                    entry["reads"] += 1
                if program and program not in entry["programs"]:
                    entry["programs"].append(program)
                network = candidate["id"]
                if network not in entry["networks"]:
                    entry["networks"].append(network)
                if mnemonic and mnemonic not in entry["mnemonics"]:
                    entry["mnemonics"].append(mnemonic)

            axis_move = mnemonic.replace(" ", "") == "AXMOVE"
            for position, operand in enumerate(operands):
                operands_text = operand.upper()
                if operands_text.startswith("R@R"):
                    # R@R61 reads R61 first and then uses its value as the
                    # target register; only the pointer register is knowable.
                    operand_text = "R" + operand[3:]
                else:
                    operand_text = operand.replace("@", "")
                parsed = parse_address(operand_text)
                if parsed is None:
                    continue
                if axis_move and position == 1:
                    # AX MOVE reads four consecutive registers starting at DATA.
                    base = parsed[1]
                    for offset in range(4):
                        if base + offset <= FAMILY_LIMITS["R"]:
                            touch(normalize_address("R", base + offset), False)
                    continue
                address = normalize_address(*parsed)
                is_write = False
                if mnemonic in COIL_MNEMONICS and position == 0:
                    is_write = True
                elif mnemonic in DATA_WRITE_MNEMONICS and position == len(operands) - 1:
                    is_write = True
                elif mnemonic in TIMER_MNEMONICS | COUNTER_MNEMONICS and position == 0:
                    is_write = True
                touch(address, is_write)

    for address, entry in entries.items():
        info = comments.get(address)
        if info:
            entry["comment"] = info["raw"]
            entry["symbol"] = info["symbol"]
            entry["short"] = info["short"]

    families: dict[str, Any] = {}
    for family in FAMILY_ORDER:
        used = [entry for entry in entries.values() if entry["family"] == family]
        used.sort(key=lambda item: (item["index"], item["bit"] or 0))
        families[family] = {"used": used, "count": len(used)}

    return {
        "inspection": inspection,
        "families": families,
        "entries": entries,
    }


def free_ranges(
    used: Iterable[int],
    *, upper: int, limit: int = 48,
) -> dict[str, Any]:
    taken = {value for value in used if 0 <= value <= upper}
    ranges: list[list[int]] = []
    start: int | None = None
    for value in range(0, upper + 1):
        if value in taken:
            if start is not None:
                ranges.append([start, value - 1])
                start = None
        elif start is None:
            start = value
    if start is not None:
        ranges.append([start, upper])
    total = len(ranges)
    return {
        "upper": upper,
        "ranges": ranges[:limit],
        "count": total,
        "truncated": max(0, total - limit),
    }


def _family_upper(family: str, range_max: int | None) -> int:
    if family == "R":
        if range_max is not None:
            return max(0, int(range_max))
        return 1023
    return FAMILY_LIMITS[family]


def resource_report(
    document: LadDocument,
    *,
    io_points: dict[str, str] | None = None,
    io_path: str | None = None,
    range_max: int | None = None,
    path: str | None = None,
) -> dict[str, Any]:
    scan = scan_document(document)
    inspection = scan["inspection"]
    families: dict[str, Any] = {}

    for family in FAMILY_ORDER:
        used = scan["families"][family]["used"]
        upper = _family_upper(family, range_max)
        families[family] = {
            "count": len(used),
            "upper": upper,
            "used": used,
            "free": free_ranges(
                (entry["index"] for entry in used),
                upper=upper,
            ),
        }

    warnings: list[dict[str, Any]] = []
    io_summary: dict[str, Any] | None = None
    if io_points is not None:
        ladder_io = {
            address
            for address, entry in scan["entries"].items()
            if entry["family"] in {"I", "O"}
        }
        # ``I000`` in a customer table and ``I0`` in the ladder are the same
        # point; normalize both sides before comparing.
        table_io: set[str] = set()
        for address in io_points:
            parsed = parse_address(address)
            key = normalize_address(*parsed) if parsed else address.upper()
            table_io.add(key)
        missing_from_table = sorted(ladder_io - table_io)
        unused_in_ladder = sorted(table_io - ladder_io)
        io_summary = {
            "path": io_path,
            "count": len(table_io),
            "missing_from_table": missing_from_table,
            "unused_in_ladder": unused_in_ladder,
        }
        if missing_from_table:
            warnings.append(
                {
                    "check": "io_missing_from_table",
                    "detail": (
                        f"{len(missing_from_table)} 个梯图用到的 I/O 点不在 IO 点表里："
                        + ", ".join(missing_from_table[:12])
                    ),
                    "addresses": missing_from_table,
                }
            )
        if unused_in_ladder:
            warnings.append(
                {
                    "check": "io_unused_in_ladder",
                    "detail": (
                        f"{len(unused_in_ladder)} 个 IO 点表点位在梯图里未使用："
                        + ", ".join(unused_in_ladder[:12])
                    ),
                    "addresses": unused_in_ladder,
                }
            )

    for address, entry in scan["entries"].items():
        readonly_hit = False
        if entry["writes"] > 0:
            if entry["family"] == "R":
                assessment = write_assessment(address)
                if assessment["severity"] == "error":
                    warnings.append(
                        {
                            "check": "read_only_write",
                            "address": address,
                            "detail": (
                                f"{address} 被写 {entry['writes']} 次，但 "
                                f"{assessment['detail']}"
                            ),
                        }
                    )
                    readonly_hit = True
                elif assessment["severity"] == "warning":
                    warnings.append(
                        {
                            "check": "register_zone_write",
                            "address": address,
                            "detail": (
                                f"{address} 被写 {entry['writes']} 次；"
                                f"{assessment['detail']}"
                            ),
                        }
                    )
                    readonly_hit = True
            for zone in ([] if entry["family"] == "R" else READ_ONLY_ZONES):
                if (
                    entry["family"] == zone["family"]
                    and zone["from"] <= entry["index"] <= zone["to"]
                ):
                    warnings.append(
                        {
                            "check": "read_only_write",
                            "address": address,
                            "detail": f"{address} 被写 {entry['writes']} 次，但 {zone['reason']}",
                        }
                    )
                    readonly_hit = True
                    break
        if entry["writes"] > 0 and entry["family"] == "I" and not readonly_hit:
            warnings.append(
                {
                    "check": "io_written",
                    "address": address,
                    "detail": (
                        f"{address} 是实体输入点却被线圈驱动（写 {entry['writes']} 次）；"
                        "应映射到 A 位后只写 A"
                    ),
                }
            )

    commented = sum(
        1 for entry in scan["entries"].values() if entry["comment"]
    )

    register_zones: list[dict[str, Any]] = []
    zone_rows: dict[str, dict[str, Any]] = {}
    for entry in scan["entries"].values():
        if entry["family"] != "R" or not entry.get("zone_id"):
            continue
        row = zone_rows.setdefault(
            entry["zone_id"],
            {
                "zone_id": entry["zone_id"],
                "zone_name": entry["zone_name"],
                "owner": entry["owner"],
                "owner_label": entry["owner_label"],
                "plc_access": entry["plc_access"],
                "plc_access_label": entry["plc_access_label"],
                "addresses": 0,
                "writes": 0,
            },
        )
        row["addresses"] += 1
        row["writes"] += int(entry["writes"])
    register_zones = sorted(
        zone_rows.values(),
        key=lambda item: int(item["zone_id"].split("-")[0][1:]),
    )

    return {
        "schema": RESOURCE_SCHEMA,
        "lad": {
            "path": path or (str(document.path) if getattr(document, "path", None) else None),
            "sha256": document.sha256,
            "programs": len(inspection["programs"]),
            "networks": len(inspection["network_candidates"]),
            "records": len(document.records),
        },
        "summary": {
            "addresses_used": len(scan["entries"]),
            "commented": commented,
            "uncommented": len(scan["entries"]) - commented,
            "register_zones": register_zones,
        },
        "families": families,
        "zones": {
            "read_only": list(READ_ONLY_ZONES),
            "notes": list(ZONE_NOTES),
            "registers": register_zones,
        },
        "io_table": io_summary,
        "warnings": warnings,
        "ok": not warnings,
    }


def render_resources(result: dict[str, Any], *, format: str = "md") -> str:
    if format == "csv":
        return render_resources_csv(result)
    return render_resources_markdown(result)


def render_resources_csv(result: dict[str, Any]) -> str:
    lines = [
        "addr,family,symbol,purpose,reads,writes,programs,comment,"
        "zone,owner,plc_access,retain"
    ]
    for family in FAMILY_ORDER:
        for entry in result["families"][family]["used"]:
            purpose = (entry.get("short") or "").replace(",", "，")
            comment = (entry.get("comment") or "").replace(",", "，").replace("\t", " ")
            retain = entry.get("retain")
            retain_text = "" if retain is None else ("true" if retain else "false")
            lines.append(
                ",".join(
                    [
                        entry["addr"],
                        entry["family"],
                        entry.get("symbol") or "",
                        purpose,
                        str(entry["reads"]),
                        str(entry["writes"]),
                        "/".join(entry["programs"]),
                        comment,
                        entry.get("zone_id") or "",
                        entry.get("owner") or "",
                        entry.get("plc_access") or "",
                        retain_text,
                    ]
                )
            )
    return "\n".join(lines) + "\n"


def render_resources_markdown(result: dict[str, Any]) -> str:
    lad = result["lad"]
    summary = result["summary"]
    lines = [
        "SYNTEC ladder resource report",
        f"File    : {lad['path'] or '<memory>'}",
        f"SHA256  : {lad['sha256']}",
        f"Programs: {lad['programs']}  Networks: {lad['networks']}  Records: {lad['records']}",
        f"Used    : {summary['addresses_used']}  "
        f"Commented: {summary['commented']}  Uncommented: {summary['uncommented']}",
        "",
        "未分配的地址只是候选，不代表可以直接使用；要用必须由人确认后写进 plan.resources。",
        "",
    ]

    empty_families: list[str] = []
    for family in FAMILY_ORDER:
        block = result["families"][family]
        if not block["used"]:
            empty_families.append(family)
            continue
        lines.append(f"## {family}  ({block['count']} used, 0~{block['upper']})")
        if block["used"]:
            lines.append("")
            if family == "R":
                lines.append("| addr | 分区 | symbol | purpose | R/W | programs | comment |")
                lines.append("|---|---|---|---|---|---|---|")
            else:
                lines.append("| addr | symbol | purpose | R/W | programs | comment |")
                lines.append("|---|---|---|---|---|---|")
            for entry in block["used"]:
                access = f"{entry['reads']}/{entry['writes']}"
                comment = (entry.get("comment") or "").replace("\t", " ").replace("|", "/")
                if family == "R":
                    lines.append(
                        f"| `{entry['addr']}` | {entry.get('zone_id') or ''} | "
                        f"{entry.get('symbol') or ''} | "
                        f"{entry.get('short') or ''} | {access} | "
                        f"{'/'.join(entry['programs'])} | {comment[:60]} |"
                    )
                else:
                    lines.append(
                        f"| `{entry['addr']}` | {entry.get('symbol') or ''} | "
                        f"{entry.get('short') or ''} | {access} | "
                        f"{'/'.join(entry['programs'])} | {comment[:60]} |"
                    )
        free = block["free"]
        if free["ranges"]:
            text = ", ".join(
                f"{low}" if low == high else f"{low}~{high}"
                for low, high in free["ranges"]
            )
            lines.append("")
            lines.append(f"空闲候选：{text}")
            if free["truncated"]:
                lines.append(f"（另有 {free['truncated']} 段未列出）")
        lines.append("")

    zone_rows = result["summary"].get("register_zones") or []
    if zone_rows:
        lines.append("## R 分区占用")
        lines.append("")
        lines.append("| 分区 | 名称 | 归属 | 阶梯权限 | 地址数 | 写次数 |")
        lines.append("|---|---|---|---|---|---|")
        for row in zone_rows:
            lines.append(
                f"| `{row['zone_id']}` | {row['zone_name']} | "
                f"{row['owner_label']} | {row['plc_access_label']} | "
                f"{row['addresses']} | {row['writes']} |"
            )
        lines.append("")

    if empty_families:
        lines.append("未使用区段：" + "、".join(empty_families))
        lines.append("")

    if result["io_table"]:
        table = result["io_table"]
        lines.append("## IO 点表对照")
        lines.append(f"Path: {table['path']}  Points: {table['count']}")
        if table["missing_from_table"]:
            lines.append(
                "梯图有、点表无： " + ", ".join(table["missing_from_table"][:20])
            )
        if table["unused_in_ladder"]:
            lines.append(
                "点表有、梯图无： " + ", ".join(table["unused_in_ladder"][:20])
            )
        lines.append("")

    if result["warnings"]:
        lines.append("## 警告")
        for item in result["warnings"]:
            lines.append(f"- [{item['check']}] {item['detail']}")
        lines.append("")
    else:
        lines.append("## 警告")
        lines.append("无")
        lines.append("")

    return "\n".join(lines)


def load_io_points(path: Path | str) -> dict[str, str]:
    from .crosscheck import parse_io_table

    return parse_io_table(Path(path))["points"]

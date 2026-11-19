"""Static rule checks for Syntec .lad ladder programs.

These rules encode the anti-patterns that ``SKILL.md`` lists but the parser
cannot enforce by itself: duplicate coils, using ``S`` as a coil, physical I/O
points reused everywhere instead of being mapped once, out-of-range indices,
and simplified-Chinese comments that will render as question marks.
"""

from __future__ import annotations

import re
from typing import Any

from .inspection import inspect_document
from .model import LadDocument
from .zhconv import find_simplified

LINT_SCHEMA = "syntec-lad-lint/v1"

COIL_MNEMONICS = {"OUT", "SET", "RST", "PLS", "PLF"}
CONTACT_MNEMONICS = {"LD", "LDI", "LDT", "LDTI", "LDP", "LDF"}

_ADDR_RE = re.compile(r"^(@?)(I|O|A|C|S|R|TM|CT)(\d+)(?:\.(\d+))?$")

LIMITS = {"I": 511, "O": 511, "A": 511, "C": 511, "S": 511, "R": 65535,
          "TM": 255, "CT": 255}


def _parse(text: str) -> tuple[str, int, int | None] | None:
    match = _ADDR_RE.match(text.strip().upper())
    if not match:
        return None
    family = match.group(2)
    return family, int(match.group(3)), (
        int(match.group(4)) if match.group(4) is not None else None
    )


def _issue(
    rule: str,
    severity: str,
    detail: str,
    *,
    network: str | None = None,
    program: str | None = None,
    record: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "rule": rule,
        "severity": severity,
        "detail": detail,
        "network": network,
        "program": program,
        "record": record,
    }
    if extra:
        item.update(extra)
    return item


def lint_document(
    document: LadDocument,
    *,
    io_max_uses: int = 5,
) -> dict[str, Any]:
    inspection = inspect_document(document)
    rows_by_record = {row["record_start"]: row for row in inspection["rows"]}
    issues: list[dict[str, Any]] = []

    coil_owners: dict[str, list[dict[str, Any]]] = {}
    io_uses: dict[str, list[dict[str, Any]]] = {}

    for candidate in inspection["network_candidates"]:
        cells: list[dict[str, Any]] = []
        for record in range(candidate["record_start"], candidate["record_end"] + 1):
            row = rows_by_record.get(record)
            if row and row["kind"] == "code":
                cells.extend(row["cells"])
        for cell in cells:
            mnemonic = cell["mnemonic"]
            operands = cell.get("operands") or []
            if not operands:
                continue
            target = str(operands[0].get("value") or "").strip()
            parsed = _parse(target)
            if parsed is None:
                continue
            family, index, bit = parsed
            where = {
                "network": candidate["id"],
                "program": candidate.get("program"),
                "record": candidate["record_start"],
                "column": cell["column"],
            }

            if mnemonic in COIL_MNEMONICS:
                coil_owners.setdefault(target.upper(), []).append(
                    {**where, "mnemonic": mnemonic}
                )
                if family == "S":
                    issues.append(
                        _issue(
                            "s_as_coil",
                            "error",
                            f"{mnemonic} 驱动 S 区地址 {target}：S 是 CNC→PLC 只读状态，不能做线圈",
                            extra=where,
                        )
                    )

            limit = LIMITS.get(family)
            if limit is not None and index > limit:
                issues.append(
                    _issue(
                        "address_range",
                        "error",
                        f"{target} 超出 {family} 允许范围（0~{limit}）",
                        extra=where,
                    )
                )

            if family in {"I", "O"}:
                io_uses.setdefault(target.upper(), []).append(where)

    for address, owners in sorted(coil_owners.items()):
        networks = {item["network"] for item in owners}
        if len(networks) > 1:
            issues.append(
                _issue(
                    "duplicate_coil",
                    "error",
                    f"{address} 被 {len(networks)} 个网络重复驱动："
                    + ", ".join(sorted(networks)),
                    network=sorted(networks)[0],
                    extra={"address": address, "owners": owners},
                )
            )

    for address, uses in sorted(io_uses.items()):
        networks = {item["network"] for item in uses}
        if len(networks) >= io_max_uses:
            issues.append(
                _issue(
                    "io_reused",
                    "warning",
                    f"{address} 在 {len(networks)} 个网络中直接读写，建议映射到 A300+n / A400+n 标志",
                    network=sorted(networks)[0],
                    extra={"address": address, "network_count": len(networks)},
                )
            )

    for comment in inspection["comments"]:
        text = str(comment["text"])
        hits = find_simplified(text)
        if hits:
            chars = "".join(sorted({str(item["simplified"]) for item in hits}))
            issues.append(
                _issue(
                    "simplified_comment",
                    "warning",
                    f"注释含简体字「{chars}」，编辑器按 cp950 显示会变成问号：{text.strip()[:40]}",
                    record=comment["record_start"],
                )
            )

    opcodes = {row.get("opcode") for row in inspection["rows"]}
    has_end = 0xCF in opcodes or 0xFD in opcodes
    if not has_end:
        issues.append(
            _issue("missing_end", "error", "未找到 END/FEND 指令，逻辑行结尾不完整")
        )

    counts = {"error": 0, "warning": 0, "info": 0}
    for item in issues:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1

    return {
        "schema": LINT_SCHEMA,
        "source": {
            "path": str(document.source_path) if document.source_path else None,
            "sha256": document.sha256,
            "records": len(document.records),
            "networks": len(inspection["network_candidates"]),
        },
        "summary": counts,
        "ok": counts["error"] == 0,
        "issues": issues,
    }


def render_lint(result: dict[str, Any], *, limit: int | None = None) -> str:
    source = result["source"]
    summary = result["summary"]
    lines = [
        "SYNTEC ladder lint",
        f"Source  : {source['path'] or '<memory>'}",
        f"Records : {source['records']}  Networks: {source['networks']}",
        f"Result  : {'PASS' if result['ok'] else 'FAIL'}  "
        f"error {summary.get('error', 0)} / warning {summary.get('warning', 0)} / "
        f"info {summary.get('info', 0)}",
    ]
    issues = result["issues"]
    if not issues:
        return "\n".join(lines) + "\n"
    lines.append("")
    shown = issues if limit is None else issues[:limit]
    for item in shown:
        where = []
        if item.get("network"):
            where.append(item["network"])
        if item.get("program"):
            where.append(f"prog {item['program']}")
        if item.get("record") is not None:
            where.append(f"r{item['record']}")
        loc = f"  @{', '.join(where)}" if where else ""
        lines.append(f"[{item['severity'].upper():7}] {item['rule']}: {item['detail']}{loc}")
    if limit is not None and len(issues) > limit:
        lines.append(f"... {len(issues) - limit} more issues (use --limit 0 to show all)")
    return "\n".join(lines) + "\n"

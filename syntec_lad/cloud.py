"""Confluence second-opinion support that degrades cleanly when offline.

This module never performs network I/O.  The agent is the one that talks to
Atlassian MCP; what lands here is the *evidence*: a snapshot page with its
``page id``, ``version`` and ``lastModified``.  Two consequences follow:

* the verification is reproducible after the fact, because the evidence is a
  file with a hash;
* when no snapshot and no live read exist, the report says so explicitly
  instead of silently pretending the step happened.

``references/confluence-verification.md`` documents the agent-side procedure.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CLOUD_SCHEMA = "syntec-lad-cloud/v1"

HEADER_ROW_RE = re.compile(r"^\|\s*([^|]+?)\s*\|\s*`?([^|`]*?)`?\s*\|\s*$", re.MULTILINE)
ADDR_TOKEN_RE = re.compile(r"@?\b(I|O|A|C|S|TM|CT)(\d{1,3})(?:\.(\d{1,2}))?\b")
REG_TOKEN_RE = re.compile(r"@?\bR(\d{1,5})(?:\.(\d{1,2}))?\b")

OFFLINE_NOTE = "未联网云端验证：本次结论只基于本地文件，没有 Atlassian Confluence 在线证据"


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "cp950", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("cp950", errors="replace")


def parse_snapshot(path: Path) -> dict[str, Any]:
    text = _read_text(path)
    header: dict[str, str] = {}
    preamble = "\n".join(text.splitlines()[:40])
    for key, value in HEADER_ROW_RE.findall(preamble):
        header[key.strip().casefold()] = value.strip()

    title = ""
    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    page_id = (
        header.get("page id")
        or header.get("page_id")
        or header.get("pageid")
        or path.stem
    )
    addresses = sorted(
        {
            f"{family}{index}" + (f".{int(bit):02d}" if bit else "")
            for family, index, bit in ADDR_TOKEN_RE.findall(text)
        }
    )
    registers = sorted(
        {
            f"R{index}" + (f".{int(bit):02d}" if bit else "")
            for index, bit in REG_TOKEN_RE.findall(text)
        }
    )
    return {
        "path": str(path.resolve()),
        "page_id": page_id,
        "title": title,
        "version": header.get("version"),
        "last_modified": header.get("lastmodified")
        or header.get("last_modified")
        or header.get("last modified"),
        "fetched": header.get("拉取") or header.get("fetch"),
        "addresses": addresses,
        "registers": registers,
        "bytes": path.stat().st_size,
        "mtime": datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat(),
    }


def scan_snapshots(directory: Path | str | None) -> list[dict[str, Any]]:
    if not directory:
        return []
    root = Path(directory)
    if not root.exists():
        return []
    return [
        parse_snapshot(path)
        for path in sorted(root.glob("*.md"))
        if path.name.casefold() != "readme.md"
    ]


def cloud_status(
    snapshots: list[dict[str, Any]] | None = None,
    *,
    online: bool = False,
    reason: str | None = None,
) -> dict[str, Any]:
    snapshots = snapshots or []
    if online:
        level = "L2"
        detail = "已通过 Atlassian MCP 读取在线页面"
    elif snapshots:
        level = "L1+"
        detail = (
            f"仅有 {len(snapshots)} 份本地快照，未联网复核；"
            "快照版本可能落后于在线页"
        )
    else:
        level = "L1"
        detail = OFFLINE_NOTE
    return {
        "schema": CLOUD_SCHEMA,
        "level": level,
        "online": bool(online),
        "note": detail,
        "reason": reason,
        "snapshots": [
            {
                "page_id": item["page_id"],
                "title": item["title"],
                "version": item["version"],
                "last_modified": item["last_modified"],
                "path": item["path"],
            }
            for item in snapshots
        ],
    }


def compare_with_ladder(
    used_addresses: set[str],
    used_registers: set[str],
    snapshots: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Report addresses a snapshot names but the ladder never touches."""

    findings: list[dict[str, Any]] = []
    used_addresses = {item.upper() for item in used_addresses}
    used_registers = {item.upper() for item in used_registers}
    for snapshot in snapshots:
        missing_bits = [item for item in snapshot["addresses"] if item.upper() not in used_addresses]
        missing_regs = [item for item in snapshot["registers"] if item.upper() not in used_registers]
        if missing_bits or missing_regs:
            findings.append(
                {
                    "check": "snapshot_not_implemented",
                    "page_id": snapshot["page_id"],
                    "title": snapshot["title"],
                    "message": (
                        f"文档 {snapshot['page_id']} 提到但梯图未使用的地址："
                        + ", ".join((missing_bits + missing_regs)[:12])
                    ),
                    "addresses": missing_bits + missing_regs,
                }
            )
    return findings


def render_cloud_status(status: dict[str, Any]) -> str:
    lines = [
        "Confluence 校验状态",
        f"能力级别: {status['level']}",
        f"说明    : {status['note']}",
    ]
    if status.get("reason"):
        lines.append(f"原因    : {status['reason']}")
    if status["snapshots"]:
        lines.append("")
        lines.append("| page id | title | version | lastModified |")
        lines.append("|---|---|---|---|")
        for item in status["snapshots"]:
            lines.append(
                f"| `{item['page_id']}` | {item['title']} | "
                f"{item['version'] or '-'} | {item['last_modified'] or '-'} |"
            )
    else:
        lines.append("")
        lines.append("本地没有 Confluence 快照。")
    return "\n".join(lines) + "\n"

"""Comment coverage graded by how likely a reader is to need it.

Not every element deserves a comment.  Writing one for every internal ``A`` bit
produces noise that is worse than silence, so the policy is graded:

* ``L1``  interface points a human or another program touches: physical ``I``
  and ``O``, ``C`` commands, ``S`` states, and the ``R`` zones that HMI, macro
  or CNC also read.  These must carry a short comment.
* ``L2``  every program (and each distinct function block) needs a header comment
  naming its purpose and parameters.
* ``L3``  long explanations, only where the logic is non-obvious.  Never
  auto-required.

The report is advisory: lint surfaces a single summary line, and ``comments``
prints the full list so a human can decide what to waive.
"""

from __future__ import annotations

from typing import Any

from .model import LadDocument
from .resources import scan_document

COMMENT_SCHEMA = "syntec-lad-comments/v1"
COMMENT_POLICY = "comment-policy/v1"

L1_FAMILIES = {"I", "O", "C", "S"}
LONG_COMMENT_THRESHOLD = 60


def _l1_reason(entry: dict[str, Any]) -> str | None:
    family = entry["family"]
    if family in L1_FAMILIES:
        return {
            "I": "实体输入点，接线和现场含义必须能查到",
            "O": "实体输出点，接线和现场含义必须能查到",
            "C": "给 CNC 下命令的位，写错动作就错",
            "S": "CNC 只读状态，读者要知道这个状态代表什么",
        }[family]
    if family == "R":
        index = entry["index"]
        if 0 <= index <= 255:
            return "HMI / 参数 / 保持区寄存器，跨程序或跨设备可读"
        if index >= 8000:
            return "宏程序可读写区，语义必须和宏保持一致"
    return None


def comment_coverage(document: LadDocument) -> dict[str, Any]:
    scan = scan_document(document)
    inspection = scan["inspection"]

    missing: list[dict[str, Any]] = []
    l1_total = 0
    l1_commented = 0
    for address, entry in sorted(scan["entries"].items()):
        reason = _l1_reason(entry)
        if reason is None:
            continue
        l1_total += 1
        if entry["comment"]:
            l1_commented += 1
            continue
        missing.append(
            {
                "addr": address,
                "level": "L1",
                "reason": reason,
                "reads": entry["reads"],
                "writes": entry["writes"],
                "programs": entry["programs"],
                "networks": entry["networks"][:6],
            }
        )

    header_by_program: dict[str, bool] = {}
    for program in inspection["programs"]:
        name = str(program.get("name") or "?")
        start = int(program["record_start"])
        end = int(program["record_end"])
        # ct=1 is a main-program header; ct=3 is the subprogram variant.  Both
        # occupy a full editor row and serve the same documentation purpose.
        header_by_program[name] = any(
            block.get("type") in (1, 3)
            and start <= int(block["record_start"]) <= end
            for block in inspection["comments"]
        )
    for name, has_header in sorted(header_by_program.items()):
        if not has_header:
            missing.append(
                {
                    "addr": None,
                    "level": "L2",
                    "program": name,
                    "reason": "程序没有任何 ct=1 行注释，读的人不知道这段是干什么的",
                    "reads": 0,
                    "writes": 0,
                    "programs": [name],
                    "networks": [],
                }
            )

    long_comments = [
        block
        for block in inspection["comments"]
        if len(str(block.get("text") or "")) >= LONG_COMMENT_THRESHOLD
    ]

    coverage = (l1_commented / l1_total) if l1_total else 1.0
    return {
        "schema": COMMENT_SCHEMA,
        "policy": COMMENT_POLICY,
        "source": {
            "path": str(getattr(document, "path", "") or ""),
            "sha256": document.sha256,
            "programs": len(inspection["programs"]),
            "comments": len(inspection["comments"]),
        },
        "summary": {
            "l1_total": l1_total,
            "l1_commented": l1_commented,
            "l1_coverage": round(coverage, 4),
            "l2_programs": len(header_by_program),
            "l2_programs_with_header": sum(1 for flag in header_by_program.values() if flag),
            "long_comments": len(long_comments),
        },
        "programs": [
            {"name": name, "has_header": flag}
            for name, flag in sorted(header_by_program.items())
        ],
        "missing": missing,
        "ok": not missing,
    }


def render_comments(result: dict[str, Any], *, limit: int | None = 40) -> str:
    summary = result["summary"]
    lines = [
        "SYNTEC ladder comment coverage",
        f"File    : {result['source']['path'] or '<memory>'}",
        f"L1      : {summary['l1_commented']}/{summary['l1_total']} "
        f"({summary['l1_coverage'] * 100:.1f}% 有注释)",
        f"L2      : {summary['l2_programs_with_header']}/{summary['l2_programs']} 个程序有头注释",
        f"L3      : {summary['long_comments']} 条长注释（不强制）",
        f"Missing : {len(result['missing'])}",
    ]
    missing = result["missing"]
    if not missing:
        return "\n".join(lines) + "\n"
    lines.append("")
    shown = missing if limit is None else missing[:limit]
    grouped = {"L1": [], "L2": []}
    for item in shown:
        grouped.setdefault(item["level"], []).append(item)
    for level in ("L1", "L2"):
        items = grouped.get(level) or []
        if not items:
            continue
        lines.append(f"{level}:")
        for item in items:
            if item["addr"]:
                where = "/".join(item["programs"]) or "-"
                lines.append(
                    f"  - {item['addr']}  @{where}  R{item['reads']}/W{item['writes']}  {item['reason']}"
                )
            else:
                lines.append(f"  - 程序 {item['program']}：{item['reason']}")
        lines.append("")
    if limit is not None and len(missing) > limit:
        lines.append(f"... 还有 {len(missing) - limit} 项（用 --limit 0 看全部）")
    return "\n".join(lines)

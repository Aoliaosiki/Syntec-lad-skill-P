"""Plan-level checks that run before a ladder is compiled.

The native ``lint`` command works on a generated ``.lad``.  This module checks
the reviewed JSON plan instead, so repeated conditions are reported while the
model can still merge them into one ``actions`` array.  Conditions are
compared after DNF normalization, which ignores commutative ordering and
equivalent ``all``/``any`` nesting.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable

from .compiler import _condition_dnf, _parse_condition_node
from .errors import LadError

PLAN_LINT_SCHEMA = "syntec-lad-plan-lint/v1"

ONE_CELL_ACTIONS = {"OUT", "OUTI", "PLS", "PLF", "SET", "RST"}
FLOW_ACTIONS = {"JMP", "JSR", "MSG"}

RESOURCE_SOURCES = {"io-table", "user", "scan", "suggested"}
RESOURCE_REQUIRED_FAMILIES = {"I", "O", "C", "S"}
COIL_ACTIONS = {"OUT", "OUTI", "PLS", "PLF", "SET", "RST"}
DATA_ACTIONS = {"MOV", "ADD", "SUB", "MUL", "DIV", "AND", "OR", "XOR"}
TIMER_ACTIONS = {"TIM"}
COUNTER_ACTIONS = {"CNTUP", "CNTDOWN", "CNTRESET", "CNTRINGUP", "CNTRINGDOWN"}
ADDR_TOKEN_RE = re.compile(r"@?\b(I|O|A|C|S|TM|CT)(\d{1,4})(?:\.(\d{1,2}))?\b")
REG_TOKEN_RE = re.compile(r"@?\bR(\d{1,5})(?:\.(\d{1,2}))?\b")


def _operand_key(operand: Any) -> tuple[Any, ...] | None:
    if operand is None:
        return None
    return (operand.kind, operand.raw, operand.indirect, operand.text)


def _leaf_key(leaf: Any) -> tuple[Any, ...]:
    # ``Leaf.key`` includes the original source spelling (``I0`` vs ``I000``).
    # Use the decoded operands instead so both spellings compare equal.
    return (
        leaf.kind,
        leaf.opcode,
        leaf.width,
        _operand_key(leaf.op1),
        _operand_key(leaf.op2),
    )


def _reduce_terms(terms: Iterable[frozenset[tuple[Any, ...]]]) -> frozenset[
    frozenset[tuple[Any, ...]]
]:
    unique = set(terms)
    if frozenset() in unique:
        return frozenset({frozenset()})
    # Absorption: A OR (A AND B) is still A.
    reduced = {
        term
        for term in unique
        if not any(other < term for other in unique)
    }
    return frozenset(reduced)


def condition_signature(condition: Any) -> frozenset[frozenset[tuple[Any, ...]]]:
    """Return a commutative DNF signature for a plan condition."""

    terms = _condition_dnf(_parse_condition_node(condition))
    return _reduce_terms(
        frozenset(_leaf_key(leaf) for leaf in term) for term in terms
    )


def _condition_width(condition: Any) -> int:
    terms = _condition_dnf(_parse_condition_node(condition))
    return max((sum(leaf.width for leaf in term) for term in terms), default=0)


def _action_width(action: Any) -> int:
    if not isinstance(action, dict):
        return 2
    return 1 if str(action.get("op", "")).upper() in ONE_CELL_ACTIONS else 2


def _network_widths(network: dict[str, Any]) -> set[int]:
    actions = network.get("actions")
    if not isinstance(actions, list):
        return set()
    return {_action_width(action) for action in actions}


def _has_flow_action(network: dict[str, Any]) -> bool:
    actions = network.get("actions")
    if not isinstance(actions, list):
        return False
    return any(
        isinstance(action, dict)
        and str(action.get("op", "")).upper() in FLOW_ACTIONS
        for action in actions
    )


def _issue(
    rule: str,
    severity: str,
    detail: str,
    *,
    program: str | None,
    networks: list[str],
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "rule": rule,
        "severity": severity,
        "detail": detail,
        "program": program,
        "network": networks[-1] if networks else None,
        "networks": networks,
    }
    if extra:
        item.update(extra)
    return item


def _normalize(raw: Any) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip().replace("@", "").upper()
    if not text:
        return None
    match = REG_TOKEN_RE.fullmatch(text)
    if match:
        bit = match.group(2)
        return f"R{int(match.group(1))}" + (f".{int(bit):02d}" if bit else "")
    match = ADDR_TOKEN_RE.fullmatch(text)
    if match:
        bit = match.group(3)
        return f"{match.group(1)}{int(match.group(2))}" + (
            f".{int(bit):02d}" if bit else ""
        )
    return None


def _walk_condition(condition: Any, found: set[str]) -> None:
    if not isinstance(condition, dict):
        return
    contact = _normalize(condition.get("contact"))
    if contact:
        found.add(contact)
    compare = condition.get("compare")
    if isinstance(compare, dict):
        for key in ("value", "other"):
            address = _normalize(compare.get(key))
            if address:
                found.add(address)
    for key in ("all", "any"):
        children = condition.get(key)
        if isinstance(children, list):
            for child in children:
                _walk_condition(child, found)


def _touch(
    usage: dict[str, dict[str, Any]],
    raw: Any,
    *,
    write: bool,
    program: str,
    network: str,
) -> None:
    address = _normalize(raw)
    if not address:
        return
    entry = usage.setdefault(
        address,
        {
            "addr": address,
            "reads": 0,
            "writes": 0,
            "programs": [],
            "networks": [],
        },
    )
    if write:
        entry["writes"] += 1
    else:
        entry["reads"] += 1
    if program not in entry["programs"]:
        entry["programs"].append(program)
    if network not in entry["networks"]:
        entry["networks"].append(network)


def _collect_networks(
    networks: Any,
    program: str,
    usage: dict[str, dict[str, Any]],
) -> None:
    if not isinstance(networks, list):
        return
    for index, network in enumerate(networks, start=1):
        if not isinstance(network, dict):
            continue
        network_id = f"N{index:04d}"
        found: set[str] = set()
        _walk_condition(network.get("condition"), found)
        for address in found:
            _touch(usage, address, write=False, program=program, network=network_id)
        actions = network.get("actions")
        if not isinstance(actions, list):
            continue
        for action in actions:
            if not isinstance(action, dict):
                continue
            op = str(action.get("op") or "").upper()
            if op in COIL_ACTIONS:
                _touch(usage, action.get("operand"), write=True, program=program, network=network_id)
            elif op in TIMER_ACTIONS:
                _touch(usage, action.get("timer"), write=True, program=program, network=network_id)
                _touch(usage, action.get("preset"), write=False, program=program, network=network_id)
            elif op in COUNTER_ACTIONS:
                _touch(usage, action.get("counter"), write=True, program=program, network=network_id)
                _touch(usage, action.get("preset"), write=False, program=program, network=network_id)
            elif op in DATA_ACTIONS:
                _touch(usage, action.get("src"), write=False, program=program, network=network_id)
                _touch(usage, action.get("dst"), write=True, program=program, network=network_id)


def plan_usage(plan: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Collect every address a plan touches, with its read/write role."""

    usage: dict[str, dict[str, Any]] = {}
    programs = plan.get("programs")
    if not isinstance(programs, list):
        return usage
    for program in programs:
        if not isinstance(program, dict):
            continue
        name = str(program.get("name") or "?")
        _collect_networks(program.get("networks"), name, usage)
    return usage


def change_usage(change: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Collect addresses introduced by a ``syntec-lad-change/v1`` document."""

    usage: dict[str, dict[str, Any]] = {}
    operations = change.get("operations")
    if not isinstance(operations, list):
        return usage
    for index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            continue
        _collect_networks(operation.get("networks"), f"OP{index}", usage)
    return usage


def lint_change(
    change: dict[str, Any],
    *,
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    """Resource checks for a change document (no merge audit)."""

    issues = _resource_issues(change, change_usage(change))
    counts = {"error": 0, "warning": 0, "info": 0}
    for item in issues:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1
    operations = change.get("operations")
    return {
        "schema": PLAN_LINT_SCHEMA,
        "source": {
            "path": str(source_path) if source_path is not None else None,
            "kind": "change",
            "operations": len(operations) if isinstance(operations, list) else 0,
        },
        "summary": counts,
        "ok": counts["error"] == 0,
        "issues": issues,
    }


def _resource_required(address: str) -> bool:
    match = REG_TOKEN_RE.fullmatch(address)
    if match:
        return int(match.group(1)) <= 255
    match = ADDR_TOKEN_RE.fullmatch(address)
    if not match:
        return False
    return match.group(1) in RESOURCE_REQUIRED_FAMILIES


def _readonly_reason(address: str) -> str | None:
    match = REG_TOKEN_RE.fullmatch(address)
    if match:
        index = int(match.group(1))
        if 81 <= index <= 100:
            return "R81~R100 由系统参数 3401~3420 单向写入，阶梯程序只读"
        if 8000 <= index <= 8255:
            return "R8000~R8255 宏程序可读写，阶梯程序只读"
        return None
    match = ADDR_TOKEN_RE.fullmatch(address)
    if match and match.group(1) in {"I", "S"}:
        return f"{match.group(1)} 区在阶梯程序里只读"
    return None


def _resource_issues(
    plan: dict[str, Any],
    usage: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    resources = plan.get("resources")
    if resources is None:
        return issues
    if not isinstance(resources, list):
        return [
            _issue(
                "resources_invalid",
                "error",
                "plan.resources 必须是数组",
                program=None,
                networks=[],
            )
        ]

    declared: dict[str, dict[str, Any]] = {}
    for position, item in enumerate(resources, start=1):
        if not isinstance(item, dict):
            issues.append(
                _issue(
                    "resources_invalid",
                    "error",
                    f"resources[{position}] 不是对象",
                    program=None,
                    networks=[],
                )
            )
            continue
        address = _normalize(item.get("addr"))
        if not address:
            issues.append(
                _issue(
                    "resources_invalid",
                    "error",
                    f"resources[{position}] 的 addr 缺失或格式非法：{item.get('addr')!r}",
                    program=None,
                    networks=[],
                )
            )
            continue
        source = str(item.get("source") or "").strip()
        if source not in RESOURCE_SOURCES:
            issues.append(
                _issue(
                    "resource_source_invalid",
                    "error",
                    f"{address} 的 source={source or '<空>'} 非法，"
                    f"只能是 {'/'.join(sorted(RESOURCE_SOURCES))}",
                    program=None,
                    networks=[],
                )
            )
        elif source == "suggested":
            issues.append(
                _issue(
                    "resource_unverified",
                    "error",
                    f"{address} 仍标记为 suggested；必须由人确认后改成 user 或 io-table 才能 build",
                    program=None,
                    networks=[],
                )
            )
        if address in declared:
            issues.append(
                _issue(
                    "resource_duplicate",
                    "error",
                    f"{address} 在 resources 里重复声明",
                    program=None,
                    networks=[],
                )
            )
            continue
        declared[address] = item
        entry = usage.get(address)
        if entry and entry["writes"] > 0:
            reason = _readonly_reason(address)
            if reason:
                issues.append(
                    _issue(
                        "resource_readonly_write",
                        "error",
                        f"{address} 在 plan 里被写 {entry['writes']} 次，但 {reason}",
                        program=entry["programs"][0] if entry["programs"] else None,
                        networks=entry["networks"],
                    )
                )
        if entry is None:
            issues.append(
                _issue(
                    "resource_unused",
                    "info",
                    f"{address} 在 resources 里声明了，但没有任何 network 使用",
                    program=None,
                    networks=[],
                )
            )

    for address, entry in usage.items():
        if address in declared or not _resource_required(address):
            continue
        issues.append(
            _issue(
                "resource_missing",
                "warning",
                f"{address} 被 plan 使用，但没有写进 resources；"
                "I/O、C、S 和 R0~R255 必须显式登记来源",
                program=entry["programs"][0] if entry["programs"] else None,
                networks=entry["networks"],
            )
        )
    return issues


def lint_plan(
    plan: dict[str, Any],
    *,
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    """Audit one ``syntec-lad-plan/v1`` document for missed merges."""

    issues: list[dict[str, Any]] = []
    programs = plan.get("programs")
    if not isinstance(programs, list):
        programs = []

    for program in programs:
        if not isinstance(program, dict):
            continue
        program_name = str(program.get("name") or "?")
        networks = program.get("networks")
        if not isinstance(networks, list):
            continue

        previous: (
            tuple[
                str,
                frozenset[frozenset[tuple[Any, ...]]],
                set[int],
                int,
                bool,
            ]
            | None
        ) = None
        for index, network in enumerate(networks, start=1):
            if not isinstance(network, dict):
                continue
            network_id = f"N{index:04d}"
            widths = _network_widths(network)

            try:
                signature = condition_signature(network.get("condition"))
                condition_width = _condition_width(network.get("condition"))
            except LadError as exc:
                issues.append(
                    _issue(
                        "invalid_condition",
                        "error",
                        f"{network_id} 的条件无法规范化：{exc}",
                        program=program_name,
                        networks=[network_id],
                    )
                )
                previous = None
                continue

            action_start = 8 if 2 in widths else 9
            if len(widths) > 1 and condition_width > action_start:
                issues.append(
                    _issue(
                        "mixed_action_too_wide",
                        "info",
                        f"{network_id} 的 actions 同时含 1 格和 2 格指令，"
                        f"但条件宽 {condition_width} 列，超过第 {action_start} 列"
                        "的动作母线起点；生成器会退回逐动作布局并重复条件。"
                        "缩短串联条件，或把动作拆到不同 network",
                        program=program_name,
                        networks=[network_id],
                    )
                )

            if previous is not None:
                (
                    previous_id,
                    previous_signature,
                    previous_widths,
                    previous_width,
                    previous_flow,
                ) = previous
                if signature == previous_signature and widths and previous_widths:
                    if previous_flow or _has_flow_action(network):
                        issues.append(
                            _issue(
                                "flow_action_not_mergeable",
                                "info",
                                f"{previous_id} 与 {network_id} 条件逻辑等价，"
                                "但包含 JMP/JSR/MSG；流程指令不能与其它动作共用"
                                "动作母线，保持独立 network",
                                program=program_name,
                                networks=[previous_id, network_id],
                            )
                        )
                        previous = (
                            network_id,
                            signature,
                            widths,
                            condition_width,
                            _has_flow_action(network),
                        )
                        continue
                    action_start = (
                        8
                        if 2 in previous_widths or 2 in widths
                        else 9
                    )
                    max_width = max(previous_width, condition_width)
                    if max_width <= action_start:
                        unconditional = signature == frozenset({frozenset()})
                        suffix = "（两者都无条件）" if unconditional else ""
                        issues.append(
                            _issue(
                                "mergeable_condition",
                                "warning",
                                f"{previous_id} 与 {network_id} 的条件逻辑等价"
                                f"{suffix}；把 {network_id} 的 actions 并入 "
                                f"{previous_id}，条件只画一次",
                                program=program_name,
                                networks=[previous_id, network_id],
                            )
                        )
                    else:
                        issues.append(
                            _issue(
                                "mergeable_condition_too_wide",
                                "info",
                                f"{previous_id} 与 {network_id} 的条件逻辑等价，"
                                f"但条件宽 {max_width} 列，超过共用动作母线的"
                                f"第 {action_start} 列；合并后仍会重复条件。"
                                "保持两个 network，或缩短串联条件",
                                program=program_name,
                                networks=[previous_id, network_id],
                            )
                        )

            previous = (
                network_id,
                signature,
                widths,
                condition_width,
                _has_flow_action(network),
            )

    usage = plan_usage(plan)
    issues.extend(_resource_issues(plan, usage))

    counts = {"error": 0, "warning": 0, "info": 0}
    for item in issues:
        counts[item["severity"]] = counts.get(item["severity"], 0) + 1

    network_count = sum(
        len(program.get("networks") or [])
        for program in programs
        if isinstance(program, dict)
    )
    return {
        "schema": PLAN_LINT_SCHEMA,
        "source": {
            "path": str(source_path) if source_path is not None else None,
            "programs": len(programs),
            "networks": network_count,
        },
        "summary": counts,
        "ok": counts["error"] == 0,
        "issues": issues,
    }


def render_plan_lint(result: dict[str, Any], *, limit: int | None = None) -> str:
    source = result["source"]
    summary = result["summary"]
    lines = [
        "SYNTEC ladder plan lint",
        f"Plan    : {source['path'] or '<memory>'}",
    ]
    if source.get("kind") == "change":
        lines.append(f"Change  : {source.get('operations', 0)} operation(s)")
    else:
        lines.append(
            f"Programs: {source['programs']}  Networks: {source['networks']}"
        )
    lines.append(
        f"Result  : {'PASS' if result['ok'] else 'FAIL'}  "
        f"error {summary.get('error', 0)} / warning {summary.get('warning', 0)} / "
        f"info {summary.get('info', 0)}"
    )
    if not result["issues"]:
        return "\n".join(lines) + "\n"
    lines.append("")
    issues = result["issues"]
    shown = issues if limit is None else issues[:limit]
    for item in shown:
        where = item.get("program") or ""
        networks = item.get("networks") or []
        if networks:
            where = f"{where} {'/'.join(networks)}".strip()
        location = f"  @{where}" if where else ""
        lines.append(
            f"[{item['severity'].upper():7}] {item['rule']}: "
            f"{item['detail']}{location}"
        )
    if limit is not None and len(issues) > limit:
        lines.append(
            f"... {len(issues) - limit} more issues (use --limit 0 to show all)"
        )
    return "\n".join(lines) + "\n"

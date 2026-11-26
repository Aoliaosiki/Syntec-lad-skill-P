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
from .edition import AXIS_GENERATION
from .errors import LadError
from .registers import (
    describe_register,
    parse_register,
    register_zone,
    write_assessment,
)

PLAN_LINT_SCHEMA = "syntec-lad-plan-lint/v1"

ONE_CELL_ACTIONS = {"OUT", "OUTI", "PLS", "PLF", "SET", "RST"}
FLOW_ACTIONS = {"JMP", "JSR", "MSG"}

RESOURCE_SOURCES = {"io-table", "user", "scan", "suggested"}
RESOURCE_REQUIRED_FAMILIES = {"I", "O", "C", "S"}
COIL_ACTIONS = {"OUT", "OUTI", "PLS", "PLF", "SET", "RST"}
DATA_ACTIONS = {"MOV", "ADD", "SUB", "MUL", "DIV", "AND", "OR", "XOR"}
TIMER_ACTIONS = {"TIM"}
COUNTER_ACTIONS = {"CNTUP", "CNTDOWN", "CNTRESET", "CNTRINGUP", "CNTRINGDOWN"}
AXIS_ACTIONS = {"AXMOVE", "AXRUN", "AXSTOP"}
WAIT_M_CODES = {3, 4, 5, 6, 19, 50, 51, 52, 53}
ADDR_TOKEN_RE = re.compile(r"@?\b(I|O|A|C|S|TM|CT)(\d{1,4})(?:\.(\d{1,2}))?\b")
REG_TOKEN_RE = re.compile(r"@?\bR(\d{1,5})(?:\.(\d{1,2}))?\b")
AXIS_TOKEN_RE = re.compile(r"^AX(\d{1,5})$")
AXIS_MOVE_DATA_RE = re.compile(r"^R(\d{1,5})$")
CONST_INT_RE = re.compile(r"^#([+-]?\d{1,6})$")
PROGRAM_NAME_RE = re.compile(r"^[A-Za-z0-9]{1,6}$")
PROGRAM_TITLE_CATEGORY_RE = re.compile(r"^【[^】\r\n]{1,10}】\s*[-－–—─]\s*\S")
PROGRAM_TITLE_NUMBER_RE = re.compile(r"^\s*(?:[（(]\s*\d+\s*[)）]|\d+\s*[.、:：])")
PROGRAM_TITLE_TRAILING_NUMBER_RE = re.compile(r"[（(]\s*\d+\s*[)）]\s*$")
PROGRAM_TITLE_SENTENCE_RE = re.compile(r"[，,。；;！!？?、]")

PROGRAM_TITLE_MAX_CHARS = 20


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
    raw_text = str(raw).strip().upper()
    if raw_text.startswith("R@R"):
        raw_text = "R" + raw_text[3:]
    text = raw_text.replace("@", "")
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
            elif op == "AXMOVE":
                data = _normalize(action.get("data"))
                if data and "." not in data:
                    base = int(data[1:])
                    for offset in range(4):
                        _touch(
                            usage,
                            f"R{base + offset:04d}",
                            write=False,
                            program=program,
                            network=network_id,
                        )
            elif op == "AXRUN":
                _touch(
                    usage,
                    action.get("program"),
                    write=False,
                    program=program,
                    network=network_id,
                )


def _program_title_issues(programs: list[Any]) -> list[dict[str, Any]]:
    """Check subprogram labels and the first line of their program comment.

    MLCEdit shows the LAB name in parentheses and the leading ct=3 comment as
    the tree title.  A title like ``【刀库】-伺服刀库`` stays readable; a full
    sentence pushes every sibling out of view and belongs in the note lines.
    """

    issues: list[dict[str, Any]] = []
    for index, program in enumerate(programs):
        if index == 0 or not isinstance(program, dict):
            continue
        name = str(program.get("name") or "").strip()
        if not PROGRAM_NAME_RE.fullmatch(name):
            issues.append(
                _issue(
                    "program_name_invalid",
                    "error",
                    f"子程序名 {name or '<空>'} 非法；LAB 名只能是 1~6 位 "
                    "ASCII 字母/数字（如 1、MAG1）。中文和短标题写到 "
                    "comment 第一行，不要塞进 LAB 名",
                    program=name or None,
                    networks=[],
                )
            )

        raw = program.get("comment")
        text = str(raw).strip() if raw is not None else ""
        title = text.splitlines()[0].strip() if text else ""
        if not title:
            issues.append(
                _issue(
                    "program_title_missing",
                    "warning",
                    "子程序没有 comment 标题；MLCEdit 程序树会只显示 LAB 名。"
                    "第一行写【分类】-短主题，例如【刀库】-伺服刀库",
                    program=name or None,
                    networks=[],
                )
            )
            continue
        if len(title) > PROGRAM_TITLE_MAX_CHARS:
            issues.append(
                _issue(
                    "program_title_too_long",
                    "warning",
                    f"子程序标题 {title!r} 有 {len(title)} 个字，超过 "
                    f"{PROGRAM_TITLE_MAX_CHARS} 字；程序树只显示第一行。"
                    "把职责、触发条件、互锁和参数清单移到批注后续行或"
                    "程序体头部",
                    program=name or None,
                    networks=[],
                )
            )
        numbered = bool(PROGRAM_TITLE_NUMBER_RE.match(title)) or bool(
            PROGRAM_TITLE_TRAILING_NUMBER_RE.search(title)
        )
        if numbered:
            issues.append(
                _issue(
                    "program_title_numbered",
                    "warning",
                    f"子程序标题 {title!r} 开头或结尾自带编号；LadEditor 已在"
                    "标题后显示 (LAB 名)，编号会重复。删除 (1)、(9) 之类的序号",
                    program=name or None,
                    networks=[],
                )
            )
        if PROGRAM_TITLE_SENTENCE_RE.search(title):
            issues.append(
                _issue(
                    "program_title_sentence",
                    "warning",
                    f"子程序标题 {title!r} 含逗号、句号、分号、问号或顿号，"
                    "像一句说明而不是树上的短标签；改成名词短语，把整句"
                    "移到批注",
                    program=name or None,
                    networks=[],
                )
            )
        if not PROGRAM_TITLE_CATEGORY_RE.match(title):
            issues.append(
                _issue(
                    "program_title_without_category",
                    "warning",
                    f"子程序标题 {title!r} 没有【分类】-前缀；建议用"
                    "【外部端子】【面板功能】【系统功能】【刀库】【报警】"
                    "【M码】等分类，方便在程序树里成组查找",
                    program=name or None,
                    networks=[],
                )
            )
    return issues


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


def _axis_issues(container: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate axis operands before generation.

    The controller decides whether an axis exists, but these checks catch
    malformed plans and values that the byte format can hold but the interface
    cannot mean (program 0, a truncated AXMOVE data block, or a second AXSTOP
    operand that would be silently ignored).
    """

    issues: list[dict[str, Any]] = []
    groups: list[tuple[str, Any]] = []
    programs = container.get("programs")
    if isinstance(programs, list):
        for program in programs:
            if isinstance(program, dict):
                groups.append(
                    (str(program.get("name") or "?"), program.get("networks"))
                )
    operations = container.get("operations")
    if isinstance(operations, list):
        for index, operation in enumerate(operations, start=1):
            if isinstance(operation, dict):
                groups.append((f"OP{index}", operation.get("networks")))

    for program, networks in groups:
        if not isinstance(networks, list):
            continue
        for index, network in enumerate(networks, start=1):
            if not isinstance(network, dict):
                continue
            network_id = f"N{index:04d}"
            actions = network.get("actions")
            if not isinstance(actions, list):
                continue
            for action in actions:
                if not isinstance(action, dict):
                    continue
                op = str(action.get("op") or "").upper()
                if op not in AXIS_ACTIONS:
                    continue
                if not AXIS_GENERATION:
                    issues.append(
                        _issue(
                            "axis_not_supported",
                            "error",
                            f"{op} 在正式版被硬性禁止：正式版不生成、也不校验 "
                            "PLC 轴动作。轴运动可能导致撞机、设备损坏或人身伤害；"
                            "严禁绕过门禁、手改 .lad 或手工拼装轴记录。请停止写入，"
                            "改用 Alpha 版并先完成专项安全评审。",
                            program=program,
                            networks=[network_id],
                        )
                    )
                    continue
                axis_text = str(action.get("axis") or "").strip().upper()
                match = AXIS_TOKEN_RE.fullmatch(axis_text)
                axis_number = int(match.group(1)) if match else 0
                if not match or not 1 <= axis_number <= 65535:
                    issues.append(
                        _issue(
                            "axis_invalid",
                            "error",
                            f"{op} 的 axis={action.get('axis')!r} 非法；"
                            "必须写成 AX1..AX65535，且轴号不能为 0",
                            program=program,
                            networks=[network_id],
                        )
                    )
                if op == "AXSTOP":
                    extra = [
                        key
                        for key in ("program", "data", "operand", "src", "dst")
                        if key in action
                    ]
                    if extra:
                        issues.append(
                            _issue(
                                "axis_stop_extra_operand",
                                "error",
                                "AXSTOP 只使用轴号；第二个操作数不会被控制器读取。"
                                f"删除 {', '.join(extra)}",
                                program=program,
                                networks=[network_id],
                            )
                        )
                elif op == "AXMOVE":
                    data_text = str(action.get("data") or "").strip().upper()
                    data_match = AXIS_MOVE_DATA_RE.fullmatch(data_text)
                    if not data_match:
                        issues.append(
                            _issue(
                                "axis_move_data_invalid",
                                "error",
                                f"AXMOVE 的 data={action.get('data')!r} 必须是"
                                "直接寄存器 R0000；不接受 #常数 或 R@R 间接",
                                program=program,
                                networks=[network_id],
                            )
                        )
                    elif int(data_match.group(1)) > 65532:
                        issues.append(
                            _issue(
                                "axis_move_data_invalid",
                                "error",
                                f"AXMOVE 的 data={data_text} 需要连续 4 个寄存器，"
                                "基址最大只能是 R65532",
                                program=program,
                                networks=[network_id],
                            )
                        )
                elif op == "AXRUN":
                    raw = str(action.get("program") or "").strip()
                    if raw.startswith("#"):
                        try:
                            number = int(raw[1:])
                        except ValueError:
                            number = 0
                        if not 1 <= number <= 9999:
                            issues.append(
                                _issue(
                                    "axis_program_invalid",
                                    "error",
                                    f"AXRUN 的 program={raw!r} 必须是 #1..#9999"
                                    "（对应 O0001~O9999）",
                                    program=program,
                                    networks=[network_id],
                                )
                            )
                    elif not re.fullmatch(r"R\d{1,5}", raw.upper()):
                        issues.append(
                            _issue(
                                "axis_program_invalid",
                                "error",
                                f"AXRUN 的 program={raw!r} 必须是 #1..#9999 "
                                "或直接寄存器 R0000",
                                program=program,
                                networks=[network_id],
                            )
                        )
    return issues


def _network_groups(
    container: dict[str, Any],
) -> list[tuple[str, list[Any]]]:
    groups: list[tuple[str, list[Any]]] = []
    programs = container.get("programs")
    if isinstance(programs, list):
        for program in programs:
            if isinstance(program, dict):
                groups.append(
                    (str(program.get("name") or "?"), program.get("networks"))
                )
    operations = container.get("operations")
    if isinstance(operations, list):
        for index, operation in enumerate(operations, start=1):
            if isinstance(operation, dict):
                groups.append(
                    (f"OP{index}", operation.get("networks"))
                )
    return groups


def _axis_actions(
    container: dict[str, Any],
) -> list[tuple[str, str, dict[str, Any], int, Any]]:
    actions: list[tuple[str, str, dict[str, Any], int, Any]] = []
    for program, networks in _network_groups(container):
        if not isinstance(networks, list):
            continue
        for index, network in enumerate(networks, start=1):
            if not isinstance(network, dict):
                continue
            raw_actions = network.get("actions")
            if not isinstance(raw_actions, list):
                continue
            for action in raw_actions:
                if not isinstance(action, dict):
                    continue
                op = str(action.get("op") or "").upper()
                if op not in AXIS_ACTIONS:
                    continue
                match = AXIS_TOKEN_RE.fullmatch(
                    str(action.get("axis") or "").strip().upper()
                )
                axis_number = int(match.group(1)) if match else 0
                actions.append(
                    (
                        program,
                        f"N{index:04d}",
                        action,
                        axis_number,
                        network.get("condition"),
                    )
                )
    return actions


def _axis_usage_issues(container: dict[str, Any]) -> list[dict[str, Any]]:
    """Catch axis plans that omit the scan-level and safety scaffolding."""

    if not AXIS_GENERATION:
        return []

    issues: list[dict[str, Any]] = []
    actions = _axis_actions(container)
    move_actions = [
        item for item in actions if item[2].get("op", "").upper() in {"AXMOVE", "AXRUN"}
    ]
    has_stop = any(item[2].get("op", "").upper() == "AXSTOP" for item in actions)

    resources = container.get("resources")
    declared = {
        _normalize(item.get("addr"))
        for item in resources
        if isinstance(item, dict)
    } if isinstance(resources, list) else None

    for program, network_id, action, _axis_number, condition in actions:
        op = str(action.get("op") or "").upper()
        if condition is None or (
            isinstance(condition, dict) and condition.get("always") is True
        ):
            issues.append(
                _issue(
                    "axis_trigger_unconditional",
                    "warning",
                    f"{op} 没有明确触发条件；AX 元件的 EN 是电平，每个扫描周期"
                    "都会重新发一次命令。用单扫描脉冲或状态机的准备步触发，"
                    "不要无条件常通",
                    program=program,
                    networks=[network_id],
                )
            )

        if op == "AXMOVE":
            data_text = str(action.get("data") or "").strip().upper()
            match = re.fullmatch(r"R(\d{1,5})", data_text)
            if declared is not None and match:
                base = int(match.group(1))
                missing = [
                    f"R{base + offset}"
                    for offset in range(4)
                    if f"R{base + offset}" not in declared
                ]
                if missing:
                    issues.append(
                        _issue(
                            "axis_move_data_unregistered",
                            "warning",
                            f"AXMOVE 的 DATA={data_text} 需要连续 4 个寄存器 "
                            f"{data_text}~R{base + 3}，但 resources 没有登记 "
                            f"{', '.join(missing)}；目标/速度/模式/保留必须"
                            "逐个说明来源",
                            program=program,
                            networks=[network_id],
                        )
                    )

    if move_actions and not has_stop:
        programs = sorted({item[0] for item in move_actions})
        issues.append(
            _issue(
                "axis_stop_missing",
                "warning",
                "plan 里有 AXMOVE/AXRUN，但没有 AXSTOP。PLC 轴移动必须能在"
                "故障、急停和复位时停轴，并清除状态机；不能只靠断 EN",
                program=",".join(programs),
                networks=sorted({item[1] for item in move_actions}),
            )
        )

    issues.extend(_axis_unit_issues(container))
    issues.extend(_axis_stop_reset_issues(container))
    issues.extend(_axis_move_data_order_issues(container))
    return issues


def _register_index(value: Any) -> int | None:
    match = re.fullmatch(r"R(\d{1,5})", _normalize(value))
    if not match:
        return None
    return int(match.group(1))


def _const_int(value: Any) -> int | None:
    match = CONST_INT_RE.fullmatch(str(value or "").strip())
    if not match:
        return None
    return int(match.group(1))


def _axis_unit_issues(container: dict[str, Any]) -> list[dict[str, Any]]:
    """Require a reviewed Pr17/BLU declaration for every AX MOVE plan."""

    if not AXIS_GENERATION:
        return []
    if not any(
        str(action.get("op") or "").upper() == "AXMOVE"
        for _program, _network, action, _axis, _condition in _axis_actions(container)
    ):
        return []

    machine = container.get("machine")
    pr17 = machine.get("pr17") if isinstance(machine, dict) else None
    if pr17 in {1, 2, 3}:
        return []

    return [
        _issue(
            "axis_unit_undeclared",
            "warning",
            "plan 含 AXMOVE，但没有在顶层 machine.pr17 声明控制精度。"
            "DATA+0 的单位是 BLU，不是 mm；Pr17=1/2/3 时 1 BLU 分别是 "
            "0.01/0.001/0.0001 mm。生成前必须确认 Pr17、画面点位寄存器的"
            "实际单位（mm 或 BLU）和换算链，不能填默认值",
            program=None,
            networks=[],
        )
    ]


def _axis_stop_reset_issues(container: dict[str, Any]) -> list[dict[str, Any]]:
    """Reset may interrupt PLC-axis motion, so a reset stop must be explicit."""

    if not AXIS_GENERATION:
        return []

    issues: list[dict[str, Any]] = []
    for program, network_id, action, _axis_number, condition in _axis_actions(container):
        if str(action.get("op") or "").upper() != "AXSTOP":
            continue
        found: set[str] = set()
        _walk_condition(condition, found)
        if "C37" not in found:
            continue
        issues.append(
            _issue(
                "axis_stop_reset",
                "warning",
                "AXSTOP 的触发条件包含 C037（复位）。官方说明复位会中断"
                "执行中的 PLC 轴动作；如果流程规定换刀/上下料中复位无效，"
                "应把复位从停轴条件移除，并在流程中挡住复位。若复位确实"
                "需要停轴，必须同时定义停稳后的恢复路径",
                program=program,
                networks=[network_id],
            )
        )
    return issues


def _axis_move_data_order_issues(container: dict[str, Any]) -> list[dict[str, Any]]:
    """MoveAx must sit after the rungs that write its DATA block."""

    if not AXIS_GENERATION:
        return []

    issues: list[dict[str, Any]] = []
    programs = container.get("programs")
    if not isinstance(programs, list):
        return issues

    for program in programs:
        if not isinstance(program, dict):
            continue
        name = str(program.get("name") or "MAIN")
        networks = program.get("networks")
        if not isinstance(networks, list):
            continue

        written: dict[int, str | None] = {}
        for index, network in enumerate(networks, start=1):
            if not isinstance(network, dict):
                continue
            network_id = f"N{index:04d}"
            actions = network.get("actions")
            if not isinstance(actions, list):
                continue

            for action in actions:
                if not isinstance(action, dict):
                    continue
                op = str(action.get("op") or "").upper()
                if op in DATA_ACTIONS:
                    dst = _register_index(action.get("dst"))
                    if dst is not None:
                        written[dst] = (
                            str(action.get("src") or "").strip()
                            if op == "MOV"
                            else None
                        )
                    continue
                if op != "AXMOVE":
                    continue

                base = _register_index(action.get("data"))
                if base is None:
                    continue
                missing = [
                    f"R{base + offset}"
                    for offset in range(4)
                    if base + offset not in written
                ]
                if not missing:
                    mode = _const_int(written.get(base + 2))
                    if mode is not None and mode not in {0, 1}:
                        issues.append(
                            _issue(
                                "axis_move_mode_invalid",
                                "warning",
                                f"AXMOVE DATA={action.get('data')} 的 "
                                f"R{base + 2}（模式）由 MOV 写成 #{mode}；"
                                "官方定义为 0=增量、1=绝对。确认是写错还是"
                                "由寄存器运行时赋值",
                                program=name,
                                networks=[network_id],
                            )
                        )
                    reserved = _const_int(written.get(base + 3))
                    if reserved is not None and reserved != 0:
                        issues.append(
                            _issue(
                                "axis_move_reserved_nonzero",
                                "warning",
                                f"AXMOVE DATA={action.get('data')} 的 "
                                f"R{base + 3} 是保留寄存器，但 MOV 写成 "
                                f"#{reserved}；官方要求保留、目前无功能，"
                                "不要复用它表达模式或标志",
                                program=name,
                                networks=[network_id],
                            )
                        )
                    continue
                issues.append(
                    _issue(
                        "axis_move_data_order",
                        "warning",
                        f"AXMOVE 的 DATA={action.get('data')}：在本 program 的 "
                        f"MoveAx 之前没有找到写 {', '.join(missing)} 的支路。"
                        "官方要求 MoveAx 必须排在设定内容之后，否则会用到旧值；"
                        "若 DATA 由子程序、宏或上位机写入，请人工确认扫描顺序",
                        program=name,
                        networks=[network_id],
                    )
                )
    return issues


def _walk_m_compare(condition: Any, found: set[int]) -> None:
    if not isinstance(condition, dict):
        return
    compare = condition.get("compare")
    if isinstance(compare, dict):
        relation = str(compare.get("relation") or "=").strip()
        if relation in {"=", "==", "EQ"}:
            left = _normalize(compare.get("value"))
            right = str(compare.get("other") or "").strip()
            if left == "R1" and right.startswith("#"):
                try:
                    found.add(int(right[1:]))
                except ValueError:
                    pass
            right_addr = _normalize(compare.get("other"))
            left_text = str(compare.get("value") or "").strip()
            if right_addr == "R1" and left_text.startswith("#"):
                try:
                    found.add(int(left_text[1:]))
                except ValueError:
                    pass
    for key in ("all", "any"):
        children = condition.get(key)
        if isinstance(children, list):
            for child in children:
                _walk_m_compare(child, found)


def _mcode_decode_issues(container: dict[str, Any]) -> list[dict[str, Any]]:
    """Every R1 M-code compare must be gated by S029 in the same network."""

    issues: list[dict[str, Any]] = []
    for program, networks in _network_groups(container):
        if not isinstance(networks, list):
            continue
        for index, network in enumerate(networks, start=1):
            if not isinstance(network, dict):
                continue
            condition = network.get("condition")
            codes: set[int] = set()
            _walk_m_compare(condition, codes)
            if not codes:
                continue
            found: set[str] = set()
            _walk_condition(condition, found)
            if "S29" in found:
                continue
            formatted = ", ".join(f"M{code:02d}" for code in sorted(codes))
            issues.append(
                _issue(
                    "mcode_decode_without_s029",
                    "warning",
                    f"网络解码 {formatted} 时没有串 S029（M 码读取旗标）。"
                    "R1 只在 S029 有效时代表当前 M 码；只比较 R1 会在"
                    "其他 M 码或旧值上误动作。画面上确认是否另有一层"
                    "总允许，否则把 S029 串进解码条件",
                    program=program,
                    networks=[f"N{index:04d}"],
                )
            )
    return issues


def _mcode_issues(
    container: dict[str, Any],
    usage: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    issues = _mcode_decode_issues(container)
    wait_found: set[int] = set()
    for _program, networks in _network_groups(container):
        if not isinstance(networks, list):
            continue
        for network in networks:
            if isinstance(network, dict):
                _walk_m_compare(network.get("condition"), wait_found)
    wait_found &= WAIT_M_CODES
    if not wait_found:
        return issues
    if usage.get("C38", {}).get("writes", 0) > 0:
        return issues
    codes = ", ".join(f"M{code:02d}" for code in sorted(wait_found))
    issues.append(
        _issue(
            "mcode_wait_without_c38",
            "warning",
            f"plan 解碼了等待型 M 码 {codes}，但没有任何 C38 写入。等待型 "
            "M 码必须在执行期间把 C38 拉低，完成条件满足后再恢复 ON；"
            "否则 CNC 会一直停在当前单节。非等待型 M 码（如冷却水）"
            "才不需要处理 C38",
            program=None,
            networks=[],
        )
    )
    return issues


def lint_change(
    change: dict[str, Any],
    *,
    source_path: str | Path | None = None,
) -> dict[str, Any]:
    """Axis and resource checks for a change document (no merge audit)."""

    issues = _axis_issues(change) + _resource_issues(change, change_usage(change))
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
        index = int(match.group(1))
        if index <= 255:
            return True
        zone = register_zone(index)
        return bool(zone and zone.get("owner") == "user_conditional")
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


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().casefold()
        if text in {"true", "yes", "1"}:
            return True
        if text in {"false", "no", "0"}:
            return False
    return None


def _conditional_note_ok(index: int, note: str) -> bool:
    zone = register_zone(index)
    if zone is None or zone.get("owner") != "user_conditional":
        return True
    zone_id = str(zone.get("id") or "")
    if zone_id == "R2050-R2090":
        return "3810" in note
    if zone_id == "R2100-R3100":
        return "3228" in note
    if zone_id == "R1024-R1032":
        return any(
            word in note
            for word in ("车床", "铣床", "分中", "对刀", "lathe", "mill")
        )
    return True


def _resource_issues(
    plan: dict[str, Any],
    usage: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    resources = plan.get("resources")
    has_resources = resources is not None
    if has_resources and not isinstance(resources, list):
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
    resource_items = resources if isinstance(resources, list) else []
    for position, item in enumerate(resource_items, start=1):
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
        parsed = parse_register(address)
        if parsed is not None:
            index, _bit = parsed
            zone = register_zone(index)
            declared_retain = _as_bool(item.get("retain"))
            zone_retain = zone.get("retain") if zone else None
            if declared_retain is True and zone_retain is False:
                issues.append(
                    _issue(
                        "r_retain_mismatch",
                        "error",
                        f"{address} 标记 retain=true，但 {zone.get('name')} 掉电不保持；"
                        "需要保持的数值请改用 R103~R255、R6000~R7999 或 R10000~R10999",
                        program=None,
                        networks=[],
                    )
                )
            elif declared_retain is False and zone_retain is True:
                issues.append(
                    _issue(
                        "r_retain_mismatch",
                        "warning",
                        f"{address} 标记 retain=false，但 {zone.get('name')} 实际掉电保持；"
                        "若依赖断电清零，需要在上电时显式初始化",
                        program=None,
                        networks=[],
                    )
                )
            if zone and zone.get("owner") == "user_conditional":
                note = str(item.get("note") or "")
                if not _conditional_note_ok(index, note):
                    issues.append(
                        _issue(
                            "r_conditional_zone",
                            "warning",
                            f"{address} 位于条件占用区 {zone.get('name')}；"
                            "plan.resources 的 note 必须写明启用条件"
                            "（R2050~R2090 查 Pr3810，R2100~R3100 查 Pr3228）",
                            program=None,
                            networks=[],
                        )
                    )
        entry = usage.get(address)
        if entry is None and has_resources:
            issues.append(
                _issue(
                    "resource_unused",
                    "info",
                    f"{address} 在 resources 里声明了，但没有任何 network 使用",
                    program=None,
                    networks=[],
                )
            )

    declared_bits: dict[int, list[str]] = {}
    for address in declared:
        parsed = parse_register(address)
        if parsed is None:
            continue
        index, bit = parsed
        if bit is not None:
            declared_bits.setdefault(index, []).append(address)

    for address, entry in usage.items():
        parsed = parse_register(address)
        if parsed is None or entry["writes"] <= 0:
            continue
        index, bit = parsed
        if bit is not None or index not in declared_bits:
            continue
        issues.append(
            _issue(
                "register_bitwise_overwrite",
                "warning",
                f"{address} 被整字写入 {entry['writes']} 次，但同一计划还"
                f"登记了位地址 {', '.join(sorted(declared_bits[index]))}。"
                "整字 MOV/ADD/SUB 会覆盖同一位域；先做位级占用扫描，"
                "确认这些位是否由按键旗标、宏或别的功能占用",
                program=entry["programs"][0] if entry["programs"] else None,
                networks=entry["networks"],
            )
        )

    checked_bit: set[str] = set()
    for address, entry in usage.items():
        parsed = parse_register(address)
        if parsed is not None:
            index, bit = parsed
            if bit is not None and address not in checked_bit:
                info = describe_register(address)
                if info is not None and not info["bit_access"]:
                    checked_bit.add(address)
                    issues.append(
                        _issue(
                            "r_bit_access_invalid",
                            "error",
                            info["bit_note"]
                            or f"{address} 所在区不支持位存取",
                            program=entry["programs"][0] if entry["programs"] else None,
                            networks=entry["networks"],
                        )
                    )
            if entry["writes"] > 0:
                assessment = write_assessment(address)
                if assessment["severity"] == "error":
                    issues.append(
                        _issue(
                            "resource_readonly_write",
                            "error",
                            f"{address} 在 plan 里被写 {entry['writes']} 次，但 "
                            f"{assessment['detail']}",
                            program=entry["programs"][0] if entry["programs"] else None,
                            networks=entry["networks"],
                        )
                    )
                elif assessment["severity"] == "warning":
                    zone = register_zone(index) or {}
                    if zone.get("owner") == "user_conditional":
                        if address not in declared:
                            issues.append(
                                _issue(
                                    "r_conditional_zone",
                                    "warning",
                                    f"{address} 位于条件占用区 {zone.get('name')}，"
                                    "但没有登记启用条件；先写进 plan.resources 并注明"
                                    "Pr3810 / Pr3228 / 机型",
                                    program=entry["programs"][0] if entry["programs"] else None,
                                    networks=entry["networks"],
                                )
                            )
                    else:
                        issues.append(
                            _issue(
                                "r_system_write",
                                "warning",
                                f"{address} 在 plan 里被写 {entry['writes']} 次；"
                                f"{assessment['detail']}",
                                program=entry["programs"][0] if entry["programs"] else None,
                                networks=entry["networks"],
                            )
                        )
        elif entry["writes"] > 0:
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
        if address in declared or not _resource_required(address):
            continue
        if not has_resources:
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

    issues.extend(_program_title_issues(programs))

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
    issues.extend(_axis_issues(plan))
    issues.extend(_axis_usage_issues(plan))
    issues.extend(_mcode_issues(plan, usage))
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

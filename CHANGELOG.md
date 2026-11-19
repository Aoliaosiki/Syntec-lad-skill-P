# Changelog

## 0.3.0p - 2026-11-19

首个公开预览版（Public Preview）。内容 = 0.2.2 的基础上合入全部 0.2.3 修复，
并把版本号、打包与文档对齐到可独立发布的形态。

### Added

- 独立分发包 `downloads/syntec-lad-skill-0.3.0p.zip`，附
  `downloads/syntec-lad-skill-0.3.0p.zip.sha256` 校验文件。
- `README.md` 新增「与原版差异」「来源与授权」两节，说明本仓库是
  `LipsLee/syntec-lad-skill` 的衍生版本。
- `README.md` 增加 CodeBuddy 安装路径（`~/.codebuddy/skills/syntec-lad/`）。
- `.gitignore` 覆盖 `work/`、`*.inspect.json`、`__pycache__/` 等本地产物。

### Changed

- 版本号统一为 `0.3.0p`（CLI `--version`、MCP `serverInfo`、README、ZIP）。
  `pyproject.toml` 保持 PEP 440 合法的 `0.3.0`。
- `README.md` 的 `diff` 说明由「按记录和指令单元比较」改为段对齐描述。

### Fixed

（继承 0.2.3，见下）

## 0.2.3 - 2026-11-10

### Fixed

- Native syntax check: ordinal `#124` (`GetSyntaxErrType`) is now optional.
  Some LadDLL builds export only 23 ordinal functions and lack `#124`, which
  made every native validation fail before the syntax gate even ran. The
  helper now reports `error_type=-1` when the export is missing.
  (`native/LadSyntaxCheck.cs`, rebuilt `native/bin/LadSyntaxCheck.exe`.)
- `diff` was rewritten as segment-aligned diff (`syntec-lad-diff/v2`). The
  legacy diff compared records by list index, so one inserted record cascaded
  into thousands of false differences. It now aligns comment blocks, network
  candidates, and structural records by content hash (LCS via
  `difflib.SequenceMatcher`), classifies them as unchanged / modified / added
  / removed / moved, and reports modified networks with instruction previews
  and 4-byte cell deltas instead of raw hex dumps.

### Added

- `inspect --program NAME` / `inspect --network Nxxxx` (and MCP `inspect_lad`
  `program` / `network` arguments) to scope the output to one program or one
  network candidate instead of dumping the whole file.
- `tests/test_patch.py` and `tests/test_native_safety.py` accept a
  `SYNTEC_LAD_SAMPLE` environment variable pointing at a real `cnc.lad`;
  previously the sample path was hardcoded to the author's machine.
- `SKILL.md` documents CodeBuddy (`~/.codebuddy/skills/syntec-lad/`) as a
  first-class host alongside Codex and WorkBuddy.

### Tests

- `python -m unittest discover -s tests` with `SYNTEC_LAD_SAMPLE` pointing at
  a real 119 KB `cnc.lad` (big5, 2991 records) and a 32-bit `LadDLL.dll`:
  65 tests passed, 2 skipped (native fixtures unavailable outside Windows).
- Real-file diff verification: 1026 revision vs 1109 revision now reports
  `unchanged 1708 / modified 5 / added 2` where the legacy diff reported 2893
  cascading position changes.

## 0.2.2 - 2026-11-09

### Fixed

- WorkBuddy Skill backups now live under `~/.workbuddy/skills-backups/`
  instead of inside the scanned `skills/` directory, preventing a backup from
  appearing as a duplicate skill.

### Tests

- 65 tests passed, including the WorkBuddy backup-location regression test.

## 0.2.1 - 2026-11-09

### Fixed

- Documented the WorkBuddy 5.9.3 MCP Servers flow and verified that
  `~/.workbuddy/mcp.json` is read as a stdio server configuration.

## 0.2.0 - 2026-11-09

### Added

- MIT-licensed engineering knowledge snapshot from
  `panming/syntec-plc-ladder` under `references/panming/`.
- 602-address C/S/R index in Markdown and CSV form.
- `syntec-lad lookup <address|keyword>` for the bundled address index.
- Dependency-free MCP stdio adapter for WorkBuddy, Claude Desktop, Cursor,
  and other MCP clients.
- WorkBuddy/Agent Skills installer with backup and self-check behavior.
- Address notation adapter for short upstream forms and SDK canonical forms.
- Knowledge routing, source hierarchy, and upstream attribution notices.
- Expanded `SKILL.md` workflow covering address classes, process patterns,
  field conventions, comments, validation, and critical anti-patterns.

### Preserved

- Native `.lad` parsing, deterministic JSON plans, hash-pinned patches,
  remapping, Python readback, and the native `LadDLL.SyntaxCheck` gate.
- Byte-for-byte preservation of unknown records and the existing safety
  boundaries.

### Tests

- `python -m unittest discover -s tests -v`
- 64 tests passed, including native validation and MCP tests.

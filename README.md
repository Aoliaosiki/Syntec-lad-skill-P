# Syntec Ladder SDK / Codex Skill + 工程知识库（0.3.0p 优化版）

> ## 本仓库是原版的优化版
>
> **原版（上游）**：[`LipsLee/syntec-lad-skill`](https://github.com/LipsLee/syntec-lad-skill) v0.2.2
> **本仓库**：[`Aoliaosiki/Syntec-lad-skill-P`](https://github.com/Aoliaosiki/Syntec-lad-skill-P) v0.3.0p
>
> 相对原版的主要优化：
>
> 1. **`diff` 重写为段对齐**——原版按记录下标硬对齐，插入一条记录后其后全部错位；
> 2. **修复原生 LadDLL 校验**——原版硬编码导出序号 `#124`，部分 `LadDLL.dll` 缺该导出会导致每次 `validate` 失败；
> 3. **测试可移植**——原版样本路径与记录号写死在作者机器上；
> 4. **`inspect` 支持 `--program` / `--network` 范围过滤**——原版只能全量输出。
>
> 详细对照见 [与原版（0.2.2）的差异](#与原版022的差异)，逐条记录见 [CHANGELOG.md](CHANGELOG.md)。
> 上游项目本体未声明 LICENSE，`references/panming/` 知识快照为 MIT，商用/再分发前请与上游作者确认。

一个无第三方 Python 依赖的 Syntec LadEditor 2.37.0 梯形图 SDK、CLI 和
Codex / CodeBuddy Skill。它直接读写原生 `.lad` 记录，可检查程序结构、根据审阅过的
JSON 计划生成新梯形图、按哈希锁定的记录范围修补现有文件、批量重映射
PLC 位地址，并调用原厂 32 位 `LadDLL.dll` 做语法校验。Skill 同时内置
新代 PLC 工程知识库：8 类元件、C/S/R 地址表、602 条地址索引、12 个工艺
模式，以及润滑/液压/排屑/刀库/M 码写法库。

本工具不会点击 LadEditor 界面，不会自动上传 CNC，也不会直接修改控制器上
的 PLC。当前可写范围仅限本地原生 `.lad` 文件。

## 目录

- [功能](#功能)
- [与原版（0.2.2）的差异](#与原版022的差异)
- [工程知识库](#工程知识库)
- [环境要求](#环境要求)
- [安装](#安装)
- [其他 Agent / WorkBuddy](#其他-agent--workbuddy)
- [直接使用 CLI](#直接使用-cli)
- [快速开始](#快速开始)
- [安全边界](#安全边界)
- [测试](#测试)
- [常见问题](#常见问题)
- [目录结构](#目录结构)
- [第三方知识](#第三方知识)
- [来源与授权](#来源与授权)

## 功能

- `inspect`：查看编码、SHA256、程序边界、物理记录、注释和网络候选。
- `build`：从 `syntec-lad-plan/v1` 生成主程序、普通子程序、触点、线圈、
  定时器、计数器、比较、数据传送和跳转/调用。
- `patch`：用 `syntec-lad-change/v1` 对哈希锁定的记录范围做插入、替换、
  删除；过期哈希、跨网络边界和结构行会被拒绝。
- `remap`：同时替换 I/O、C/S/A 位和 R 寄存器位，避免级联误替换。
- `lookup`：查询内置 602 条 C/S/R 地址索引，支持地址精确查询和关键词搜索。
- `validate`：Python 回读校验，并在可用时调用原厂 LadDLL 语法检查。
- `diff`：按注释块 / 网络 / 结构记录做段对齐比较，输出未变、修改、新增、
  删除、移动五类结果，带指令预览和 4 字节单元差异（不再按记录下标硬对齐）。
- `open`：仅启动 `MLCEdit.exe -f <file>` 供人工复核。

## 与原版（0.2.2）的差异

本仓库是 [`LipsLee/syntec-lad-skill`](https://github.com/LipsLee/syntec-lad-skill)
的衍生版本，0.3.0p 在保留原有解析 / 生成 / 补丁 / 重映射内核和安全边界的前提下，
做了四项针对性改动：

| 项 | 原版 0.2.2 | 本版 0.3.0p |
| --- | --- | --- |
| `diff` | 按记录下标硬对齐，插入一条记录后其后全部错位（实测两版真实 `cnc.lad` 报 2893 处差异） | 段对齐（`syntec-lad-diff/v2`），同样两版文件报「未变 1708 / 修改 5 / 新增 2」，带指令预览与单元差异 |
| 原生校验 | 硬编码导出序号 `#124`，缺少该导出的 `LadDLL.dll` 会导致每次 `validate` 失败 | `#124` 改为可选，缺失时 `error_type=-1`，语法门禁正常运行 |
| 测试 | 真实样本路径与若干记录号写死在作者机器上，换文件必挂 | 动态定位网络 / 结构记录，样本路径支持 `SYNTEC_LAD_SAMPLE` 环境变量 |
| `inspect` | 只能全量输出（120 KB 文件约 11 MB JSON） | 新增 `--program` / `--network` 过滤，MCP `inspect_lad` 同步支持 |

新增 `syntec_lad/lad_diff.py`；CLI、MCP 的接口与既有 JSON Schema 保持兼容。

## 工程知识库

`references/panming/` 是从 MIT 许可的
[`panming/syntec-plc-ladder`](https://github.com/panming/syntec-plc-ladder)
项目整理的工程知识快照，保留原文和来源标记。内容包括：

- 8 类元件分工、C/S 全表、R 寄存器分配和常见误用。
- 602 条 C/S/R 地址反向索引，可浏览 Markdown/CSV 或使用 CLI 查询。
- 12 个真机工艺模式：启保停、自动/手动、报警锁存、定时循环、互锁、
  模拟量回差、上电初始化等。
- 润滑、液压、排屑/冷却、刀库/刀塔、M 码五类功能写法库。
- 现场约定、三层注释、批注编码、R512~R1023 权限表和 `.lad` 技术附录。

知识层用于选结构和查地址；真正的写入仍必须走 `inspect` → JSON 计划/变更
→ `build`/`patch` → Python 回读 + LadDLL 原生校验。上游 `validate` 只作
提示，不能替代本项目的原生校验。

上游示例里的 `add_rung` 元件对象不是本项目的 JSON Schema；迁移时要转成
`syntec-lad-plan/v1` 或 `syntec-lad-change/v1`，以 `syntec_lad/schema/`
下的 Schema 为准。

知识入口：

- `references/knowledge-map.md`：按任务选择参考资料。
- `references/address-notation.md`：短地址与 SDK 规范地址的转换。
- `references/panming/README.md`：上游来源、许可证和文件清单。

融合时保留本项目的原生 SDK/CLI、哈希锁定补丁和 LadDLL 硬校验。新增的
MCP 适配器和 WorkBuddy 安装器按本项目接口自行实现，没有复制上游服务端；
上游的 `validate` 只作提示，不作为本项目的交付门。

## 环境要求

- Windows 10/11（原生校验和 `open` 必需；纯解析/生成可在其他系统运行）。
- Python 3.10 或更高版本，无第三方 Python 依赖。
- 原厂校验：32 位 `LadDLL.dll`、.NET Framework 4.x、可用的 `csc.exe`。
- 人工复核：`MLCEdit.exe`。

如果 LadEditor 不在默认位置，先设置：

```powershell
$env:SYNTEC_LAD_DLL = 'C:\path\to\LadEditor\LadDLL.dll'
$env:SYNTEC_LAD_EDITOR = 'C:\path\to\LadEditor\MLCEdit.exe'
```

## 安装

克隆到对应 Agent 的 skills 目录即可，目录名保持 `syntec-lad`：

```powershell
# CodeBuddy
$target = Join-Path $HOME '.codebuddy\skills\syntec-lad'
# Codex
# $target = Join-Path $HOME '.codex\skills\syntec-lad'
# WorkBuddy（也可用下面的 install_workbuddy.py）
# $target = Join-Path $HOME '.workbuddy\skills\syntec-lad'

New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
git clone https://github.com/Aoliaosiki/Syntec-lad-skill-P.git $target
```

刷新 / 重启客户端后即可调用（Codex 中显式写 `$syntec-lad`）。

也可以下载 ZIP 解压，把文件夹命名为 `syntec-lad` 放入上述目录：

- 直链：
  <https://raw.githubusercontent.com/Aoliaosiki/Syntec-lad-skill-P/main/downloads/syntec-lad-skill-0.3.0p.zip>
- jsDelivr 加速：
  <https://cdn.jsdelivr.net/gh/Aoliaosiki/Syntec-lad-skill-P@main/downloads/syntec-lad-skill-0.3.0p.zip>
- SHA256：见 `downloads/syntec-lad-skill-0.3.0p.zip.sha256`

Skill 自带启动器，不要求安装 Python 包：

```powershell
$LadCli = Join-Path $HOME '.codebuddy\skills\syntec-lad\scripts\run_syntec_lad.py'
python $LadCli --help
```

## 其他 Agent / WorkBuddy

SDK 本身不绑定 Codex。任何能运行 Python 的 Agent 都可以直接调用
`scripts/run_syntec_lad.py`；支持 MCP 的 Agent 可以注册
`scripts/syntec_lad_mcp.py`。

### WorkBuddy 一键安装

```powershell
python .\scripts\install_workbuddy.py
```

或双击 `scripts\install_workbuddy.bat`。安装器会：

- 把 Skill 复制到 `~/.workbuddy/skills/syntec-lad/`
- 合并写入 `~/.workbuddy/mcp.json` 的 `syntec-lad` 服务
- 安装前备份旧 Skill 目录和旧 MCP 配置（Skill 备份放在扫描目录之外）
- 先跑 CLI/MCP 自检，再改动文件

安装后完全退出 WorkBuddy，重新打开，在“MCP 服务器”页面确认
`syntec-lad` 已出现；若提示授权或信任，点允许。

### 其他 MCP 客户端

Claude Desktop、Cursor 等客户端可使用 `mcp-config.example.json`，把路径
改成实际位置即可。MCP 工具包括 `inspect_lad`、`lookup_address`、
`build_plan`、`patch_lad`、`validate_lad`、`diff_lad`、`read_reference`、
`list_references`、`explain_capabilities`。

跨 Agent 的完整说明见 `PORTABLE.md`。原生 LadDLL 校验仍只支持 Windows +
32 位 `LadDLL.dll` + .NET Framework 4.x。

## 直接使用 CLI

在仓库根目录执行：

```powershell
python -m pip install -e .
syntec-lad --version
```

或完全不安装：

```powershell
python .\scripts\run_syntec_lad.py --help
```

## 快速开始

```powershell
python $LadCli inspect .\file.lad
python $LadCli lookup C6
python $LadCli lookup "M码"
python $LadCli build .\plan.json .\new.lad
python $LadCli validate .\new.lad
python $LadCli diff .\file.lad .\new.lad
python $LadCli open .\new.lad
```

修补现有文件前，先取得目标记录范围和哈希：

```powershell
python $LadCli inspect .\source.lad --json --output .\source.inspect.json
python $LadCli patch .\source.lad .\change.json .\patched.lad
```

只有用户明确要求覆盖时才使用 `--in-place`。SDK 会创建带时间戳的 `.bak`，
并在同名 `.LC` 侧车文件存在时先备份 `.LC`。

### Plan 示例

完整 Schema 位于 `syntec_lad/schema/lad-plan.schema.json`。

```json
{
  "schema": "syntec-lad-plan/v1",
  "encoding": "gb2312",
  "programs": [
    {
      "name": "MAIN",
      "networks": [
        {
          "comment": "启动、停止与自锁",
          "condition": {
            "all": [
              {"contact": "I000"},
              {"any": [{"contact": "I001", "normally": "closed"}, {"contact": "O000"}]}
            ]
          },
          "actions": [{"op": "OUT", "operand": "O000"}]
        }
      ]
    }
  ]
}
```

以上 I/O 地址只是格式示例，不能直接用于真实设备。

### Change 示例

完整 Schema 位于 `syntec_lad/schema/lad-change.schema.json`。

```json
{
  "schema": "syntec-lad-change/v1",
  "base_sha256": "<inspect 输出的 source.sha256>",
  "operations": [
    {
      "op": "replace",
      "record_start": 19,
      "record_end": 26,
      "expected_sha256": "<对应 network candidate 的 sha256>",
      "networks": [
        {
          "condition": {"contact": "I010"},
          "actions": [{"op": "OUT", "operand": "O010"}]
        }
      ]
    }
  ]
}
```

## 安全边界

- 原生 `.lad` 是唯一可写源格式；`.il`、PDF、BMP 和截图不能作为生成输入。
- 不自行分配 I/O、寄存器、定时器、计数器、预置值或联锁关系。
- 不生成新的轴、RS232、Keyscan、文件系统、外部功能、Coord/Tool 或
  FastPLC 记录。
- 未知或高级记录必须逐字节保留。
- `build`/`patch` 默认同时执行 Python 回读和 LadDLL 原生校验；任一失败
  都不应覆盖目标文件。
- `open` 仅用于人工复核，不把编辑器打开成功当作语法通过。

## 测试

```powershell
python -m unittest discover -s tests -v
```

测试覆盖记录编解码、并/串联与嵌套网络、定时/计数/比较/数据传送/子程序、
哈希锁定补丁、同步重映射、原子写入、真实 `cnc.lad` 往返，以及可用的
LadDLL 原生校验。真实 `cnc.lad` 路径不存在时会自动跳过该样本测试。

要跑真实样本相关用例，指定样本路径与 DLL 即可：

```powershell
$env:SYNTEC_LAD_SAMPLE = 'D:\path\to\cnc.lad'
$env:SYNTEC_LAD_DLL    = 'C:\path\to\LadEditor\LadDLL.dll'
python -m unittest discover -s tests -v
```

## 常见问题

**`validate` 提示原生校验无法运行？**
设置 `SYNTEC_LAD_DLL` 指向 32 位 `LadDLL.dll`。本版已兼容缺少导出序号
`#124` 的 DLL 版本（原版会直接失败）。没有 DLL 时 `inspect` / `diff` /
`build` / `patch` 仍可正常使用，只是跳过原生语法门。

**中文注释显示成乱码？**
`.lad` 内的注释是 cp950/Big5 或 gb2312 编码，`inspect` 会自动探测。
写入时注释必须是编辑器兼容的繁体（cp950），简体中文可能显示为问号。

**把目录放进 skills 后 Agent 没反应？**
目录名必须是 `syntec-lad`，且 `SKILL.md` 位于该目录根层，然后重启或刷新
客户端。

**`diff` 输出几千处改动？**
那是原版按下标硬对齐的表现。本版按注释块/网络/结构记录做段对齐，只报告
真实的新增/修改/删除/移动；若仍异常，请附 `--json` 输出以便定位。

**能直接改 CNC 或操作编辑器界面吗？**
不能。本工具只处理本地 `.lad` 文件，不点击界面、不上传控制器。

## 目录结构

```text
SKILL.md                   Codex Skill 入口与强制安全流程
CHANGELOG.md               版本变更记录
THIRD_PARTY_NOTICES.md     第三方知识与 MIT 许可声明
PORTABLE.md                Codex / WorkBuddy / MCP 通用接入说明
mcp-config.example.json    MCP 客户端配置示例
agents/openai.yaml         Skill 展示信息
scripts/run_syntec_lad.py  免安装启动器
scripts/syntec_lad_mcp.py  MCP stdio 适配器
scripts/install_workbuddy.py  WorkBuddy 安装器
syntec_lad/                Python SDK、CLI 和 JSON Schema
native/                    x86 LadDLL 校验辅助程序源码
tools/lad_parser.py        独立的旧版解析/反汇编交叉检查器
references/                原生工作流与工程知识库
references/panming/        上游 MIT 知识快照（地址、模式、功能库）
examples/                  格式示例与回归夹具
tests/                     unittest 测试
```

## 第三方知识

`references/panming/` 的材料来自 `panming/syntec-plc-ladder`，提交
`29cde41df688055f11fb7b33a5db782b92c7e4d7`，MIT 许可，
版权归 `syntec-plc-ladder contributors`。再分发时请保留
`references/panming/LICENSE` 和 `THIRD_PARTY_NOTICES.md`。

## 来源与授权

- 上游项目：[`LipsLee/syntec-lad-skill`](https://github.com/LipsLee/syntec-lad-skill)
  （0.2.2）。本仓库在其基础上合入上述改动。
- 上游项目本体未声明 LICENSE，`references/panming/` 的知识快照为 MIT。
  如需商用或再分发，请先与上游作者确认授权范围。
- 本工具仅用于对自有或已获授权设备的离线梯形图分析与生成；不点击编辑器
  界面、不上传 CNC、不修改控制器。

版本：`0.3.0p`

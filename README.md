# Syntec Ladder SDK / Codex Skill + 工程知识库（0.3.9p）

[![Version](https://img.shields.io/badge/version-0.3.9p-blue)](CHANGELOG.md)
[![Python](https://img.shields.io/badge/python-3.10%2B-green)](pyproject.toml)
[![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)](README.md)

一个无第三方 Python 依赖的 **Syntec LadEditor 2.37.0 梯形图 SDK、CLI、MCP 工具和 Agent Skill**。

- 直接读写原生 `.lad` 记录，不依赖编辑器 GUI。
- 用审阅过的 JSON 计划生成新梯形图，或用哈希锁定的变更修补现有文件。
- 批量重映射 PLC 位地址，避免级联误替换。
- 调用原厂 32 位 `LadDLL.dll` 做原生语法校验。
- 内置新代 PLC 工程知识库：8 类元件、C/S/R 地址表、R 分区与权限/保持/
  位存取、`@` 公用变量到 R 的分段映射与 `R@R` 间接寻址、602 条地址索引、12 个工艺模式，
  以及润滑/液压/排屑/刀库写法库、`S29/R1/C38` 标准 M 码握手。

> **本仓库是 [`LipsLee/syntec-lad-skill`](https://github.com/LipsLee/syntec-lad-skill) v0.2.2 的优化版。**
> 当前版本：`0.3.9p`（正式版），仓库：
> [`Aoliaosiki/Syntec-lad-skill-P`](https://github.com/Aoliaosiki/Syntec-lad-skill-P)。
> 本工具不会点击 LadEditor 界面，不会上传 CNC，也不会直接修改控制器。

## 目录

- [0.3.9p 重点](#039p-重点)
- [0.3.8p 重点](#038p-重点)
- [0.3.7p 重点](#037p-重点)
- [0.3.6p 重点](#036p-重点)
- [功能总览](#功能总览)
- [安全边界](#安全边界)
- [环境要求与原生校验](#环境要求与原生校验)
- [安装](#安装)
- [快速开始](#快速开始)
- [命令参考](#命令参考)
- [Plan Schema](#plan-schema)
- [Change Schema](#change-schema)
- [Python SDK](#python-sdk)
- [MCP 与其他 Agent](#mcp-与其他-agent)
- [工程知识库](#工程知识库)
- [备份目录识别](#备份目录识别)
- [测试与当前验证结果](#测试与当前验证结果)
- [常见问题](#常见问题)
- [目录结构](#目录结构)
- [版本与授权](#版本与授权)

## 0.3.9p 重点

### M 码：S29 读入、R1 取号、C38 放行

M 码不是只写一条 `CMPE #50 R1 -> OUT A150`。标准链路是：

- `S029` 为 ON 时才解码 M 码，M 号从 `R1` 读取；
- 每个 M 码一个独立请求位，不要把所有 M 码塞进一个大 rung；
- `C038` 是 M/S/T 完成信号，**常态 ON**；
- 等待型 M 码（M03/M04/M05/M19/M50/M51 等）执行期间必须把 `C38` 拉低，
  实际完成条件满足后再恢复 ON；
- 非等待型 M 码（M07/M08/M09 等）不处理 `C38`，但仍要有急停、复位和互锁；
- 只要该 M 码在加工档的任何位置需要等待 G 码完成，解码条件就要串
  `S030`（分布结束）；M05/M19 是最常见的例子，不能因单独执行时没有 G 码
  就省略。
- 官方 MSD 最小模型是 `A50` 就绪 / `A51` 执行 / `A70` 非等待直通。
  现场骨架可能是 `A050/A051/A070` 或别的组合；原机已经验证的 `C38`
  支路要逐字节保留，新 M/T 码只改动作和完成条件。某案例出现的
  `A050/A051/A052/A101/A188` 不是所有新代 PLC 的通用模板。

`plan-lint` 会对等待型 M 码没有任何 `C38` 写入的计划报
`mcode_wait_without_c38`，对比较 `R1` 但同网络没有 `S029` 的计划报
`mcode_decode_without_s029`。完整时序、`C38` 布尔式、真实样本和检查表见
`references/mcode-patterns.md`。

### 子程序命名：短标题、长批注

新增 `references/subprogram-naming.md`。`LAB` 名只表达功能和侧别，程序树
第一行是 2~8 字短标题（如 `【刀库】-刀盘转位`），详细职责、调用条件、
互锁和参数放到后续批注行。`plan-lint` 新增
`program_name_invalid`（error）、`program_title_missing`、
`program_title_too_long`、`program_title_numbered`、
`program_title_sentence`、`program_title_without_category`，避免把整句
职责写进程序树。



## 0.3.8p 重点

### R 分区：先判断数据性质，再选区

新增 `syntec_lad/data/register-zones.json` 和 `lookup` 的分区输出。查一个 R
地址时，不只知道它叫什么，还能看到：归属（系统/用户/条件占用）、阶梯权限、
宏/HMI 权限、是否掉电保持、能否位存取、条件区对应的 Pr 参数。

```powershell
python $LadCli lookup R2050
python $LadCli lookup R2100
python $LadCli lookup R700.0
python $LadCli lookup @108001
```

同时把三套容易混淆的命名空间分开写清楚：

- `R@R61`：**阶梯图间接寻址**，先读 R61 的值，再把它当作要访问的寄存器号；
- `@108001`：**宏/HMI 公用变量**，按 `R = @ - 100000` 映射到 `R8001`；
  但 `@` 不是全部对应 R：`@1~@400`、`@656~@1999`、`@60000~@79999`
  都是独立变量，`@100` 不是 R100；
- `#5001`：**宏变量**，不是 R5001。

`resources` 现在会按 R 分区汇总占用；`plan-lint` 新增
`r_system_write`、`r_bit_access_invalid`、`r_retain_mismatch`、
`r_conditional_zone`，以及整字写 `Rn` 又登记 `Rn.yy` 时的
`register_bitwise_overwrite`。完整决策表见 `references/register-map.md`。

### 八类元件 smoke 验证

新增 `tests/test_elements.py`：同一份计划生成 `I/O/A/C/S/R/TM/CT` 八类元件。
Python 回读 0 issue，原厂 `LadDLL.SyntaxCheck` 通过。该测试只证明格式/编辑器
兼容，不代表真机动作安全。

### 0.3.8p 修复汇总

- 修正 `@` 公用变量到 R 的分段映射：`@1~@400`、`@656~@999`、
  `@1001~@1999`、`@60000~@79999` 不对应 R，不能把 `@100` 当成 `R100`。
- 只有 `@401~@655`、`@10000~@14095`、`@100000~@165535` 映射 R；公式分别为
  `R = @ - 400`、`R = @ - 10000`、`R = @ - 100000`。
- 修正 `@` 映射后的可写范围：`R50~R80`、`R101~R511`、`R1024~R4095`、
  `R5800~R7999`、`R10000~R10999`、`R15000~R65535`。
- 补齐 `R0~R65535` 分区表，`lookup`、`resources`、`plan-lint` 会同时给出
  归属、权限、保持、位存取和条件 Pr。
- 区分阶梯 `R@R` 间接寻址、宏/HMI `@` 公用变量和 `#` 宏变量，避免混用。

## 0.3.7p 重点

### 资源规划：先出表，人确认，再进 plan

```powershell
python $LadCli resources cnc.lad --io 点位表.csv
python $LadCli plan-lint plan.json
```

`resources` 盘点已用地址、读/写次数、所属程序、现有注释、空闲候选和只读区
告警。空闲候选只是候选：要用必须写进 `plan.resources`，`source` 为
`io-table` 或 `user`。`source=suggested` 会让 `plan-lint` 直接失败。

### 注释分级：接口必须写，内部按需

```powershell
python $LadCli comments cnc.lad
```

L1 覆盖 `I/O/C/S` 和 `R0~R255`；L2 检查每个程序有没有头注释；L3 只统计长注释。
只报告不阻断，避免为了凑覆盖率写废话。

### Confluence 二次验证可降级

```powershell
python $LadCli cloud-status --snapshots references\snapshots
python $LadCli crosscheck cnc.lad --snapshots references\snapshots
```

没有 MCP 在线证据时明确输出 `未联网云端验证`；只有本地快照时标 `L1+`，
并提示快照可能落后于在线页。

## 0.3.6p 重点

### 同条件多输出真正合并

同一 `condition` 下的多个动作写进一个 `actions` 数组即可：

```json
{
  "condition": {"all": [{"contact": "I000"}, {"contact": "I001"}]},
  "actions": [
    {"op": "OUT", "operand": "O000"},
    {"op": "OUT", "operand": "O001"}
  ]
}
```

生成器只画一次条件，在动作列前加一条竖直母线，各动作上下并联，不再为
每个线圈重复整组条件。

### 新增 `plan-lint`

在生成 `.lad` 之前直接审计 JSON 计划：

- 条件按 DNF 规范化后比较，忽略 `all`/`any` 顺序差异。
- 识别 `A∧(B∨C)` 与 `(A∧B)∨(A∧C)` 等展开写法不同但逻辑等价的条件。
- 识别相邻的无条件网络。
- 报告 `JMP`/`JSR`/`MSG` 不能与其它动作共用母线。
- 报告条件过宽、无法共用动作母线的情况。

### 1 格线圈与 2 格动作可混排

1 格线圈固定在第 9 列，前面第 8 列是 LINE；2 格定时器/计数器/数据/流程
动作从第 8 列开始。两者可以共用第 8 列动作母线，不需要重复条件。

### 原生 DLL 自动发现

`0.3.6p` 先检查固定安装位置和 skill 自带目录：

```text
C:\Program Files (x86)\SYNTEC\MacroDev\Bin\LadDLL.dll
C:\Program Files\SYNTEC\MacroDev\Bin\LadDLL.dll
C:\Program Files (x86)\SYNTEC\LadEditor\LadDLL.dll
C:\Program Files\SYNTEC\LadEditor\LadDLL.dll
<skill>\native\LadDLL.dll
<skill>\native\bin\LadDLL.dll
```

固定位置都找不到时，才搜索 C 盘以外的本地固定盘（例如 D/E）。搜索只查找
`LadDLL.dll` 和 `MLCEdit.exe`，优先进入 `SYNTEC`、`LadEditor`、`MacroDev`
等目录，并限制搜索深度和目录数量；Windows、回收站、`node_modules`、
虚拟环境和缓存目录会跳过。成功路径缓存到
`%LOCALAPPDATA%\syntec-lad\native-discovery.json`，后续命令直接复用。

因此安装路径可以因电脑而异，不需要把某个人的 D 盘目录写死。本机实测
MacroDev 2014 版和 LadEditor 2.37.0 的 2025 版 DLL 都能通过原生校验。

## 功能总览

| 命令 | 作用 | 关键点 |
| --- | --- | --- |
| `inspect` | 查看编码、SHA256、程序边界、物理记录、注释、网络候选 | 支持 `--program` / `--network` 过滤 |
| `build` | 从 `syntec-lad-plan/v1` 生成新 `.lad` | 默认做 Python 回读 + LadDLL 原生校验 |
| `patch` | 用 `syntec-lad-change/v1` 修补现有 `.lad` | 每个操作都锁定 `expected_sha256` |
| `remap` | 同时替换 I/O、C/S/A 位和 R 寄存器位 | 避免 `I0→I400` 后又被 `I40→...` 误替换 |
| `validate` | 解析回读并调用原生 `LadDLL.SyntaxCheck` | 输出 `parser: PASS` / `native: PASS` |
| `diff` | 按注释块、网络、结构记录做段对齐比较 | 修改项给出操作数级差异，不是只有字节差异 |
| `lint` | 静态规则检查 | 重复线圈、S 当线圈、I/O 复用、越界、简体注释、可合并条件 |
| `resources` | 盘点已用/空闲的 I/O、A、C、S、TM、CT、R 地址 | 只出候选，不分配；可选对照 IO 点表 |
| `comments` | 按级别统计注释覆盖率 | L1 接口点、L2 程序头、L3 长注释 |
| `cloud-status` | 报告 Confluence 校验级别与快照 | 无证据时明确输出“未联网云端验证” |
| `plan-lint` | 生成前检查 JSON 计划 | DNF 等价条件、动作母线宽度、流程动作、资源来源与只读区 |
| `discover` | 识别 MB/SB/package 备份结构 | 自动找 `.lad`、`paramext.pxt`、`ParamExt_*.xml`、`AlarmPLC_*.xml`、IO 表 |
| `crosscheck` | 跨文件四项核对 | 参数表 ↔ 梯图、三语 ↔ 三语、报警位 ↔ 文案、IO 表 ↔ 梯图；可加 `--snapshots` 对照 Confluence 快照 |
| `lookup` | 查询 602 条 C/S/R 地址索引 | 无命中时回落到参考文档全文检索 |
| `zhconv` | 简体 ↔ 繁体转换 | 写 cp950/Big5 注释前使用 |
| `open` | 启动 `MLCEdit.exe -f <file>` | 仅供人工复核，不是语法校验 |

## 安全边界

- 原生 `.lad` 是唯一可写源格式；`.il`、PDF、BMP、截图和旧文本转储不能
  直接作为生成输入。
- 资源规划是**可审阅的建议**，不是自动分配。`resources` 只盘点现状并列出
  空闲候选；一条地址要进生成流程，必须写进 `plan.resources`，且
  `source` 为 `user` 或 `io-table`。`source=suggested` 会让 `plan-lint`
  直接失败。缺少的地址和参数仍然必须先向用户确认。
- `R81`~`R100`（系统参数窗口）、`R8000`~`R8255`（宏程序区）、`I`、`S`
  在阶梯程序里只读；对这些区写入会被 `resource_readonly_write` 拦下。
- 不生成 RS232、Keyscan、文件系统、外部功能、Coord/Tool 或 FastPLC 记录。
- 未知或高级记录必须逐字节保留。
- `build` / `patch` 默认同时执行 Python 回读和 LadDLL 原生校验；任一失败
  都不应覆盖目标文件。
- `open` 只启动编辑器供人工复核，不把“能打开”当作语法通过。
- 不点击编辑器界面，不上传 CNC，不直接修改控制器。

## 环境要求与原生校验

### 最低要求

- Windows 10/11（原生校验和 `open` 需要；纯解析/生成可在其他系统运行）。
- Python 3.10 或更高版本。
- 无第三方 Python 依赖。
- 原生校验：32 位 `LadDLL.dll`、.NET Framework 4.x、可用的 `csc.exe`。
- 人工复核：`MLCEdit.exe`。

### 自动查找 LadDLL

默认先尝试固定 C 盘安装位置和 skill 自带目录：

```text
C:\Program Files (x86)\SYNTEC\MacroDev\Bin\LadDLL.dll
C:\Program Files\SYNTEC\MacroDev\Bin\LadDLL.dll
C:\Program Files (x86)\SYNTEC\LadEditor\LadDLL.dll
C:\Program Files\SYNTEC\LadEditor\LadDLL.dll
<skill>\native\LadDLL.dll
<skill>\native\bin\LadDLL.dll
```

固定位置不存在时，会自动搜索其它本地固定盘。搜索有深度和目录数量上限，
会优先匹配 `SYNTEC` / `LadEditor` / `MacroDev` 目录名，并跳过系统目录、
依赖目录和缓存目录。找到后会写入用户缓存，后续不再重复扫描。

如果需要固定使用某一版 DLL，仍可显式指定：

```powershell
$env:SYNTEC_LAD_DLL = 'C:\path\to\LadEditor\LadDLL.dll'
$env:SYNTEC_LAD_EDITOR = 'C:\path\to\LadEditor\MLCEdit.exe'
```

或在单次命令中使用：

```powershell
python $LadCli validate .\file.lad --dll "C:\path\to\LadDLL.dll"
python $LadCli build .\plan.json .\new.lad --dll "C:\path\to\LadDLL.dll"
```

### 原生校验在做什么

64 位 Python 不能直接加载 32 位 `LadDLL.dll`，所以 SDK 会编译并调用一个
x86 的 `LadSyntaxCheck.exe` 辅助程序。最终结果看：

```text
parser  : PASS
native  : PASS  error_count=0
```

本版已兼容缺少导出序号 `#124` 的旧版 DLL；原版在这种情况下会直接失败。
如果本机没有 DLL，`inspect` / `diff` / `lint` / `plan-lint` / `lookup` /
`discover` / `zhconv` 仍可运行；`build` / `patch` / `remap` 默认需要原生
校验，缺 DLL 时会失败。此时只能加 `--no-native` 做解析级诊断，不能算
“原生语法通过”，也不应作为交付结果。

## 安装

### 方式一：下载分发包

- 最新 GitHub Release：
  <https://github.com/Aoliaosiki/Syntec-lad-skill-P/releases/latest>
- 仓库内历史分发包在 `downloads/`；当前版本请以 Releases 页为准。

解压后把文件夹命名为 `syntec-lad`，放到对应 Agent 的 skills 目录。

### 方式二：克隆仓库

```powershell
# Codex
$target = Join-Path $HOME '.codex\skills\syntec-lad'
# CodeBuddy
# $target = Join-Path $HOME '.codebuddy\skills\syntec-lad'
# WorkBuddy
# $target = Join-Path $HOME '.workbuddy\skills\syntec-lad'

New-Item -ItemType Directory -Force -Path (Split-Path $target) | Out-Null
git clone https://github.com/Aoliaosiki/Syntec-lad-skill-P.git $target
```

刷新或重启客户端后即可调用。Codex 中可显式写 `$syntec-lad`。

### 方式三：免安装 CLI

Skill 自带启动器，不要求 `pip install`：

```powershell
$LadCli = Join-Path $HOME '.codex\skills\syntec-lad\scripts\run_syntec_lad.py'
python $LadCli --version
python $LadCli --help
```

CodeBuddy 把路径换成 `~/.codebuddy/skills/syntec-lad/...`。

### 方式四：安装为 Python 包

在仓库根目录：

```powershell
python -m pip install -e .
syntec-lad --version
```

## 快速开始

以下命令假设已设置：

```powershell
$LadCli = Join-Path $HOME '.codex\skills\syntec-lad\scripts\run_syntec_lad.py'
```

### 1. 先检查源文件

```powershell
python $LadCli inspect .\source.lad
python $LadCli inspect .\source.lad --json --output .\source.inspect.json
python $LadCli inspect .\source.lad --program MAIN
python $LadCli inspect .\source.lad --network N0016 --rows 8
```

确认编码、SHA256、程序边界、网络候选和注释。不要凭截图或行号猜记录范围。

### 2. 写计划并做生成前检查

```powershell
python $LadCli plan-lint .\plan.json
python $LadCli plan-lint .\plan.json --json --output .\plan-lint.json
```

有 `mergeable_condition` 时，把后一个网络的 `actions` 并入前一个网络。只有
部分条件相同时，不要擅自新增中间继电器；保持多个网络，或使用用户确认过的
A 区中间标志。

### 3. 生成、回读、原生校验

```powershell
python $LadCli build .\plan.json .\new.lad
python $LadCli validate .\new.lad
```

成功输出必须同时包含：

```text
parser readback: PASS
native syntax: PASS  error_count=0
```

### 4. 与源文件比较

```powershell
python $LadCli diff .\source.lad .\new.lad
python $LadCli diff .\source.lad .\new.lad --json --output .\diff.json
```

### 5. 人工复核

```powershell
python $LadCli open .\new.lad
```

只启动 `MLCEdit.exe -f <file>`，不点击任何界面按钮，不上传 CNC。

## 命令参考

### `inspect`

```powershell
python $LadCli inspect .\file.lad
python $LadCli inspect .\file.lad --encoding big5
python $LadCli inspect .\file.lad --json --output .\file.inspect.json
python $LadCli inspect .\file.lad --program MAIN --rows 5
python $LadCli inspect .\file.lad --network N0016
```

主要输出：

- 文件大小、编码、SHA256、记录数。
- MAIN / 子程序范围、LAB/RTS/END 边界。
- 注释块、网络候选、记录范围和网络 SHA256。
- 完整性问题和预览指令。

### `build`

```powershell
python $LadCli build .\plan.json .\new.lad
python $LadCli build .\plan.json .\new.lad --encoding big5
python $LadCli build .\plan.json .\new.lad --open
python $LadCli build .\plan.json .\new.lad --no-native   # 仅诊断，不作交付
```

- 目标已存在时默认拒绝覆盖。
- `--in-place` 才会原子替换并创建带时间戳的 `.bak`。
- 默认执行 Python 回读 + LadDLL 原生校验。

### `patch`

```powershell
python $LadCli inspect .\source.lad --json --output .\source.inspect.json
python $LadCli patch .\source.lad .\change.json .\patched.lad
python $LadCli patch .\source.lad .\change.json --in-place
```

- `base_sha256` 防止源文件已被改动。
- 每个操作的 `expected_sha256` 防止目标记录范围已变化。
- 跨网络边界、结构行和过期哈希都会被拒绝。
- 支持 `insert`（按锚点或范围）、`replace`、`delete`。
- 打补丁前自动跑 `change` 的资源门禁：`resources` 里有 `source=suggested`
  或写了只读区时直接拒绝。确认后仍要覆盖，才用 `--allow-unverified`。

### `remap`

```powershell
python $LadCli remap .\source.lad .\mapped.lad `
  --map I0=I400 `
  --map I1=I401 `
  --map I2=I402 `
  --require-all-sources `
  --report .\remap.json
```

映射文件写法：

```json
{
  "I0": "I400",
  "I1": "I401",
  "C6": "C106"
}
```

```powershell
python $LadCli remap .\source.lad .\mapped.lad `
  --mapping-file .\mapping.json `
  --expected-sha256 <inspect 输出的 sha256> `
  --require-all-sources
```

- 同时替换，避免 `I0→I400` 后又被 `I40→...` 二次替换。
- `--require-all-sources` 要求每个映射源都出现在梯图中。
- 支持 `--in-place`、`--overwrite`、`--report`、`--json`。

### `validate`

```powershell
python $LadCli validate .\file.lad
python $LadCli validate .\file.lad --json
python $LadCli validate .\file.lad --no-native   # 仅解析回读
python $LadCli validate .\file.lad --dll "C:\path\to\LadDLL.dll"
```

`--no-native` 只能用于诊断。最终交付必须看到原生校验通过。

### `diff`

```powershell
python $LadCli diff .\before.lad .\after.lad
python $LadCli diff .\before.lad .\after.lad --context 20
python $LadCli diff .\before.lad .\after.lad --context 0
python $LadCli diff .\before.lad .\after.lad --json
```

按注释块 / 网络 / 结构记录做段对齐，输出未变、修改、新增、删除、移动五类
结果。默认只显示前 8 条差异；`--context N` 显示前 N 条，`--context 0`
显示全部差异。修改项会给出操作数级差异，例如：

```text
OUT R0591.04 -> OUT R0590.04
```

### `lint`

```powershell
python $LadCli lint .\file.lad
python $LadCli lint .\file.lad --json --output .\lint.json
python $LadCli lint .\file.lad --io-max-uses 8
python $LadCli lint .\file.lad --limit 0
```

规则：

| 规则 | 级别 | 含义 |
| --- | --- | --- |
| `duplicate_coil` | error | 同一地址被多个网络驱动 |
| `s_as_coil` | error | 把只读 `S` 区当线圈 |
| `address_range` | error | 地址超出允许范围 |
| `missing_end` | error | 没有 `END` / `FEND` |
| `io_reused` | warning | 同一 I/O 点被过多网络直接使用 |
| `simplified_comment` | warning | 注释含简体字，cp950 下可能显示为问号 |
| `mergeable_condition` | warning | 相邻网络条件逻辑等价，可合并到同一 `actions` |
| `mergeable_condition_too_wide` | info | 条件太宽，无法共用动作母线 |
| `flow_action_not_mergeable` | info | 含 `JMP`/`JSR`/`MSG`，不能进并行动作母线 |

`error` 会让命令返回 1；`warning` / `info` 不阻断，但应逐条确认。


### `plan-lint`

```powershell
python $LadCli plan-lint .\plan.json
python $LadCli plan-lint .\plan.json --json
python $LadCli plan-lint .\plan.json --output .\plan-lint.json
```

规则：

| 规则 | 级别 | 含义 |
| --- | --- | --- |
| `invalid_condition` | error | 条件无法解析或规范化 |
| `mergeable_condition` | warning | 相邻条件逻辑等价，应合并 `actions` |
| `mergeable_condition_too_wide` | info | 条件宽度超过共用母线起点 |
| `mixed_action_too_wide` | info | 同一网络混用 1/2 格动作且条件过宽 |
| `flow_action_not_mergeable` | info | 流程动作不能与其它动作共用母线 |
| `program_name_invalid` | error | 子程序 `LAB` 名不是 1~6 位 ASCII 字母/数字 |
| `program_title_missing` / `program_title_too_long` / `program_title_numbered` / `program_title_sentence` / `program_title_without_category` | warning | 程序树标题缺少、超长、带序号、含句读或没有分类前缀 |
| `mcode_wait_without_c38` | warning | 解码了等待型 M 码，但计划里没有任何 `C38` 写入 |
| `mcode_decode_without_s029` | warning | 比较 `R1` 解码 M 码，但同网络没有 `S029` |
| `resource_unverified` | error | `plan.resources` 里还有 `source=suggested` |
| `resource_source_invalid` | error | `source` 不在 `io-table/user/scan/suggested` 内 |
| `resource_duplicate` | error | 同一地址登记两次 |
| `resource_readonly_write` | error | 写了 `R81~R100`、`R8000~R8255`、`I` 或 `S` |
| `register_bitwise_overwrite` | warning | 整字写 `Rn`，但同一计划登记了 `Rn.yy` 位地址 |
| `resource_missing` | warning | 用了 I/O/C/S 或 `R0~R255` 却没登记 |
| `resource_unused` | info | 登记了但没有任何网络使用 |



`plan-lint` 也接受 `syntec-lad-change/v1`：这时跑资源规则，按
`operations[].networks` 统计地址，输出里标 `Change: N operation(s)`。

### `resources`

```powershell
python $LadCli resources .\cnc.lad
python $LadCli resources .\cnc.lad --io .\io-points.csv
python $LadCli resources .\cnc.lad --format csv --output .\baseline.csv
python $LadCli resources .\cnc.lad --r-max 2047 --json
```

输出每个族的已用地址、读/写次数、所属程序、现有注释、空闲候选，以及
IO 点表的双向差集。**空闲候选不是分配结果**；新建和修改都必须由人确认后
写入 `plan.resources`。R 地址还会附带分区、归属、阶梯/宏权限、保持和位存取，
并按分区汇总占用。详见 `references/resource-planning.md` 和
`references/register-map.md`。

### `comments`

```powershell
python $LadCli comments .\cnc.lad
python $LadCli comments .\cnc.lad --json --output .\coverage.json
```

按三级统计：L1 接口点（I/O/C/S、`R0~R255`）、L2 程序头注释、L3 长注释。
只报告不阻断；写法规范见 `references/comment-policy.md`。

### `cloud-status`

```powershell
python $LadCli cloud-status
python $LadCli cloud-status --snapshots .\references\snapshots
python $LadCli cloud-status --snapshots .\references\snapshots --online
```

没有 MCP 在线证据时输出 `L1 — 未联网云端验证`；只有本地快照时输出 `L1+`。
`--online` 只能由实际读过页面的 agent 添加。接入步骤见
`references/confluence-verification.md`。

### `discover`

```powershell
python $LadCli discover "D:\path\to\MB_or_SB_backup"
python $LadCli discover "D:\path\to\single.lad"
python $LadCli discover "D:\path\to\backup" --json
```

报告备份里实际存在哪些文件：

```text
Ladder/cnc.lad
ParameterExt/paramext.pxt
DiskC/OpenCNC/Res/paramext.pxt
DiskC/OCRes/<lang>/String/ParamExt_<lang>.Xml
AlarmPLC_*.xml
IO 点位表
```

### `crosscheck`

```powershell
python $LadCli crosscheck --delivery "D:\path\to\MB_or_SB_backup"
python $LadCli crosscheck .\cnc.lad `
  --pxt .\paramext.pxt `
  --param-xml .\ParamExt_CHS.xml `
  --param-xml .\ParamExt_CHT.xml `
  --alarm-xml .\AlarmPLC_CHS.xml `
  --io .\io.csv
```

四项核对：

1. `paramext.pxt` 里的参数是否被梯图读取，或梯图是否读取了不存在的参数。
2. `ParamExt_CHS/CHT/COM.xml` 三语条目是否一致（排除注释掉的条目）。
3. 梯图写入的报警位是否有 `AlarmPLC_*.xml` 文案。
4. IO 点位表与梯图是否有一边缺失。

### `lookup`

```powershell
python $LadCli lookup C6
python $LadCli lookup C006 --json
python $LadCli lookup R600.1
python $LadCli lookup R2050
python $LadCli lookup R700.0
python $LadCli lookup @108001
python $LadCli lookup @401
python $LadCli lookup @100
python $LadCli lookup R@R61
python $LadCli lookup @R100
python $LadCli lookup "M码" --limit 5
python $LadCli lookup "润滑"
python $LadCli lookup R99999 --addresses-only
```

先查 602 条 C/S/R 地址索引；R 地址会追加分区、权限、保持、位存取和条件 Pr
说明；`@` 查询会按 Confluence《Macro变数规格》解释公用变量区段，只有
`@401~@655`、`@10000~@14095`、`@100000~@165535` 会映射到 R；
`R@R` 查询会解释阶梯图间接寻址（`@R` 是兼容别名，官方写法是 `R@R`）。
无命中时回落到 `references/` 全文检索，适合用“润滑”“刀库”“安全门”这类
工艺词定位章节。

### `zhconv`

```powershell
python $LadCli zhconv "主轴润滑压力不足"
python $LadCli zhconv "主軸潤滑壓力不足" --to-simplified
python $LadCli zhconv "主轴润滑压力不足" --json
```

写注释前把简体转成繁体，避免 cp950/Big5 编辑器显示问号。

### `open`

```powershell
python $LadCli open .\file.lad
python $LadCli open .\file.lad --editor "C:\path\to\MLCEdit.exe"
python $LadCli open .\file.lad --wait
```

只启动编辑器，不做 UI 自动化，不上传 CNC。

## Plan Schema

完整 Schema：`syntec_lad/schema/lad-plan.schema.json`。

最小示例：

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
              {
                "any": [
                  {"contact": "I001", "normally": "closed"},
                  {"contact": "O000"}
                ]
              }
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

### 顶层字段

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `schema` | 是 | 固定 `syntec-lad-plan/v1` |
| `programs` | 是 | 至少一个程序 |
| `encoding` | 否 | `gb2312`、`gb18030`、`big5` |
| `layout` | 否 | `auto`（默认）或 `expanded` |
| `variables` | 否 | 变量注释（type-4，`name/short/long`） |
| `resources` | 否 | 地址登记表；新建流程必须提供，缺省时保持旧行为 |

### `resources` 字段

```json
{
  "addr": "R0200",
  "symbol": "润滑累计次数",
  "purpose": "每次打油完成加 1，满 500 次提示保养",
  "permission": "readwrite",
  "retain": true,
  "owner": "MAIN",
  "source": "user",
  "note": "掉电保持，避开 R103~R192 刀号区"
}
```

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `addr` | 是 | `I0` / `R200.03` / `TM12` |
| `source` | 是 | `io-table` / `user` / `scan` / `suggested` |
| `symbol` | 否 | 图上短名 |
| `purpose` | 否 | 用途和触发条件 |
| `permission` | 否 | `read` / `write` / `readwrite` |
| `retain` | 否 | 是否掉电保持 |
| `owner` | 否 | 归属程序或功能 |
| `note` | 否 | 现场差异、选配说明；条件占用区必须写明 Pr 条件 |

`source=suggested` 是唯一会让 `plan-lint` 失败的值：它表示「模型建议、
还没人确认」。把 `suggested` 批量改成 `user` 来绕过检查，等于放弃审阅。

条件占用区的 `note` 必须能判断启用条件：`R2050~R2090` 写 `Pr3810=0/1`，
`R2100~R3100` 写 `Pr3228=0/1`，`R1024~R1032` 写铣床自动分中/对刀或车床用户区。
缺条件时 `plan-lint` 报 `r_conditional_zone`。

### 程序字段

- `name`：`MAIN` 或 1 到 6 位 ASCII 字母/数字的普通子程序名
  （如 `1`、`MAG1`）。中文和描述不能写进 `name`。
- `comment`：程序注释，最长 255 字符。子程序的第一行是 LadEditor 程序树
  标题，必须是 `【分类】-短主题`（建议 ≤20 字）；从第二行起写职责、调用
  条件、互锁、参数和 I/O 速查。
- `networks`：网络数组。

#### 子程序命名

LadEditor 程序树显示的是 `comment` 第一行，后面的 `(1)`、`(9)` 才是
`LAB` 名。标题写成一整句会把同级的其它程序挤出视野，所以按下面分层：

```json
{
  "name": "9",
  "comment": "【刀库】-伺服刀库\n职责：刀盘旋转、刀套翻转与换刀完成确认\n调用：M06 且主轴停止、刀库门关闭\n互锁：急停、刀库未原点、气压不足时禁止启动\n参数：R120~R139 刀号与刀套映射",
  "networks": []
}
```

规则：

- `LAB` 名 1~6 位 ASCII 字母/数字，推荐沿用现场编号 `1`、`2` …，或短代号
  `MAG1`、`LUB1`。
- 第一行统一 `【分类】-短主题`，分类可用 `【外部端子】`、`【面板功能】`、
  `【系统功能】`、`【刀库】`、`【报警】`、`【M码】`、`【润滑】`、`【液压】`、
  `【排屑】`、`【主轴】`、`【冷却】`、`【安全】`。
- 第一行不写 `(1)`、`1.` 这类序号，不写 `，。；！？、`，不写日期和版本。
- 详细说明从第二行开始；如果现场不使用多行程序注释，就放到程序体第一条
  `type-1` 注释，标题行仍保持短句。

`plan-lint` 会检查：

| 规则 | 级别 | 触发条件 |
| --- | --- | --- |
| `program_name_invalid` | error | `LAB` 名不是 1~6 位 ASCII 字母/数字 |
| `program_title_missing` | warning | 子程序没有 `comment` |
| `program_title_too_long` | warning | 标题第一行超过 20 字 |
| `program_title_numbered` | warning | 标题以 `(1)`、`1.`、`一、` 开头，或以 `(9)` 结尾 |
| `program_title_sentence` | warning | 标题含 `，。；！？、` |
| `program_title_without_category` | warning | 标题没有 `【分类】-` 前缀 |

完整规则、现场样本和反模式见 `references/subprogram-naming.md`。

`JMP` / `JSR` 的目标必须是已声明的普通子程序，不能调用 `MAIN` 或未声明
的局部 `LAB`。

### 条件形态

```json
{"contact": "I000"}
{"contact": "I001", "normally": "closed"}
{"all": [{"contact": "I000"}, {"contact": "I001"}]}
{"any": [{"contact": "I000"}, {"contact": "I001"}]}
{"always": true}
{"compare": {"relation": "=", "value": "R0001", "other": "#00005"}}
```

- `all` 是串联，`any` 是并联，可任意嵌套。
- `contact` 支持 `I/O/A/C/S/R.x/TM/CT`。
- `compare` 关系支持 `>`、`<`、`=`，值支持寄存器或常数。
- `always` 只接受 `true`。

### 动作形态

线圈：

```json
{"op": "OUT", "operand": "O000"}
{"op": "OUTI", "operand": "O001"}
{"op": "SET", "operand": "A010"}
{"op": "RST", "operand": "A010"}
{"op": "PLS", "operand": "A011"}
{"op": "PLF", "operand": "A011"}
```

定时器 / 计数器：

```json
{"op": "TIM", "timer": "TM000", "unit": "100ms", "preset": "#00050"}
{"op": "CNTUP", "counter": "CT000", "preset": "#00010"}
{"op": "CNTDOWN", "counter": "CT001", "preset": "R0100"}
{"op": "CNTRESET", "counter": "CT000"}
```

数据与流程：

```json
{"op": "MOV", "src": "R0001", "dst": "R0100"}
{"op": "ADD", "src": "#1", "dst": "R0100"}
{"op": "JSR", "target": "SUB1"}
{"op": "MSG", "target": "ALM001"}
```


### 同条件多动作

同一条件驱动多个输出时，写进同一个 `actions` 数组：

```json
{
  "condition": {"all": [{"contact": "I000"}, {"contact": "I001"}]},
  "actions": [
    {"op": "OUT", "operand": "O000"},
    {"op": "OUT", "operand": "O001"},
    {"op": "TIM", "timer": "TM000", "unit": "100ms", "preset": "#00050"}
  ]
}
```

1 格线圈和 2 格动作可以混排。动作母线在第 8 列，线圈前保留第 8 列 LINE。

以下情况不会强行合并：

- 条件本身已经占满第 8 列，2 格动作放不下；`plan-lint` 报
  `mergeable_condition_too_wide` / `mixed_action_too_wide`。
- 动作含 `JMP` / `JSR` / `MSG`；流程动作保持独立行，`plan-lint` 报
  `flow_action_not_mergeable`。
- 只有部分条件相同；不要擅自新增中间继电器。

### 布局模式

`layout` 可写在顶层或单个 network 上：

- `auto`（默认）：直接按原始 `all`/`any` 树排布。`all` 从左到右串联，
  `any` 上下并联并在左右画母线；嵌套并联块共用公共前缀/后缀，尾部串联
  只写一次。
- `expanded`：一个 DNF 项一行，用于对照或回退旧布局。

例如：

```text
A040 ∧ (A012∨A013) ∧ (S069∨R075.00) ∧ A031 ∧ A051 ∧ R044.05
```

`auto` 生成 2 行，而不是展开成 4 行重复公共条件。外层 OR + 内层并联也可
直接排布：

```text
(A040 ∧ (A012∨A013) ∧ (S069∨R075.00) ∧ ¬A031) ∨ (A043 ∧ ¬A044)
∧ A051 ∧ ¬R044.05
```

生成 3 行，`A043/¬A044` 从下方并入 `A051` 前的母线。

`auto` 的回落顺序是树形布局 → 笛卡尔积因式分解 → `expanded`。

### 注释与编码

- 新文件默认 `gb2312`，可在计划顶层覆盖。
- 编辑器兼容注释建议使用 cp950/Big5 繁体。
- 简体中文可能显示成问号；写前用 `zhconv` 转繁体。
- 建议三层注释：元件注释、功能段注释、程序头注释。

## Change Schema

完整 Schema：`syntec_lad/schema/lad-change.schema.json`。

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

### `insert`

按锚点插入：

```json
{
  "op": "insert",
  "at_record": 19,
  "expected_sha256": "<record 19 所在范围的 sha256>",
  "networks": [
    {
      "condition": {"contact": "I020"},
      "actions": [{"op": "OUT", "operand": "O020"}]
    }
  ]
}
```

按范围插入：

```json
{
  "op": "insert",
  "record_start": 19,
  "record_end": 26,
  "position": "after",
  "expected_sha256": "<该范围的 sha256>",
  "networks": [
    {
      "condition": {"contact": "I021"},
      "actions": [{"op": "OUT", "operand": "O021"}]
    }
  ]
}
```

`position` 可取 `before` 或 `after`。

### `delete`

```json
{
  "op": "delete",
  "record_start": 19,
  "record_end": 26,
  "expected_sha256": "<该范围的 sha256>"
}
```

### 哈希锁定规则

- `base_sha256` 必须等于当前源文件 SHA256。
- 每个操作的 `expected_sha256` 必须等于目标记录范围当前 SHA256。
- 任一哈希不一致、范围跨网络边界或落在结构行上，操作会被拒绝。
- 只有用户明确要求覆盖时才使用 `--in-place`；SDK 会创建时间戳 `.bak`，
  并处理同名 `.LC` 侧车文件。

## Python SDK

```python
from pathlib import Path

from syntec_lad import LadDocument, compile_plan, validate_document
from syntec_lad.inspection import inspect_document

plan = {
    "schema": "syntec-lad-plan/v1",
    "programs": [
        {
            "name": "MAIN",
            "networks": [
                {
                    "condition": {"contact": "I000"},
                    "actions": [{"op": "OUT", "operand": "O000"}],
                }
            ],
        }
    ],
}

document = compile_plan(plan)
document.save(Path("new.lad"))

readback = LadDocument.load("new.lad")
print(readback.sha256)
print(inspect_document(readback)["network_candidates"])
validate_document(readback)  # 需要本机 32 位 LadDLL
```

常用公开接口：

- `LadDocument.load/save/to_bytes/sha256`
- `compile_plan` / `compile_networks`
- `inspect_document` / `inspect_lad`
- `apply_change_plan` / `apply_change_plan_file`
- `remap_plc_bits`
- `lookup_address`
- `validate_document` / `validate_native`
- `lint_plan` / `condition_signature`

## MCP 与其他 Agent

### MCP 配置

```json
{
  "mcpServers": {
    "syntec-lad": {
      "command": "python",
      "args": [
        "C:/path/to/syntec-lad/scripts/syntec_lad_mcp.py"
      ]
    }
  }
}
```

也可参考 `mcp-config.example.json`。

### MCP 工具

| 工具 | 作用 |
| --- | --- |
| `inspect_lad` | 检查程序、注释、记录范围、网络候选，支持 `program` / `network` |
| `lookup_address` | 查地址或工艺关键词 |
| `build_plan` | 从计划生成 `.lad` |
| `patch_lad` | 应用哈希锁定变更 |
| `validate_lad` | 解析回读 + 原生校验 |
| `diff_lad` | 段对齐差异 |
| `lint_lad` | `.lad` 静态规则 |
| `lint_plan` | 生成前计划审计 |
| `crosscheck_lad` | 参数/三语/报警/IO 四项核对 |
| `read_reference` | 读取 `references/` 文档 |
| `list_references` | 列出参考文件 |
| `explain_capabilities` | 说明工作流和安全边界 |

### WorkBuddy

```powershell
python .\scripts\install_workbuddy.py
```

或双击 `scripts\install_workbuddy.bat`。安装器会复制 Skill、备份旧目录、
合并 `~/.workbuddy/mcp.json`，并在改动前跑 CLI/MCP 自检。

### 其他 Agent

```powershell
python .\scripts\run_syntec_lad.py --version
python .\scripts\run_syntec_lad.py inspect .\source.lad
```

跨 Agent 说明见 `PORTABLE.md`。

## 工程知识库

`references/panming/` 是从 MIT 许可的
[`panming/syntec-plc-ladder`](https://github.com/panming/syntec-plc-ladder)
整理的工程知识快照，保留原文和来源标记。内容包括：

- 8 类元件分工、C/S 全表、R 寄存器分配和常见误用。
- 602 条 C/S/R 地址反向索引，可浏览 Markdown/CSV 或使用 CLI 查询。
- 12 个真机工艺模式：启保停、自动/手动、报警锁存、定时循环、互锁、
  模拟量回差、上电初始化等。
- 润滑、液压、排屑/冷却、刀库/刀塔、M 码五类功能写法库。
- 现场约定、三层注释、批注编码、R512~R1023 权限表和 `.lad` 技术附录。

知识入口：

| 需要 | 读取 |
| --- | --- |
| 地址类别、C/S/R 表、权限 | `references/panming/address-map.md` |
| R 分区、保持、位存取、`@`/`R@R` | `references/register-map.md` |
| 精确地址查询 | `python $LadCli lookup <address>` |
| 触点/线圈/定时/计数/比较/流程语法 | `references/panming/element-grammar.md` |
| 12 个常用回路 | `references/panming/patterns.md` |
| 润滑/液压/排屑/刀库/M 码 | `references/panming/function-library.md` |
| M 码 `S29/R1/C38`、等待型握手与超时 | `references/mcode-patterns.md` |
| 现场约定和程序骨架 | `references/panming/project-conventions.md` |
| 注释编码 | `references/panming/comment-encoding.md` |
| 子程序命名、树标题与批注分层 | `references/subprogram-naming.md` |
| 紧凑二进制布局 | `references/panming/lad-format.md` |
| R512~R1023 权限 | `references/panming/R512-R1023-权限表.md` |
| 完整操作码/格式附录 | `references/panming/TECHNICAL.md` |
| 原生计划/变更工作流 | `references/workflow.md` |
| MB/SB/package 备份结构 | `references/delivery-layout.md` |


知识层用于选结构和查地址；写入仍必须走 `inspect` → 计划/变更 →
`build`/`patch` → 回读 + 原生校验。

## 备份目录识别

### MB 备份

```text
<backup>/
  Ladder/cnc.lad
  ParameterExt/paramext.pxt
  ...
```

### SB 备份

```text
<backup>/
  DiskC/OpenCNC/Ladder/CNC.LAD
  DiskC/OpenCNC/Res/paramext.pxt
  DiskC/OCRes/<lang>/String/ParamExt_<lang>.Xml
  ...
```

### 一键核对

```powershell
python $LadCli discover "D:\path\to\backup"
python $LadCli crosscheck --delivery "D:\path\to\backup"
```

`discover` 只报告找到了什么；`crosscheck` 才会真正做四项内容核对。
`IoMap_Customer.xml` 是端口映射，不是 IO 点位表；`ParamExt_RBit_*.xml`
是另一组参数，不要混用。

## 测试与当前验证结果

```powershell
python -m unittest discover -s tests -v
```

当前结果：

- 公开构建跑完整测试套件。
- `examples/resources.plan.json`：`plan-lint: PASS`，`build` 原生校验
  `PASS error_count=0`，`comments` 覆盖率 L1 7/7、L2 2/2。
- 本机 LadEditor 2.37.0（2025 版）和
  `C:\Program Files (x86)\SYNTEC\MacroDev\Bin\LadDLL.dll`（2014 版）
  均可用。
- `examples/demo.lad`：`native: PASS error_count=0`。
- `examples/mvp.lad`：`native: PASS error_count=0`。
- 混合 `TIM+OUT` 同条件布局：`native: PASS error_count=0`。
- 9 触点条件驱动双线圈：`native: PASS error_count=0`。
- 八类元件 `I/O/A/C/S/R/TM/CT`：Python 回读 0 issue，原厂
  `LadDLL.SyntaxCheck` 通过。
- R 分区表覆盖 `R0~R65535` 无空洞；`R2050`/`R2100`/`R700.0`/`@108001`
  的查询与 `plan-lint` 规则均有单元测试。
- `LadDLL.dll` 和 `MLCEdit.exe` 的自定义盘符安装目录可由兜底搜索自动定位。

真实样本测试可指定：

```powershell
$env:SYNTEC_LAD_SAMPLE = 'D:\path\to\cnc.lad'
$env:SYNTEC_LAD_DLL    = 'C:\path\to\LadEditor\LadDLL.dll'
python -m unittest discover -s tests -v
```

## 常见问题

**`validate` 提示原生校验无法运行？**

先用 `--dll` 或 `SYNTEC_LAD_DLL` 指向 32 位 `LadDLL.dll`；本版会自动尝试
`Program Files (x86)\SYNTEC\MacroDev\Bin`、`Program Files\SYNTEC\MacroDev\Bin`
等固定位置；仍找不到时会搜索其它本地固定盘中的 `LadDLL.dll`。已兼容缺少
导出序号 `#124` 的 DLL。没有 DLL 时 `build` / `patch` / `remap` 会失败；
只能加 `--no-native` 做解析级诊断，不能声称原生语法通过。

**中文注释显示成乱码？**

`.lad` 内注释通常是 cp950/Big5 或 gb2312。`inspect` 会自动探测；写入时
注释建议用繁体，简体可能显示为问号。可先运行 `zhconv`。

**把目录放进 skills 后 Agent 没反应？**

目录名必须是 `syntec-lad`，`SKILL.md` 必须在目录根层；然后重启或刷新
客户端。Codex 中可显式写 `$syntec-lad`。

**`diff` 输出几千处改动？**

原版按下标硬对齐，插入一条记录后后面全部错位。本版按注释块/网络/结构
记录段对齐，只报告真实新增/修改/删除/移动；仍异常时附 `--json` 输出。

**能直接改 CNC 或操作编辑器界面吗？**

不能。只处理本地 `.lad` 文件，不点击界面、不上传控制器。

**手上只有整包备份，怎么最快核对？**

先 `discover` 看识别结果，再 `crosscheck --delivery` 一次跑完四项核对。

**`lint` 报了很多 `duplicate_coil` / `io_reused`，都是错吗？**

`duplicate_coil` 是错误级，通常是真的重复驱动。`io_reused` 是警告级：
同一 I/O 点在多个网络直接读写，Syntec 规范建议映射到 `A300+n` /
`A400+n` 后统一使用；老程序常见，可用 `--io-max-uses` 调阈值。

**`plan-lint` 报了 `mergeable_condition`，一定要合并吗？**

相邻网络条件逻辑等价且动作能共用母线时，应合并到同一 `actions`。如果
条件只是部分相同，不要为了合并擅自新增中间继电器；保持多个网络，或使用
用户确认过的 A 区中间标志。

## 目录结构

```text
SKILL.md                       Codex Skill 入口与强制安全流程
README.md                      本文件
CHANGELOG.md                   版本变更记录
THIRD_PARTY_NOTICES.md         第三方知识与 MIT 许可声明
PORTABLE.md                    Codex / WorkBuddy / MCP 通用接入说明
mcp-config.example.json        MCP 客户端配置示例
agents/openai.yaml             Skill 展示信息
scripts/run_syntec_lad.py      免安装启动器
scripts/syntec_lad_mcp.py      MCP stdio 适配器
scripts/install_workbuddy.py   WorkBuddy 安装器
syntec_lad/                    Python SDK、CLI、Schema 和内置数据
  compiler.py                  计划 → 原生记录
  inspection.py                记录/程序/网络检查
  lint.py                      .lad 静态规则
  plan_lint.py                 计划级合并审计
  resources.py                 I/O/A/R 资源盘点（只出候选）
  comments.py                  注释分级覆盖率
  cloud.py                     Confluence 快照与降级状态
  patch.py                     哈希锁定变更
  remap.py                     同步地址重映射
  lad_diff.py                  段对齐差异
  crosscheck.py                跨文件核对
  delivery.py                  MB/SB/package 识别
  native.py                    LadDLL 原生校验
native/                        x86 LadDLL 校验辅助程序源码
tools/lad_parser.py            独立旧版解析/反汇编交叉检查器
references/                    原生工作流与工程知识库
references/delivery-layout.md  MB/SB/package 固定目录结构
references/resource-planning.md 资源盘点与人工确认流程
references/comment-policy.md    注释分级规范
references/confluence-verification.md 云端二次验证与降级
references/mcode-patterns.md     M 码 S29/R1/C38 标准写法
references/snapshots/          Confluence 离线快照
references/panming/            上游 MIT 知识快照
examples/                      格式示例与回归夹具
tests/                         unittest 测试
downloads/                     版本分发包与 SHA256
```

## 版本与授权

- 上游项目：[`LipsLee/syntec-lad-skill`](https://github.com/LipsLee/syntec-lad-skill)
  v0.2.2。本仓库在其基础上合入上述改动。
- 上游项目本体未声明 LICENSE；`references/panming/` 的知识快照为 MIT。
  商用或再分发前请与上游作者确认授权范围。
- 本工具仅用于对自有或已获授权设备的离线梯形图分析与生成；不点击编辑器
  界面、不上传 CNC、不修改控制器。

当前版本：`0.3.9p`。完整变更见 [CHANGELOG.md](CHANGELOG.md)。

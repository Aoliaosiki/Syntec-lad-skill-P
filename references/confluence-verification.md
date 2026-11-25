# Confluence 二次验证：接入、判据、降级

> 一句话结论：云端校验是第二证据源，不是门禁。
> 连不上时必须明确写「未联网云端验证」，不能默认本地结论等于最新规格。
>
> 本仓库为公开分发版，站点地址、cloudId、空间名和 page id 一律用占位符。
> 内部部署时在自己的本地副本里填入真实值，或让 agent 从客户端 MCP 配置里取，
> **不要把真实站点信息提交回公开仓库**。
>
> 本地真实值的存放位置：私有文件 `confluence-local.md`（已在 `.gitignore` 中）。
> 该文件不存在时，agent 只能靠已连接的 MCP 现场探测，探测失败就按 L1 降级。

---

## 1. 什么情况下值得查

不是每个任务都要打开 Confluence。命中以下任一条才查：

| 场景 | 查什么 |
|---|---|
| M 码 / 宏交接 | 该 M 码的功能定义、参数号、PLC 与宏的分工 |
| 报警文案 | 报警号段、三语措辞、触发条件 |
| 扩充参数 | Pr 编号、对应的 R 区、HMI 显示名 |
| 选配功能 | 是否标配、机型分叉、启用条件 |
| 客户特殊约定 | 现场 IO 点表、面板定义、互锁要求 |
| 旧程序改造 | 上一版验收记录、已知问题单 |

不查的情况：纯语法分析、地址范围检查、格式转换、本地已有一手点表的交付。

---

## 2. Agent 侧四步接入

工具名因客户端而异，按能力找工具，不按名字找。

### 第 1 步：能力探测

```text
searchConfluence(cql = 'type = page AND id = <page-id>', limit = 1)
```

- 返回 1 条：搜索可用；
- 返回 0 条但无报错：搜索可用、页面不可见（id 错或无权限）；
- 报错或 tool not found：直接进第 4 步降级，不要用 shell 抓网页替代。

### 第 2 步：读页探测

```text
getConfluenceContent(
  content_id = '<page-id>',
  content_format = 'markdown',
  detail = 'summary'
)
```

有 `version.number` 和 `lastModified` 才算 L2。
只有正文没有版本字段：受限 L2，记录里写「版本不可得」。

### 第 3 步：按主题检索与精读

1. 优先用 page id，不要猜 URL；
2. 只有标题时用 `title ~ "..."` 加 `space` 限定，先拿 id 再读；
3. 同一主题至少交叉 2 页（最新规格 + 最近验收），冲突时并列，不自行择一；
4. 只对规格/验收/改造页拉 `detail=full`。

### 第 4 步：落成本地快照

抓到页面后写到 `references/snapshots/`，文件名用页面 ID，头部固定格式：

```markdown
# 页面标题

| 项 | 值 |
|---|---|
| page id | `<page-id>` |
| version | `<version>` |
| lastModified | `<ISO-8601 timestamp>` |
| 拉取 | `getConfluenceContent` markdown / full |
```

头部三行是 `cloud-status` 解析的依据，缺了就只能算「无版本快照」。

---

## 3. 代码侧怎么接

工具本身不联网，只消费证据：

```bash
# 看当前能力级别（无快照时明确打印“未联网云端验证”）
python scripts/run_syntec_lad.py cloud-status

# 有快照时列出 page id / version / lastModified
python scripts/run_syntec_lad.py cloud-status --snapshots references/snapshots

# 交叉核对：文档提到但梯图未使用的地址
python scripts/run_syntec_lad.py crosscheck cnc.lad --snapshots references/snapshots

# agent 确实在线读过页面时，才加这个开关
python scripts/run_syntec_lad.py crosscheck cnc.lad --snapshots references/snapshots --cloud-online
```

输出约定：

| 情况 | 级别 | 输出 |
|---|---|---|
| MCP 实读成功且有版本 | L2 | Cloud : L2，已通过 Atlassian MCP 读取在线页面 |
| 只有本地快照 | L1+ | Cloud : L1+，仅有 N 份本地快照，未联网复核 |
| 什么都没有 | L1 | Cloud : L1，未联网云端验证，本次结论只基于本地文件 |
| 401/403 | L1 | 原因写「无权限」，不要重试到超时 |
| 超时 | L1 | 重试 1 次，仍失败写「网络失败」 |

`--cloud-online` 只能由实际调用过 MCP 并拿到返回的 agent 添加。
不要为了报告好看而加。

---

## 4. 交叉核对查什么

`compare_with_ladder` 只做一件事：快照里出现的地址，梯图里有没有。

| 发现 | 含义 | 处理 |
|---|---|---|
| 文档有、梯图无 | 可能漏实现，也可能文档写的是可选功能 | 列出来，人判断 |
| 梯图有、文档无 | 正常，文档不可能列全内部位 | 不报 |

报警号段、参数号这类强对应关系，用 `crosscheck` 的报警/参数检查，不要用地址比对代替。

---

## 5. 客户端适配

| 客户端 | 接入方式 | 工具名 | 注意 |
|---|---|---|---|
| Codex | 运行环境已注入 Atlassian MCP | `mcp__atlassian__searchConfluence` / `mcp__atlassian__getConfluenceContent` | 不要读 `config.toml`，工具不在列表里就直接判 L1 |
| Claude | MCP 设置里加 Atlassian remote MCP | 通常同为 `mcp__atlassian__*` | 首次 OAuth 后要重开会话 |
| CodeBuddy | MCP/插件设置里加 Atlassian，或市场里的连接器 | 可能无 `mcp__` 前缀 | 只有通用 search/fetch 时按「search 传 CQL、fetch 传 URL」适配 |
| WorkBuddy | 连接器/MCP/知识源里添加 Atlassian | 可能是封装后的 search/read_page | 只能读摘要时算受限 L2 |

认证由客户端管理，禁止把 Cookie、API Token、OAuth refresh token 写进技能、脚本或对话。

---

## 6. 降级输出模板

```text
Confluence 校验：未完成
能力级别：L1
原因：Atlassian MCP 未连接 / 无 <space> 读权限 / 页面 <page-id> 读取超时
已完成：本地 resource-report + lint + 交叉核对
待查：<page-id-a>（润滑点位）、<page-id-b>（报警号段）
结论：草案，不可直接交付
```

有快照但没联网：

```text
Confluence 校验：本地快照
能力级别：L1+
快照：<page-id> v<version> / <date>
说明：未联网复核，快照版本可能落后于在线页
```

---

## 7. 禁止事项

- 禁止把「账号能登录 Wiki」当成 L2，必须有工具返回；
- 禁止保存任何凭据；
- 禁止猜 page id、猜空间、猜 URL；
- 禁止 search 失败时用「通常/应该/大概」补规格；
- 禁止把整批页面正文灌进技能，只做索引、蒸馏和核心页快照；
- 禁止覆盖旧结论不标变更点，冲突必须并列。

# 快照层说明

`snapshots/<page-id>.md` 保存核心 Confluence 页的离线摘录，用于断网追溯和版本比对。

## 头部格式（必须）

```markdown
# 页面标题

| 项 | 值 |
|---|---|
| page id | `<page-id>` |
| version | `<version>` |
| lastModified | `<ISO-8601 timestamp>` |
| 拉取 | `getConfluenceContent` markdown / full |
```

`cloud-status` 只读前 40 行里的两列表格，所以头部要放在最前面。

## 收录原则

- 只快照「规格 / 验收 / 改造 / 官方语法」页；
- 现场流水页、日报页不入快照；
- 一份快照只对应一个 page id，文件名就是 page id；
- 正文含图片/附件时，在头部加一行说明 `lossyConversion`，不要假装是全文。

## 当前快照

| page id | 标题 | version | lastModified | 类型 |
|---|---|---:|---|---|
| （暂无） | | | | |

## 与在线页的关系

快照不替代在线页。交付前若页面版本已变：

1. 以在线页为准；
2. 更新快照的 version / lastModified；
3. 在交付说明里写出「快照版本 vs 在线版本」。

## 与 macro 技能的关系

macro 技能的 `syntec-macro/references/snapshots/` 有同一站点的快照。
两边 page id 可以互相引用，但**不要跨技能复制结论**：
同一参数号在宏和 PLC 里含义可能不同，引用前先看快照归属。

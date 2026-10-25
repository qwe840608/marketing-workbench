# 领域文档

> **语言 / Language / 語言 / 言語**：[繁體中文](domain_zh-TW.md) | 简体中文 | [English](domain.md) | [日本語](domain_ja.md)

工程类 skills 在探索代码库时应如何使用本 repo 的领域文档。

## 探索前先读这些

- repo 根目录的 **`CONTEXT.md`**，或
- 若 repo 根目录有 **`CONTEXT-MAP.md`**：它指向每个上下文各自的 `CONTEXT.md`。读取与主题相关的每一份。
- **`docs/adr/`**：读取涉及你即将处理的区域的 ADR。在多上下文的 repo 中，也要检查 `src/<context>/docs/adr/` 中属于特定上下文的决策。

如果这些文件不存在，**直接继续，不必提及**。不要指出它们缺失，也不要预先建议创建。`/domain-modeling` skill（通过 `/grill-with-docs` 与 `/improve-codebase-architecture` 调用）会在术语或决策真正确定时才按需创建它们。

## 文件结构

单一上下文的 repo（大多数 repo）：

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-event-sourced-orders.md
│   └── 0002-postgres-for-write-model.md
└── src/
```

多上下文的 repo（根目录存在 `CONTEXT-MAP.md`）：

```
/
├── CONTEXT-MAP.md
├── docs/adr/                          ← system-wide decisions
└── src/
    ├── ordering/
    │   ├── CONTEXT.md
    │   └── docs/adr/                  ← context-specific decisions
    └── billing/
        ├── CONTEXT.md
        └── docs/adr/
```

## 使用术语表的用词

当你的输出提到某个领域概念（在 issue 标题、重构提案、假设、测试名称中）时，使用 `CONTEXT.md` 中定义的术语。不要改用术语表明确避免的同义词。

如果你需要的概念还不在术语表中，这是一个信号：要么你在发明项目不使用的说法（请重新考虑），要么确实存在缺口（记下来交给 `/domain-modeling`）。

## 标出与 ADR 的冲突

如果你的输出与现有的 ADR 相矛盾，要明确指出，而不是悄悄推翻：

> _与 ADR-0007（event-sourced orders）相矛盾，但值得重新讨论，因为……_

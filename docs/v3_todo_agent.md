# v3: Todo Agent 任务驱动执行

**~500 行代码，5 个工具，把“计划”变成可验证的执行状态。**

v2 的多工具能力已经够用，但面对长链路任务，模型仍可能在多轮后丢失节奏。

`v3_todo_agent_demo/todo_agent.py` 的核心改动是：引入强约束的 `todo_write` 工具和 `TodoManager`，把“我准备做什么”从隐式思考变成显式、可校验、可追踪的数据结构。

## 核心变化

v3 在 v2 的 4 个工具基础上新增：

- `todo_write`：完整更新任务列表
- `TodoManager`：统一校验与渲染任务状态
- Reminder 机制：在关键时机提醒模型更新 todo

工具集合变为：

- `bash`
- `read_file`
- `write_file`
- `edit_file`
- `todo_write`

## TodoManager 约束设计

`TodoManager.update()` 会校验模型传入的完整 `items` 列表，并强制规则：

- 每个条目必须包含 `content`、`status`、`activeForm`
- `status` 只能是 `pending | in_progress | completed`
- 同时最多只能有 1 个 `in_progress`
- 总条目数最多 20

这几条规则对应代码中的真实校验逻辑，违反即返回错误，避免计划失控或状态混乱。

## todo_write 的输入与返回

`todo_write(items)` 接收“完整新列表”，不会做增量 patch。调用成功后返回渲染文本，例如：

```text
- [✅] Read existing code
- [>] Implement todo constraints <- (Implementing todo validation)
- [ ] Add regression checks
(1/3 items completed)
```

其中：

- `completed` 显示为 `[✅]`
- `in_progress` 显示为 `[>]`，并附带 `activeForm`
- `pending` 显示为 `[ ]`

## Reminder 注入策略

v3 增加了两条系统提醒：

- `INITIAL_REMINDER`：会话初期提醒使用 todo
- `NAG_REMINDER`：若 assistant 连续 10+ 轮未调用 `todo_write`，再次提醒

实现方式是：每轮请求前将提醒作为 system message 注入 `messages`，属于软约束，不会中断主循环。

## 主循环行为

`chat()` 的执行流程：

1. 构建 `messages`（系统提示 + reminder + history）
2. 调用 `LLM_SERVER.chat.completions.create(...)`
3. 若返回工具调用，则逐个执行并把 tool result 追加进 `history`
4. 若无工具调用，返回最终文本

与 v2 相比，循环结构保持一致，新增的关键是 todo 状态被写入对话历史并持续反馈给模型。

## 与 v4 的边界

v3 只有单代理，不包含子代理编排。

- v3 关注“显式任务状态与执行纪律”
- v4 才引入 `Task` 子代理与多角色协作

如果你要先稳定任务拆解与跟踪，再升级到上下文隔离的多代理流程，v3 是必要过渡层。

## 适用场景

v3 最适合：

- 需要连续多步执行的任务
- 希望实时看到当前进行项的场景
- 需要约束模型避免“开很多坑不收尾”的流程

不太适合：

- 一步可完成的简单查询
- 不需要状态可视化的短任务

---

**v3 的本质：让模型“边做边维护状态”，而不是只在脑中计划。**

[← v2](./v2_basic_agent_demo.md) | [返回 README](../README.md)

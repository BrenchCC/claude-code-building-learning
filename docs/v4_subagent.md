# v4: Subagent 编排与上下文隔离

**~700 行代码，6 个工具，在 todo 驱动下实现主代理 + 子代理协作。**

`v4_subagent_demo/subagent.py` 是当前版本的完整实现：在 v3 的 `todo_write` 约束上新增 `Task` 工具，把复杂任务拆成可隔离执行的子任务。

## 核心能力

v4 的工具集合：

- `bash`
- `read_file`
- `write_file`
- `edit_file`
- `todo_write`
- `Task`

相比 v3，核心增量是 `Task` 与子代理执行循环；同时保留 v3 的 todo 机制与提醒策略。

## 代理类型注册表

通过 `AGENT_TYPE_REGISTRY` 定义子代理能力：

- `explore`：只读探索（`bash`, `read_file`）
- `plan`：只读规划（`bash`, `read_file`）
- `code`：实现代理（`*`，允许完整实现能力）

每类都绑定：

- `description`
- `tools`
- `system_prompt`

这样主代理可以按子任务性质选择最合适的执行角色。

## 工具过滤与递归控制

`get_tool_for_agent(agent_type)` 会根据类型筛选工具。

关键细节：

- `explore/plan` 只拿到只读工具
- `code` 使用 `*` 时会自动排除 `Task`

排除 `Task` 的目的很明确：避免子代理继续递归生成子代理，降低失控风险。

## Task 执行流程

`Task` 参数：

- `agent_type`
- `task_description`
- `prompt`

调用路径：

1. 主代理收到 `Task` 调用
2. `run_task(...)` 创建子代理隔离上下文（独立 `sub_messages`）
3. 子代理在自己的 system prompt + 受限工具下循环执行
4. 子代理只返回摘要文本给主代理

主代理拿到摘要后继续主线任务，避免把子代理完整探索过程塞满主上下文。

## Todo 机制（延续 v3）

`TodoManager` 约束保持不变：

- 每项必须包含 `content/status/activeForm`
- `status` 仅允许 `pending|in_progress|completed`
- 同时最多一个 `in_progress`
- 最多 20 项

`todo_write` 每次都要求传完整列表，并返回渲染结果（含总进度行）。

## Reminder 与回合上限

v4 在主循环中同时使用软提醒和硬上限：

- `INITIAL_REMINDER`：会话初期提醒使用 `todo_write`
- `NAG_REMINDER`：assistant 连续 10+ 轮未更新 todo 时提醒
- `MAX_MAIN_ROUNDS = 40`：主代理最大轮数
- `MAX_SUBAGENT_ROUNDS = 30`：子代理最大轮数

这套机制能减少“忘记更新状态”和“重复工具调用卡住”两类常见问题。

## 容错与可观测性

v4 额外加入两层健壮性：

- `_parse_tool_args()`：对 JSON 参数做清洗和容错解析
- `_safe_call_tool()`：统一捕获参数错误与运行时异常

同时 `run_task()` 会输出子代理进度（工具调用数 + 耗时），`todo_write` 会打印最新任务列表，便于 CLI 直接观察执行状态。

## 与 v3 的差异

- v3：单代理 + todo 任务管理
- v4：主代理编排 + 子代理隔离 + todo 管理 + 回合上限保护

v3 适合中等复杂任务；v4 适合需要“探索/规划/实现”分工的大任务。

---

**v4 的本质：把“任务拆解”和“上下文隔离”变成默认执行策略。**

[← v3](./v3_todo_agent.md) | [返回 README](../README.md)

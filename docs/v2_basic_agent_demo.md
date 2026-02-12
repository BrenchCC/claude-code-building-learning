# v2: Basic Agent 多工具执行

**~400 行代码，4 个核心工具，把 bash-only Agent 升级为可维护的文件操作代理。**

`v2_basic_agent_demo/basic_agent.py` 在 v1 循环基础上，重点升级为“结构化工具层”：

- `bash`
- `read_file`
- `write_file`
- `edit_file`

模型仍然通过同一个循环工作，但现在可以直接用工具完成读写与精确编辑，不必把所有动作都塞进 shell 命令。

## 核心改动

相对 v1，v2 的关键收益：

- 文件操作有了专用 API（读/写/替换）
- 路径统一按 `WORKSPACE` 解析
- `edit_file` 会在替换前创建 `.bak` 备份
- 保留 `bash` 作为通用兜底执行入口

## 工具行为对齐代码

### `bash(command)`

- 在 `WORKSPACE` 下执行命令
- 超时 300 秒返回 `returncode = 124`
- 返回 `stdout`、`stderr`、`returncode`

### `read_file(file_path, max_lines = 1000)`

- 支持相对路径与绝对路径
- 默认最多读取 1000 行
- 返回 `{"content": ...}`

### `write_file(file_path, content)`

- 自动创建父目录
- 直接覆盖写入
- 返回 `{"status": "ok"}`

### `edit_file(file_path, old_content, new_content)`

- 若找不到 `old_content`，返回 `{"status": "not_found"}`
- 命中后先写入备份 `*.bak`
- 完成替换后返回 `{"status": "ok", "backup_path": ...}`

## 对话循环

v2 仍是标准 Agent loop：

1. 组装 `messages`（系统提示 + 历史）
2. 请求模型并附带 `TOOLS`
3. 若模型返回工具调用，执行后将 tool result 追加到 `history`
4. 若无工具调用，输出最终文本

这个循环不复杂，但已能稳定覆盖大部分“读代码 -> 改代码 -> 验证”的任务。

## CLI 模式

`basic_agent.py` 支持两种运行方式：

- 单轮：`python v2_basic_agent_demo/basic_agent.py "你的任务"`
- 交互：`python v2_basic_agent_demo/basic_agent.py`

并通过 `parse_args()` 统一参数解析。

## 与 v3 的边界

v2 不包含 todo 追踪能力：

- 没有 `todo_write`
- 没有任务状态约束
- 没有 reminder 注入

v3 才在 v2 工具层之上加入任务拆解与进度管理。

---

**v2 的本质：在不改变主循环的前提下，用结构化工具提升可控性与可维护性。**

[← v1](./v1_bash_is_everything.md) | [返回 README](../README.md) | [v3 →](./v3_todo_agent.md)

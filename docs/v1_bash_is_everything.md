# v1: Bash 就是一切

**终极简化：~50 行代码，1 个工具，也能跑出完整 Agent 闭环。**

基于 `v2_basic_agent_demo` 可以看得更清楚：Agent 的本质不是“工具数量”，而是“循环结构”。
v2 用 4 个工具覆盖大多数开发任务；v1 再往前一步，把入口收敛到一个：`bash`。

## 核心洞察

Unix 哲学里，一切皆文件，一切皆可管道。`bash` 是统一入口：

| 你需要 | Bash 命令 |
|--------|-----------|
| 读文件 | `cat`, `head`, `grep` |
| 写文件 | `echo '...' > file` |
| 搜索 | `find`, `grep`, `rg` |
| 执行程序 | `python`, `npm`, `make` |
| 调子代理 | `python v1_bash_agent_demo/bash_agent.py "task"` |

关键点在最后一行：**通过 bash 调用自身，就有了子代理能力**。不需要额外的 registry 或调度框架，递归即可形成层级。

## 最小 Agent 循环

和 v2 一样，核心仍是同一个循环：模型决策，工具执行，结果回填，再次决策。

```python
while True:
    response = model(messages, tools)
    if response.stop_reason != "tool_use":
        return response.text
    results = execute(response.tool_calls)
    messages.append(results)
```

只要这段循环成立，Agent 就成立。  
在 v1 中，`tools` 只有一个 `bash`；在 v2 中，`tools` 扩展为 `bash/read_file/write_file/edit_file`。

## 子代理如何自然出现

```
主代理
  └─ bash: python v1_bash_agent_demo/bash_agent.py "分析架构"
       └─ 子代理（独立进程，全新 history）
            ├─ bash: find . -name "*.py"
            ├─ bash: cat src/main.py
            └─ stdout 返回给父代理
```

`subprocess` 拉起新进程时，天然获得：
- 独立消息历史（上下文隔离）
- 独立执行生命周期（失败不会污染父循环）
- 文本化输出接口（stdout 直接回填为 tool result）

一句话：**进程隔离就是上下文隔离**。

## 对照 v2：少了什么，多了什么

| 维度 | v1 (bash-only) | v2 (4 tools) |
|------|----------------|--------------|
| 学习成本 | 最低 | 低 |
| 可控编辑 | 依赖 shell 命令 | 原生读写/编辑 |
| 鲁棒性 | 偏提示词约束 | 更结构化 |
| 可解释性 | 极简、直观 | 更接近生产形态 |

v1 不是“过时版本”，而是“最小可证明版本”：它证明 Agent 能力可以从极小规则中涌现。

## 实现位置与运行前提

- 代码：`v1_bash_agent_demo/bash_agent.py`
- Prompt：`prompts/v1_bash_agent.md`（会注入当前工作目录）
- 环境变量：`LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`（见 `.env`）

---

**Bash 就是一切。先让循环跑起来，再谈功能分层。**

[← 返回 README](../README.md)

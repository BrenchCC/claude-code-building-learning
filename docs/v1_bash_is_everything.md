# v1: Bash 就是一切

**终极简化：~50 行代码，1 个工具，Agent 能力像“搭积木”一样自然长出来。**

在构建 v1、v2、v3 之后，一个问题浮现：Agent 的*本质*到底是什么？

v1 通过反向思考来回答——像削铅笔一样，一层层削掉装饰，直到只剩下最锋利的芯。

## 核心洞察

Unix 哲学：一切皆文件，一切皆可管道。Bash 是这个世界的入口，也是 Agent 的“万能开关”：你只要会开关，就能驱动一切。

| 你需要 | Bash 命令 |
|--------|-----------|
| 读文件 | `cat`, `head`, `grep` |
| 写文件 | `echo '...' > file` |
| 搜索 | `find`, `grep`, `rg` |
| 执行 | `python`, `npm`, `make` |
| **子代理** | `python v1_bash_agent_demo/bash_agent.py "task"` |

最后一行是关键洞察：**通过 bash 调用自身就实现了子代理**。这就像在镜子里再放一面镜子，层层映射，层层展开。不需要 Task 工具，不需要 Agent Registry——只需要递归。

## 关键实现（对应本仓库 v1 代码）

只保留最小循环骨架，完整实现见 `v1_bash_agent_demo/bash_agent.py`。这段骨架像“心跳”，每一次跳动都完成一次：提问、执行、反馈、再提问。

```python
while True:
    response = model(messages, tools)
    if response.stop_reason != "tool_use":
        return response.text
    results = execute(response.tool_calls)
    messages.append(results)
```

补充说明：

- System Prompt 来自 `prompts/v1_bash_agent.md`，并会动态注入当前工作目录
- 运行依赖 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL` 环境变量（见 `.env`）

## 子代理工作原理

```
主代理
  └─ bash: python v1_bash_agent_demo/bash_agent.py "分析架构"
       └─ 子代理（独立进程，全新历史）
            ├─ bash: find . -name "*.py"
            ├─ bash: cat src/main.py
            └─ 通过 stdout 返回摘要
```
```
参与者:
User         Parent Agent (PID 1001)           OS          Subagent (PID 2002)           LLM Service

  |                   |                         |                  |                        |
  |  提问: "分析架构"  |                         |                  |                        |
  |------------------>|  chat()                 |                  |                        |
  |                   |  LLM(...)               |                  |                        |
  |                   |------------------------>|                  |                        |
  |                   |  生成工具调用: bash     |                  |                        |
  |                   |  cmd = python ...       |                  |                        |
  |                   |  subprocess.run(...)    |                  |                        |
  |                   |------------------------>|  spawn new proc  |                        |
  |                   |                         |----------------->|  启动脚本 main()       |
  |                   |                         |                  |  chat() history = []   |
  |                   |                         |                  |  LLM(...)              |
  |                   |                         |                  |----------------------->|
  |                   |                         |                  |  得到行动/结果         |
  |                   |                         |                  |  print(stdout)         |
  |                   |                         |<-----------------|  stdout返回             |
  |                   |  capture_output         |                  |                        |
  |                   |  结果作为 tool_result   |                  |                        |
  |                   |  继续对话               |                  |                        |
  |<------------------|  最终回答               |                  |                        |
```

**进程隔离 = 上下文隔离**。每个子进程像一间独立的小实验室，门一关，历史就被隔离开。
- 子进程有自己的 `history=[]`
- 父进程捕获 stdout 作为工具结果
- 递归调用实现无限嵌套

时序图（主进程 ↔ 子进程）：

```text
参与者:
User         Parent Agent (PID 1001)           OS          Subagent (PID 2002)           LLM Service

  |                   |                         |                  |                        |
  |  提问: "分析架构"  |                         |                  |                        |
  |------------------>|  chat()                 |                  |                        |
  |                   |  LLM(...)               |                  |                        |
  |                   |------------------------>|                  |                        |
  |                   |  生成工具调用: bash     |                  |                        |
  |                   |  cmd = python ...       |                  |                        |
  |                   |  subprocess.run(...)    |                  |                        |
  |                   |------------------------>|  spawn new proc  |                        |
  |                   |                         |----------------->|  启动脚本 main()       |
  |                   |                         |                  |  chat() history = []   |
  |                   |                         |                  |  LLM(...)              |
  |                   |                         |                  |----------------------->|
  |                   |                         |                  |  得到行动/结果         |
  |                   |                         |                  |  print(stdout)         |
  |                   |                         |<-----------------|  stdout返回             |
  |                   |  capture_output         |                  |                        |
  |                   |  结果作为 tool_result   |                  |                        |
  |                   |  继续对话               |                  |                        |
  |<------------------|  最终回答               |                  |                        |
```

一句话：上下文隔离来自本地进程隔离，模型服务可以共享，但每次请求的 `messages` 由各自进程独立构建。

## v1 牺牲了什么

| 特性 | v1 | v3 |
|------|----|----|
| 代理类型 | 无 | explore/code/plan |
| 工具过滤 | 无 | 白名单 |
| 进度显示 | 普通 stdout | 行内更新 |
| 代码复杂度 | ~170 行 | ~450 行 |

## v1 证明了什么

**复杂能力从简单规则中涌现：**像河流由无数水滴组成，能力由无数个“简单回路”叠出来。

1. **一个工具足够** — Bash 是通往一切的入口
2. **递归 = 层级** — 自我调用实现子代理
3. **进程 = 隔离** — 操作系统提供上下文分离
4. **提示词 = 约束** — 指令塑造行为

核心模式从未改变：就像发动机的四冲程，换了外壳，循环还在。

```python
while True:
    response = model(messages, tools)
    if response.stop_reason != "tool_use":
        return response.text
    results = execute(response.tool_calls)
    messages.append(results)
```

其他一切——待办、子代理、权限——都是围绕这个循环的精化与装配。

---

**Bash 就是一切。**

[← 返回 README](../README.md)

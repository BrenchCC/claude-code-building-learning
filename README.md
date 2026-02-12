# nano-claude-code - Learn Claude Code

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)

一个用于学习如何构建类似 Claude Code 的 Nano CLI Agent 的项目。通过从零开始搭建，你将理解 LLM Agent 的核心原理与架构，并能独立扩展自己的 Agent。

这个仓库来自我对 Claude Code、codex 等 coding agent 产品的持续使用与复盘。过去半年在不断构建和迭代 Agent 系统的过程中，我对“什么才是真正的 AI Agent”有了新的认知。

你将学到的关键能力：
- Agent 循环：AI 编程代理背后的简单而有效的模式
- 工具设计：让模型与真实世界交互的方式
- 显式规划：使用约束让行为更可预测
- 上下文管理：通过子代理隔离保持记忆干净
- 知识注入：按需加载领域知识而非重新训练

## 适合人群

- 想理解 LLM Agent 基本工作原理的开发者
- 想构建可扩展的 CLI Agent 原型的学习者
- 对工具调用、系统提示与上下文管理感兴趣的人

## 项目结构

```
.
├── v1_bash_agent_demo/          # V1 版本：仅支持 Bash 工具的简单 Agent
├── v2_basic_agent_demo/         # V2 版本：支持多个工具的基础 Agent
├── prompts/                     # 系统提示文件目录
├── examples/                    # 使用示例
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量示例
├── v3_todo_agent_demo/          # V3 版本：引入 Todo 任务管理的进阶 Agent
├── v4_subagent_demo/            # V4 版本：支持子代理编排的多代理 Agent
└── LICENSE                      # MIT 许可证
```

## Agent 版本演进

### V1 - Bash Agent（最简单版本）

文件：`v1_bash_agent_demo/bash_agent.py`

特点：
- 仅支持一个工具：Bash 命令执行
- 架构简单，适合入门
- 支持单轮和交互式对话
- 使用 OpenAI 兼容 API

核心功能示意：
```python
# 工具定义
TOOL = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute shell command. Common patterns include: read, write, subagent",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"],
            },
        },
    }
]

# 对话循环
def chat(prompt: str = None, history: List = None):
    while True:
        response = LLM_SERVER.chat.completions.create(...)
        if llm_response.tool_calls:
            results = []
            for tool_call in llm_response.tool_calls:
                if tool_call.function.name == "bash":
                    output = subprocess.run(...)
                    results.append(...)
            history.extend(results)
        else:
            return llm_response.content
```

### V2 - Basic Agent（基础版本）

文件：`v2_basic_agent_demo/basic_agent.py`

特点：
- 支持多个工具：Bash、Read File、Write File、Edit File
- 工具独立实现，架构更完整
- 更好的错误处理与日志记录
- 支持文件操作工具

新增工具示意：
```python
# Read File 工具
def read_file(file_path: str, max_lines: int = 1000) -> dict:
    path = Path(file_path)
    with path.open("r") as file:
        content = "".join(file.readline() for _ in range(max_lines))
    return {"content": content}

# Write File 工具
def write_file(file_path: str, content: str) -> dict:
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as file:
        file.write(content)
    return {"status": "ok"}

# Edit File 工具
def edit_file(file_path: str, old_content: str, new_content: str) -> dict:
    text = path.read_text()
    if old_content not in text:
        return {"status": "not_found"}
    updated = text.replace(old_content, new_content)
    path.write_text(updated)
    return {"status": "ok"}
```

### V3 - Todo Agent（带任务管理的进阶版本）

文件：`v3_todo_agent_demo/todo_agent.py`

特点：
- 新增 `TodoWrite` 工具，要求模型在多步骤任务中显式规划
- 强约束：最多 20 个任务项、同时只能有 1 个 `in_progress`
- 通过 `activeForm` 实时显示正在做的动作
- 加入软提醒机制：如果多轮未更新 Todo，会提示模型更新

Todo 列表示意：
```text
- [ ] 收集需求
- [>] 撰写 README 说明 <- (Writing README guidance...)
- [✅] 读取现有代码
(1/3 items completed)
```

适合用法：
- 需要连续 3 步以上的复杂任务
- 需要“可见的计划 + 可追踪的进度”
- 想观察模型如何拆解任务并持续更新状态

### V4 - Subagent Agent（多代理协作版本）

文件：`v4_subagent_demo/subagent.py`

特点：
- 新增 `Task` 工具，可按 `explore | code | plan` 三类子代理拆分复杂任务
- 主代理与子代理使用隔离上下文，降低长任务中的上下文污染
- 子代理支持按类型限制工具权限，减少无关调用
- 保留并强化 `todo_write` 约束，支持主循环提醒与进度追踪
- 增加主循环/子循环轮数上限，降低重复调用风险

适合用法：
- 需要并行/分治处理的复杂代码分析与实现任务
- 希望把“探索、规划、编码”职责显式分离的场景
- 想验证多代理编排在可维护性与稳定性上的收益

## 快速开始

### 1. 克隆仓库
```bash
git clone https://github.com/BrenchCC/claude-code-building-learning
cd claude-code-building-learning
```

### 2. 环境设置

创建 `.env` 文件：
```bash
cp .env.example .env
```

编辑 `.env`，配置你的 LLM 服务器信息：
```env
LLM_BASE_URL=http://localhost:11434/v1  # 例如：Ollama 本地服务器
LLM_API_KEY=ollama                     # Ollama 的 API Key 固定为 ollama
LLM_MODEL=llama3:latest                # 你要使用的模型
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 运行 Agent

单轮模式：
```bash
python v1_bash_agent_demo/bash_agent.py "列出当前目录内容"
python v2_basic_agent_demo/basic_agent.py "读取 README.md 文件并总结内容"
python v3_todo_agent_demo/todo_agent.py "请规划并完成一个小型重构任务"
python v4_subagent_demo/subagent.py "请先规划，再调用子代理完成一次项目代码质量评估"
```

交互式模式：
```bash
python v1_bash_agent_demo/bash_agent.py
python v2_basic_agent_demo/basic_agent.py
python v3_todo_agent_demo/todo_agent.py
python v4_subagent_demo/subagent.py
```

## 核心概念

### 1. 工具定义

每个工具需要定义：
- `name`：工具名称
- `description`：工具功能描述（帮助 LLM 理解何时使用）
- `parameters`：工具参数的 JSON Schema 定义

### 2. 对话循环

核心架构模式：
```python
while True:
    1. 发送消息给 LLM（包含系统提示、对话历史、工具定义）
    2. 解析 LLM 响应
    3. 如果是工具调用：
        - 执行工具
        - 收集结果
        - 将结果加入对话历史
        - 继续循环
    4. 如果是最终响应：返回结果
```

### 3. 系统提示

系统提示是 Agent 的“大脑”，定义行为准则。

V1 系统提示示例：`prompts/v1_bash_agent.md`
```markdown
You are a helpful AI programming assistant.

## Rules
1. Solve the user's problem step by step
2. Use bash to get necessary information
3. Verify each step works before proceeding
```

### 4. Todo 任务管理（V3）

V3 引入 `TodoWrite` 工具，让模型必须“列计划、标进度”。  
它解决了两个常见问题：
- 模型容易一次性输出大段方案，缺少执行过程
- 多步骤任务容易丢上下文、重复或偏离目标

约束规则（由工具强制校验）：
- 最多 20 项
- `pending | in_progress | completed` 三种状态
- 同一时间只允许 1 个 `in_progress`
- 每项必须包含 `activeForm`（进行时描述）

建议的使用方式：
- 提示中明确要求“先拆分任务，再逐步执行”
- 如果任务复杂，让模型先用 `TodoWrite` 写出计划
- 每完成一个子任务就更新 Todo

## 扩展你的 Agent

### 添加新工具

需要完成三步：
1. 在 `TOOL` 列表中添加工具定义
2. 实现工具函数
3. 在 `chat()` 函数中添加调用逻辑

示例：添加列出目录工具
```python
# 1. 工具定义
{
    "type": "function",
    "function": {
        "name": "list_dir",
        "description": "List directory contents",
        "parameters": {
            "type": "object",
            "properties": {
                "dir_path": {"type": "string", "description": "Directory path to list"}
            },
            "required": ["dir_path"],
        },
    },
}

# 2. 工具函数
def list_dir(dir_path: str) -> dict:
    files = os.listdir(dir_path)
    return {"files": files}

# 3. 调用逻辑（在 chat() 中）
elif tool_name == "list_dir":
    output = list_dir(**args)
```

### 改进系统提示

你可以通过修改 `prompts/` 目录下的文件来：
- 改变 Agent 的性格
- 添加特定领域知识
- 改进问题解决策略

## 学习路径

1. 从 V1 开始：理解基本架构和对话循环
2. 学习 V2：掌握工具扩展和错误处理
3. 尝试 V3：观察 Todo 约束如何改变模型行为
4. 尝试 V4：体验子代理任务拆分与上下文隔离
5. 尝试扩展：添加你自己的工具
6. 优化提示：改进系统提示以获得更好的结果
7. 高级功能探索：多工具扩展、多 Agent 协作、记忆能力、工具调用校验

## 常见问题

### 1. LLM 不调用工具怎么办？

- 检查系统提示是否明确说明工具用途
- 确保工具描述足够详细
- 调整用户提示，更明确地请求工具使用

### 2. 工具执行失败怎么办？

- 添加更详细的错误处理
- 在系统提示中说明错误处理策略
- 实现重试机制

### 3. 如何提高 Agent 的代码质量？

- 完善错误处理
- 添加类型注解
- 提高系统提示的详细程度
- 实现工具使用的验证机制

## 技术栈

- Python 3.10+
- OpenAI API（兼容 Ollama 等本地服务器）
- python-dotenv
- ANSI 颜色输出

## 许可证

MIT License - 详见 `LICENSE`

## 下一步

1. 运行示例代码，观察 Agent 的行为
2. 修改系统提示，改变 Agent 的行为方式
3. 添加一个新工具（如 `list_dir` 或 `download_file`）
4. 用 V3 尝试一个复杂任务，观察 Todo 机制的效果
5. 用 V4 尝试一次“计划 + 子代理执行”的完整流程
6. 尝试不同的 LLM 模型，比较它们的表现

祝你学习愉快！

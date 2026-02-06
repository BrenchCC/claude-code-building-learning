# nano-claude-code - 构建 CLI Agent 的学习项目

这是一个用于学习如何构建类似 Claude Code 的Nano CLI Agent 的项目。包含从简单到复杂的多个 Agent 实现版本，帮助您理解 LLM Agent 的核心原理和架构。

## 项目目标

通过学习本项目，您将能够：
- 理解 LLM Agent 的基本工作原理
- 掌握如何构建能够执行外部命令的 CLI Agent
- 学习如何为 Agent 添加工具调用能力
- 了解如何实现交互式和单轮对话模式
- 掌握系统提示（System Prompt）的设计方法

## 项目结构

```
.
├── v1_bash_agent_demo/          # V1 版本：仅支持 Bash 工具的简单 Agent
├── v2_basic_agent_demo/         # V2 版本：支持多个工具的基础 Agent
├── prompts/                     # 系统提示文件目录
├── examples/                    # 使用示例
├── requirements.txt             # Python 依赖
├── .env.example                 # 环境变量示例
└── LICENSE                      # MIT 许可证
```

## Agent 版本演进

### V1 - Bash Agent (最简单版本)

**文件**：[v1_bash_agent_demo/bash_agent.py](v1_bash_agent_demo/bash_agent.py)

**特点**：
- 仅支持一个工具：Bash 命令执行
- 简单的架构，适合初学者学习
- 支持单轮和交互式对话模式
- 使用 OpenAI 兼容的 API

**核心功能**：
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
            }
        }
    }
]

# 对话循环
def chat(prompt: str = None, history: List = None):
    while True:
        response = LLM_SERVER.chat.completions.create(...)
        if llm_response.tool_calls:
            # 执行工具调用
            results = []
            for tool_call in llm_response.tool_calls:
                if tool_call.function.name == "bash":
                    output = subprocess.run(...)
                    results.append(...)
            history.extend(results)
        else:
            return llm_response.content
```

### V2 - Basic Agent (基础版本)

**文件**：[v2_basic_agent_demo/basic_agent.py](v2_basic_agent_demo/basic_agent.py)

**特点**：
- 支持多个工具：Bash、Read File、Write File、Edit File
- 更完整的架构，工具独立实现
- 更好的错误处理和日志记录
- 支持文件操作工具

**新增工具**：
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

## 快速开始

### 1. 环境设置

**创建 .env 文件**：
```bash
cp .env.example .env
```

**编辑 .env 文件**，配置您的 LLM 服务器信息：
```env
LLM_BASE_URL=http://localhost:11434/v1  # 例如：Ollama 本地服务器
LLM_API_KEY=ollama                     # Ollama 的 API Key 固定为 ollama
LLM_MODEL=llama3:latest                # 您要使用的模型
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行 Agent

#### 单轮模式

**V1 Bash Agent**：
```bash
python v1_bash_agent_demo/bash_agent.py "列出当前目录内容"
```

**V2 Basic Agent**：
```bash
python v2_basic_agent_demo/basic_agent.py "读取 README.md 文件并总结内容"
```

#### 交互式模式

**V1 Bash Agent**：
```bash
python v1_bash_agent_demo/bash_agent.py
```

**V2 Basic Agent**：
```bash
python v2_basic_agent_demo/basic_agent.py
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

系统提示是 Agent 的"大脑"，定义了 Agent 的行为准则。

**V1 系统提示示例**（[prompts/v1_bash_agent.md](prompts/v1_bash_agent.md)）：
```markdown
You are a helpful AI programming assistant.

## Rules
1. Solve the user's problem step by step
2. Use bash to get necessary information
3. Verify each step works before proceeding
```

## 扩展您的 Agent

### 添加新工具

要添加新工具，需要：

1. 在 `TOOL` 列表中添加工具定义
2. 实现工具函数
3. 在 `chat()` 函数中添加调用逻辑

**示例：添加列出目录工具**
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
            "required": ["dir_path"]
        }
    }
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

系统提示是 Agent 行为的关键。您可以通过修改 `prompts/` 目录下的文件来：
- 改变 Agent 的性格
- 添加特定领域知识
- 改进问题解决策略

## 学习路径

1. **从 V1 开始**：理解基本架构和对话循环
2. **学习 V2**：掌握工具扩展和错误处理
3. **尝试扩展**：添加您自己的工具
4. **优化提示**：改进系统提示以获得更好的结果
5. **高级功能**：
   - 添加更多工具类型（API 调用、数据库操作等）
   - 实现多 Agent 协作
   - 添加记忆功能
   - 优化工具调用的解析和执行

## 常见问题

### 1. LLM 不调用工具怎么办？

- 检查系统提示是否明确说明了工具的用途
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

- **Python 3.10+**：主要开发语言
- **OpenAI API**：LLM 通信（兼容 Ollama 等本地服务器）
- **python-dotenv**：环境变量管理
- **颜色输出**：使用 ANSI 颜色代码提升用户体验

## 许可证

MIT License - 详见 LICENSE 文件

## 下一步

现在您已经了解了基础架构，尝试：
1. 运行示例代码，观察 Agent 的行为
2. 修改系统提示，改变 Agent 的行为方式
3. 添加一个新工具（如 `list_dir` 或 `download_file`）
4. 尝试不同的 LLM 模型，比较它们的表现

祝您学习愉快！

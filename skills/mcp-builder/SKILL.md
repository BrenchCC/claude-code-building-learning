---
name: mcp-builder
description: 构建 MCP（模型上下文协议）服务器，为 Codex/Claude 提供新功能。当用户想要创建 MCP 服务器、注册到 Codex 或集成外部服务时使用。
---

# MCP 服务器构建技能

你现在具备了构建 MCP（Model Context Protocol）服务器的专业知识。MCP 让模型通过标准协议访问外部工具、资源与提示模板。

## 什么是 MCP？

MCP 服务器提供：
- **工具（Tools）**：模型可调用的函数（如 API 端点）
- **资源（Resources）**：模型可读取的数据（如文件或数据库记录）
- **提示（Prompts）**：可复用的提示模板

## 执行目标（默认）

当用户要求“做一个 MCP 并接入 Codex”时，默认按以下产出交付：
1. 最小可运行 MCP 服务器代码（Python 或 TypeScript）
2. 可直接执行的 Codex 注册命令（`codex mcp add ...`）
3. `config.toml` 备选配置
4. 验证步骤（`codex mcp list`、`codex mcp get`、`/mcp`）
5. 常见故障定位建议

## 快速入门：Python MCP 服务器

### 1. 项目设置（Conda 默认）

```bash
mkdir my-mcp-server && cd my-mcp-server

conda create -n my-mcp-env python=3.11 -y
conda activate my-mcp-env

pip install mcp
```

#### 备选方案：使用 venv（如需）

```bash
mkdir my-mcp-server && cd my-mcp-server
python3 -m venv venv && source venv/bin/activate

pip install mcp
```

### 2. 基本服务器模板

```python
#!/usr/bin/env python3
"""my_server.py - 一个简单的 MCP 服务器"""

from mcp.server import Server
from mcp.server.stdio import stdio_server

server = Server("my-server")

@server.tool()
async def hello(name: str) -> str:
    """向某人打招呼。

    Args:
        name: 要问候的名字
    """
    return f"你好，{name}!"

@server.tool()
async def add_numbers(a: int, b: int) -> str:
    """将两个数字相加。

    Args:
        a: 第一个数字
        b: 第二个数字
    """
    return str(a + b)

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write)

if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
```

### 3. 注册到 Codex（重点）

优先给出 CLI 方式；`config.toml` 作为可审阅/可版本化备选。

#### 方式 A：使用 Codex CLI（推荐）

1. 注册本地 STDIO 服务器：

```bash
codex mcp add my-server -- python3 /ABS/PATH/my_server.py
```

2. 如果需要环境变量：

```bash
codex mcp add weather-server --env WEATHER_API_KEY=YOUR_KEY -- python3 /ABS/PATH/weather_server.py
```

3. 验证注册结果：

```bash
codex mcp list
codex mcp get my-server
```

4. 在 Codex TUI 中查看是否激活：

```text
/mcp
```

#### 方式 B：手动编辑 `config.toml`

Codex 配置默认在 `~/.codex/config.toml`。也可使用项目级 `.codex/config.toml`（仅 trusted project 生效）。

STDIO 示例：

```toml
[mcp_servers.my-server]
command = "python3"
args = ["/ABS/PATH/my_server.py"]
cwd = "/ABS/PATH"
startup_timeout_sec = 20
tool_timeout_sec = 60
enabled = true
required = false
```

带环境变量示例：

```toml
[mcp_servers.weather]
command = "python3"
args = ["/ABS/PATH/weather_server.py"]

[mcp_servers.weather.env]
WEATHER_API_KEY = "YOUR_KEY"
```

HTTP MCP 示例：

```toml
[mcp_servers.openaiDeveloperDocs]
url = "https://developers.openai.com/mcp"
```

带 Bearer Token 的 HTTP MCP：

```toml
[mcp_servers.my-remote]
url = "https://example.com/mcp"
bearer_token_env_var = "MY_REMOTE_MCP_TOKEN"
```

### 4. 让 Codex 可靠识别 MCP

1. 使用绝对路径，避免 `cwd` 与相对路径不一致导致启动失败。
2. 改完 `config.toml` 后重启 Codex 会话。
3. 先用 `codex mcp list` 看配置是否存在，再用 `codex mcp get <name>` 看字段是否正确。
4. 若 server 启动慢，调大 `startup_timeout_sec`。
5. 需要 OAuth 的远程 MCP，执行 `codex mcp login <server-name>`。

### 5. Claude Desktop 注册（兼容场景）

若用户明确要求接入 Claude Desktop，再补充此配置：`~/.claude/mcp.json`

```json
{
  "mcpServers": {
    "my-server": {
      "command": "python3",
      "args": ["/path/to/my_server.py"]
    }
  }
}
```

## TypeScript MCP 服务器

### 1. 项目设置

```bash
mkdir my-mcp-server && cd my-mcp-server
npm init -y
npm install @modelcontextprotocol/sdk
```

### 2. 基础模板

```typescript
// src/index.ts
import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";

const server = new Server({
  name: "my-server",
  version: "1.0.0",
});

// 定义工具
server.setRequestHandler("tools/list", async () => ({
  tools: [
    {
      name: "hello",
      description: "向某人打招呼",
      inputSchema: {
        type: "object",
        properties: {
          name: { type: "string", description: "要问候的名字" },
        },
        required: ["name"],
      },
    },
  ],
}));

server.setRequestHandler("tools/call", async (request) => {
  if (request.params.name === "hello") {
    const name = request.params.arguments.name;
    return { content: [{ type: "text", text: `你好，${name}!` }] };
  }
  throw new Error("未知工具");
});

// 启动服务器
const transport = new StdioServerTransport();
server.connect(transport);
```

## 高级模式

### 外部 API 集成

```python
import httpx
from mcp.server import Server

server = Server("weather-server")

@server.tool()
async def get_weather(city: str) -> str:
    """获取城市的当前天气。"""
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"https://api.weatherapi.com/v1/current.json",
            params = {"key": "YOUR_API_KEY", "q": city}
        )
        data = resp.json()
        return f"{city}: {data['current']['temp_c']}°C, {data['current']['condition']['text']}"
```

### 数据库访问

```python
import sqlite3
from mcp.server import Server

server = Server("db-server")

@server.tool()
async def query_db(sql: str) -> str:
    """执行只读 SQL 查询。"""
    if not sql.strip().upper().startswith("SELECT"):
        return "错误：只允许 SELECT 查询"

    conn = sqlite3.connect("data.db")
    cursor = conn.execute(sql)
    rows = cursor.fetchall()
    conn.close()
    return str(rows)
```

### 资源（只读数据）

```python
@server.resource("config://settings")
async def get_settings() -> str:
    """应用程序设置。"""
    return open("settings.json").read()

@server.resource("file://{path}")
async def read_file(path: str) -> str:
    """从工作区读取文件。"""
    return open(path).read()
```

## 测试

```bash
npx @anthropics/mcp-inspector python3 my_server.py

echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 my_server.py
```

## 最佳实践

1. **优先给 Codex 注册命令**：默认先输出 `codex mcp add ...`，再给 `config.toml`
2. **清晰工具描述**：模型依赖描述来决定是否调用工具
3. **输入验证**：始终验证和清理输入
4. **错误处理**：返回可诊断的错误消息
5. **默认异步**：I/O 场景优先 async/await
6. **安全性**：不要暴露高风险或未授权操作
7. **幂等性**：工具应可安全重试
8. **可观测性**：关键路径加日志，便于排查注册后调用失败

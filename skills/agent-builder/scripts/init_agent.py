#!/usr/bin/env python3
"""
Agent Scaffold Script - Create a new agent project with best practices.

Usage:
    python init_agent.py <agent-name> [--level 0-4] [--path <output-dir>]

Examples:
    python init_agent.py my-agent                 # Level 1 (4 tools)
    python init_agent.py my-agent --level 0      # Minimal (bash only)
    python init_agent.py my-agent --level 2      # With TodoWrite
    python init_agent.py my-agent --path ./bots  # Custom output directory
"""

import argparse
import sys
from pathlib import Path
from string import Template

# Agent templates for each level
TEMPLATES = {
    0: '''#!/usr/bin/env python3
"""
Level 0 Agent - Bash is All You Need (~50 lines)

Core insight: One tool (bash) can do everything.
Subagents via self-recursion: python $name.py "subtask"
"""

import json
import os
import subprocess

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = os.getenv("LLM_MODEL")
if not MODEL:
    raise ValueError("Missing LLM_MODEL in environment.")

client = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)

SYSTEM = """You are a coding agent. Use bash for everything:
- Read: cat, grep, find, ls
- Write: echo 'content' > file
- Subagent: python $name.py "subtask"
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute shell command",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"}
                },
                "required": ["command"]
            }
        }
    }
]


def run(prompt, history = None):
    if history is None:
        history = []

    history.append({"role": "user", "content": prompt})
    while True:
        messages = [{"role": "system", "content": SYSTEM}]
        messages.extend(history)

        response = client.chat.completions.create(
            model = MODEL,
            messages = messages,
            tools = TOOLS,
            max_tokens = 8000,
        )

        message = response.choices[0].message
        if message is None:
            raise ValueError("LLM response is None.")

        assistant_message = {
            "role": "assistant",
            "content": message.content or "",
        }
        if message.tool_calls:
            assistant_message["tool_calls"] = []
            for tool_call in message.tool_calls:
                assistant_message["tool_calls"].append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                )
        history.append(assistant_message)

        if not message.tool_calls:
            return message.content or ""

        results = []
        for tool_call in message.tool_calls:
            try:
                args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            command = args.get("command", "")
            print(f"> {command}")
            try:
                out = subprocess.run(
                    command,
                    shell = True,
                    capture_output = True,
                    text = True,
                    timeout = 60,
                )
                output = (out.stdout + out.stderr).strip() or "(empty)"
            except subprocess.TimeoutExpired:
                output = "Error: Timeout (60s)"
            except Exception as exception:
                output = f"Error: {exception}"

            results.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": "bash",
                    "content": output[:50000],
                }
            )

        history.extend(results)


if __name__ == "__main__":
    h = []
    print("$name - Level 0 Agent\\nType 'q' to quit.\\n")
    while (q := input(">> ").strip()) not in ("q", "quit", ""):
        print(run(q, h), "\\n")
''',

    1: '''#!/usr/bin/env python3
"""
Level 1 Agent - Model as Agent (~200 lines)

Core insight: 4 tools cover 90% of coding tasks.
The model IS the agent. Code just runs the loop.
"""

import json
import os
import subprocess
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = os.getenv("LLM_MODEL")
if not MODEL:
    raise ValueError("Missing LLM_MODEL in environment.")

client = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)
WORKDIR = Path.cwd()

SYSTEM = f"""You are a coding agent at {WORKDIR}.

Rules:
- Prefer tools over prose. Act, don't just explain.
- Never invent file paths. Use ls/find first if unsure.
- Make minimal changes. Don't over-engineer.
- After finishing, summarize what changed."""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Run shell command",
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}},
                "required": ["command"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"}
                },
                "required": ["path", "content"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace exact text in file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "old_text": {"type": "string"},
                    "new_text": {"type": "string"}
                },
                "required": ["path", "old_text", "new_text"]
            }
        }
    },
]


def safe_path(p: str) -> Path:
    """Prevent path escape attacks."""
    path = (WORKDIR / p).resolve()
    if not path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {p}")
    return path


def execute(name: str, args: dict) -> str:
    """Execute a tool and return result."""
    if name == "bash":
        dangerous = ["rm -rf /", "sudo", "shutdown", "> /dev/"]
        if any(d in args["command"] for d in dangerous):
            return "Error: Dangerous command blocked"
        try:
            r = subprocess.run(
                args["command"],
                shell = True,
                cwd = WORKDIR,
                capture_output = True,
                text = True,
                timeout = 60,
            )
            return (r.stdout + r.stderr).strip()[:50000] or "(empty)"
        except subprocess.TimeoutExpired:
            return "Error: Timeout (60s)"
        except Exception as exception:
            return f"Error: {exception}"

    if name == "read_file":
        try:
            return safe_path(args["path"]).read_text()[:50000]
        except Exception as exception:
            return f"Error: {exception}"

    if name == "write_file":
        try:
            p = safe_path(args["path"])
            p.parent.mkdir(parents = True, exist_ok = True)
            p.write_text(args["content"])
            return f"Wrote {len(args['content'])} bytes to {args['path']}"
        except Exception as exception:
            return f"Error: {exception}"

    if name == "edit_file":
        try:
            p = safe_path(args["path"])
            content = p.read_text()
            if args["old_text"] not in content:
                return f"Error: Text not found in {args['path']}"
            p.write_text(content.replace(args["old_text"], args["new_text"], 1))
            return f"Edited {args['path']}"
        except Exception as exception:
            return f"Error: {exception}"

    return f"Unknown tool: {name}"


def agent(prompt: str, history: list = None) -> str:
    """Run the agent loop."""
    if history is None:
        history = []
    history.append({"role": "user", "content": prompt})

    while True:
        messages = [{"role": "system", "content": SYSTEM}]
        messages.extend(history)

        response = client.chat.completions.create(
            model = MODEL,
            messages = messages,
            tools = TOOLS,
            max_tokens = 8000,
        )

        message = response.choices[0].message
        if message is None:
            raise ValueError("LLM response is None.")

        assistant_message = {
            "role": "assistant",
            "content": message.content or "",
        }
        if message.tool_calls:
            assistant_message["tool_calls"] = []
            for tool_call in message.tool_calls:
                assistant_message["tool_calls"].append(
                    {
                        "id": tool_call.id,
                        "type": "function",
                        "function": {
                            "name": tool_call.function.name,
                            "arguments": tool_call.function.arguments,
                        },
                    }
                )
        history.append(assistant_message)

        if not message.tool_calls:
            return message.content or ""

        results = []
        for tool_call in message.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                tool_args = {}

            print(f"> {tool_name}: {str(tool_args)[:100]}")
            output = execute(tool_name, tool_args)
            print(f"  {output[:100]}...")
            results.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": output,
                }
            )

        history.extend(results)


if __name__ == "__main__":
    print(f"$name - Level 1 Agent at {WORKDIR}")
    print("Type 'q' to quit.\\n")
    h = []
    while True:
        try:
            query = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if query in ("q", "quit", "exit", ""):
            break
        print(agent(query, h), "\\n")
''',
}

ENV_TEMPLATE = '''# API Configuration
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3:latest
'''


def create_agent(name: str, level: int, output_dir: Path):
    """Create a new agent project."""
    # Validate level
    if level not in TEMPLATES and level not in (2, 3, 4):
        print(f"Error: Level {level} not yet implemented in scaffold.")
        print("Available levels: 0 (minimal), 1 (4 tools)")
        print("For levels 2-4, copy from mini-claude-code repository.")
        sys.exit(1)

    # Create output directory
    agent_dir = output_dir / name
    agent_dir.mkdir(parents = True, exist_ok = True)

    # Write agent file
    agent_file = agent_dir / f"{name}.py"
    template = TEMPLATES.get(level, TEMPLATES[1])
    agent_file.write_text(Template(template).substitute(name = name))
    print(f"Created: {agent_file}")

    # Write .env.example
    env_file = agent_dir / ".env.example"
    env_file.write_text(ENV_TEMPLATE)
    print(f"Created: {env_file}")

    # Write .gitignore
    gitignore = agent_dir / ".gitignore"
    gitignore.write_text(".env\n__pycache__/\n*.pyc\n")
    print(f"Created: {gitignore}")

    print(f"\nAgent '{name}' created at {agent_dir}")
    print(f"\nNext steps:")
    print(f"  1. cd {agent_dir}")
    print(f"  2. cp .env.example .env")
    print(f"  3. Edit .env with your LLM settings")
    print(f"  4. pip install openai python-dotenv")
    print(f"  5. python {name}.py")


def main():
    parser = argparse.ArgumentParser(
        description = "Scaffold a new AI coding agent project",
        formatter_class = argparse.RawDescriptionHelpFormatter,
        epilog = """
Levels:
  0  Minimal (~50 lines) - Single bash tool, self-recursion for subagents
  1  Basic (~200 lines)  - 4 core tools: bash, read, write, edit
  2  Todo (~300 lines)   - + TodoWrite for structured planning
  3  Subagent (~450)     - + Task tool for context isolation
  4  Skills (~550)       - + Skill tool for domain expertise
        """,
    )
    parser.add_argument("name", help = "Name of the agent to create")
    parser.add_argument(
        "--level",
        type = int,
        default = 1,
        choices = [0, 1, 2, 3, 4],
        help = "Complexity level (default: 1)",
    )
    parser.add_argument(
        "--path",
        type = Path,
        default = Path.cwd(),
        help = "Output directory (default: current directory)",
    )

    args = parser.parse_args()
    create_agent(args.name, args.level, args.path)


if __name__ == "__main__":
    main()

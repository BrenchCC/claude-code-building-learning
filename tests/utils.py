"""
Shared test utilities for this repository.

Provides:
1) OpenAI-compatible test client
2) Tool schema constants (OpenAI function-calling format)
3) Local tool executor for offline test loops
4) Agent loop runner for lightweight integration tests
5) Common test runner
"""

import os
import json
import subprocess
import traceback
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv



PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

MODEL = os.getenv("TEST_MODEL") or os.getenv("LLM_MODEL") or "gpt-4o-mini"


def get_client():
    """
    Build OpenAI-compatible client for tests.

    Parameters:
        None.
    """
    api_key = os.getenv("TEST_API_KEY") or os.getenv("LLM_API_KEY")
    base_url = os.getenv("TEST_BASE_URL") or os.getenv("LLM_BASE_URL")
    if not api_key or not base_url:
        return None
    return OpenAI(
        api_key = api_key,
        base_url = base_url,
    )


BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a shell command and return stdout+stderr.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"],
        },
    },
}

READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read text content from a file path.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "max_lines": {"type": "integer"},
            },
            "required": ["file_path"],
        },
    },
}

WRITE_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write full text content to a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["file_path", "content"],
        },
    },
}

EDIT_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "edit_file",
        "description": "Replace first match of old_text with new_text in a file.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "old_content": {"type": "string"},
                "new_content": {"type": "string"},
            },
            "required": ["file_path", "old_content", "new_content"],
        },
    },
}

TODO_WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "todo_write",
        "description": "Update task list with content/status/activeForm fields.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {"type": "string"},
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                            },
                            "activeForm": {"type": "string"},
                        },
                        "required": ["content", "status", "activeForm"],
                    },
                }
            },
            "required": ["items"],
        },
    },
}

SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": "Skill",
        "description": "Load a skill by name.",
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {"type": "string"},
                "args": {"type": "string"},
            },
            "required": ["skill_name"],
        },
    },
}

TASK_TOOL = {
    "type": "function",
    "function": {
        "name": "Task",
        "description": "Spawn subagent task with type and prompt.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_description": {"type": "string"},
                "prompt": {"type": "string"},
                "agent_type": {
                    "type": "string",
                    "enum": ["explore", "code", "plan"],
                },
            },
            "required": ["task_description", "prompt", "agent_type"],
        },
    },
}


def _resolve_path(raw_path, workdir):
    """
    Resolve a user path under a selected working directory.

    Parameters:
        raw_path: Path string from tool args.
        workdir: Base directory string or Path.
    """
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path(workdir) / path


def _parse_arguments(arguments):
    """
    Parse function arguments JSON safely.

    Parameters:
        arguments: Raw JSON argument string.
    """
    if not arguments:
        return {}
    try:
        return json.loads(arguments)
    except json.JSONDecodeError:
        cleaned = "".join(ch for ch in arguments if ch >= " " or ch in "\t\n\r")
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            return {}


def execute_tool(name, args, workdir = None):
    """
    Execute supported local test tool calls.

    Parameters:
        name: Tool name.
        args: Parsed argument dictionary.
        workdir: Base directory used by file and bash tools.
    """
    base_dir = Path(workdir or os.getcwd())

    if name == "bash":
        command = args.get("command", "")
        try:
            result = subprocess.run(
                command,
                shell = True,
                cwd = base_dir,
                capture_output = True,
                text = True,
                timeout = 30,
            )
            output = (result.stdout or "") + (result.stderr or "")
            return output.strip() or "(empty)"
        except Exception as exc:
            return f"Error: {exc}"

    if name == "read_file":
        raw_path = args.get("file_path", args.get("path", ""))
        path = _resolve_path(raw_path, base_dir)
        limit = args.get("max_lines", args.get("limit"))
        try:
            lines = path.read_text(encoding = "utf-8", errors = "replace").splitlines()
            if isinstance(limit, int):
                lines = lines[:limit]
            return "\n".join(lines)
        except Exception as exc:
            return f"Error: {exc}"

    if name == "write_file":
        raw_path = args.get("file_path", args.get("path", ""))
        path = _resolve_path(raw_path, base_dir)
        content = args.get("content", "")
        try:
            path.parent.mkdir(parents = True, exist_ok = True)
            path.write_text(content, encoding = "utf-8")
            return f"Wrote {len(content)} bytes to {path}"
        except Exception as exc:
            return f"Error: {exc}"

    if name == "edit_file":
        raw_path = args.get("file_path", args.get("path", ""))
        path = _resolve_path(raw_path, base_dir)
        old_text = args.get("old_content", args.get("old_text", args.get("old_string", "")))
        new_text = args.get("new_content", args.get("new_text", args.get("new_string", "")))
        try:
            text = path.read_text(encoding = "utf-8", errors = "replace")
            if old_text not in text:
                return f"Error: Text not found in {path}"
            path.write_text(text.replace(old_text, new_text, 1), encoding = "utf-8")
            return f"Edited {path}"
        except Exception as exc:
            return f"Error: {exc}"

    if name in {"TodoWrite", "todo_write"}:
        items = args.get("items", [])
        in_progress = 0
        lines = []
        for item in items:
            status = item.get("status", "pending")
            if status == "in_progress":
                in_progress += 1
            mark = "[x]" if status == "completed" else "[>]" if status == "in_progress" else "[ ]"
            lines.append(f"{mark} {item.get('content', '')}")
        if in_progress > 1:
            return "Error: Only one task can be in_progress"
        done = len([i for i in items if i.get("status") == "completed"])
        return "\n".join(lines) + f"\n({done}/{len(items)} done)"

    if name == "Skill":
        skill_name = args.get("skill_name", args.get("skill", ""))
        skill_args = args.get("args")
        args_attr = f' args="{skill_args}"' if skill_args else ""
        return (
            f'<skill-loaded name="{skill_name}"{args_attr}>\n'
            f"# Skill: {skill_name}\n\n"
            f"Simulated skill content for local tests.\n"
            f"</skill-loaded>\n\n"
            "Follow the instructions in the skill above to complete the user's task."
        )

    if name == "Task":
        desc = args.get("task_description", args.get("description", ""))
        agent_type = args.get("agent_type", args.get("subagent_type", ""))
        return f"[{agent_type}] {desc} (simulated)"

    return f"Unknown tool: {name}"


def run_agent(client, task, tools, system = None, max_turns = 10, workdir = None):
    """
    Run a tool-calling agent loop with the provided client.

    Parameters:
        client: OpenAI-compatible client instance.
        task: Initial user instruction.
        tools: Tool schema list.
        system: Optional system prompt text.
        max_turns: Max tool loop rounds.
        workdir: Optional working directory for local tool executor.
    """
    if not client:
        return None, [], []

    messages = [{"role": "user", "content": task}]
    system_prompt = system or "You are a coding agent. Use tools to complete tasks."
    tool_calls_made = []

    for _ in range(max_turns):
        response = client.chat.completions.create(
            model = MODEL,
            messages = [{"role": "system", "content": system_prompt}] + messages,
            tools = tools,
            max_tokens = 2000,
        )
        message = response.choices[0].message

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
        messages.append(assistant_message)

        if not message.tool_calls:
            return message.content, tool_calls_made, messages

        tool_messages = []
        for tool_call in message.tool_calls:
            args = _parse_arguments(tool_call.function.arguments)
            tool_name = tool_call.function.name
            tool_calls_made.append((tool_name, args))
            output = execute_tool(name = tool_name, args = args, workdir = workdir)
            tool_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": output[:5000],
                }
            )
        messages.extend(tool_messages)

    return None, tool_calls_made, messages


def run_tests(test_functions):
    """
    Run test callables and print a compact summary.

    Parameters:
        test_functions: List of test functions.
    """
    failed = []
    for test_function in test_functions:
        print(f"\n{'=' * 60}")
        print(f"Running: {test_function.__name__}")
        print("=" * 60)
        try:
            if not test_function():
                failed.append(test_function.__name__)
        except Exception as exc:
            print(f"FAILED: {exc}")
            traceback.print_exc()
            failed.append(test_function.__name__)

    passed = len(test_functions) - len(failed)
    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{len(test_functions)} passed")
    print("=" * 60)
    if failed:
        print(f"FAILED: {failed}")
        return False
    print("All tests passed!")
    return True

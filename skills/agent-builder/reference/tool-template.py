"""
Tool Templates - Copy and customize these for your agent.

Each tool needs:
1. OpenAI function schema for model tool calling.
2. Python implementation for actual execution.
"""

import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

WORKDIR = Path.cwd()
MAX_OUTPUT_CHARS = 50000


BASH_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": (
            "Run a shell command in workspace. Use for ls/find/rg/git/python/etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Shell command to execute.",
                }
            },
            "required": ["command"],
        },
    },
}

READ_FILE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read UTF-8 file content.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative file path.",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Optional max lines to return.",
                },
            },
            "required": ["path"],
        },
    },
}

WRITE_FILE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Write full content to file and create missing parent dirs.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative file path.",
                },
                "content": {
                    "type": "string",
                    "description": "File content to write.",
                },
            },
            "required": ["path", "content"],
        },
    },
}

EDIT_FILE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "edit_file",
        "description": "Replace exact text once in file for surgical edits.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Workspace-relative file path.",
                },
                "old_text": {
                    "type": "string",
                    "description": "Exact text to search.",
                },
                "new_text": {
                    "type": "string",
                    "description": "Replacement text.",
                },
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
}

TODO_WRITE_TOOL: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "TodoWrite",
        "description": "Update task list for planning and progress tracking.",
        "parameters": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "description": "Complete task list state.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Task description.",
                            },
                            "status": {
                                "type": "string",
                                "enum": [
                                    "pending",
                                    "in_progress",
                                    "completed",
                                ],
                            },
                            "activeForm": {
                                "type": "string",
                                "description": "Present tense action phrase.",
                            },
                        },
                        "required": ["content", "status", "activeForm"],
                    },
                }
            },
            "required": ["items"],
        },
    },
}


def build_base_tools() -> List[Dict[str, Any]]:
    """
    Return common base tools for a coding agent.

    Parameters:
        None: This function has no input parameters.
    """
    return [
        BASH_TOOL,
        READ_FILE_TOOL,
        WRITE_FILE_TOOL,
        EDIT_FILE_TOOL,
    ]


def safe_path(path: str) -> Path:
    """
    Resolve path safely inside workspace.

    Parameters:
        path: Relative path from tool arguments.
    """
    resolved_path = (WORKDIR / path).resolve()
    if not resolved_path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {path}")
    return resolved_path


def run_bash(command: str) -> str:
    """
    Execute shell command with basic safety checks.

    Parameters:
        command: Shell command string to run.
    """
    dangerous = ["rm -rf /", "sudo", "shutdown", "reboot", "> /dev/"]
    if any(token in command for token in dangerous):
        return "Error: Dangerous command blocked"

    try:
        result = subprocess.run(
            command,
            shell = True,
            cwd = WORKDIR,
            capture_output = True,
            text = True,
            timeout = 60,
        )
        output = (result.stdout + result.stderr).strip()
        return output[:MAX_OUTPUT_CHARS] if output else "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: Command timed out (60s)"
    except Exception as exception:
        return f"Error: {exception}"


def run_read_file(path: str, max_lines: Optional[int] = None) -> str:
    """
    Read UTF-8 text file with optional line limit.

    Parameters:
        path: Relative file path to read.
        max_lines: Optional line count limit.
    """
    try:
        text = safe_path(path = path).read_text(encoding = "utf-8")
        lines = text.splitlines()

        if max_lines is not None and max_lines > 0 and max_lines < len(lines):
            remaining_count = len(lines) - max_lines
            lines = lines[:max_lines] + [f"... ({remaining_count} more lines)"]

        return "\n".join(lines)[:MAX_OUTPUT_CHARS]
    except Exception as exception:
        return f"Error: {exception}"


def run_write_file(path: str, content: str) -> str:
    """
    Write full file content, creating parent directories as needed.

    Parameters:
        path: Relative file path to write.
        content: Full content that replaces file.
    """
    try:
        file_path = safe_path(path = path)
        file_path.parent.mkdir(
            parents = True,
            exist_ok = True,
        )
        file_path.write_text(
            content,
            encoding = "utf-8",
        )
        return f"Wrote {len(content)} bytes to {path}"
    except Exception as exception:
        return f"Error: {exception}"


def run_edit_file(path: str, old_text: str, new_text: str) -> str:
    """
    Replace first exact occurrence of text in file.

    Parameters:
        path: Relative file path to edit.
        old_text: Exact source text to replace.
        new_text: Replacement text.
    """
    try:
        file_path = safe_path(path = path)
        content = file_path.read_text(encoding = "utf-8")

        if old_text not in content:
            return f"Error: Text not found in {path}"

        file_path.write_text(
            content.replace(old_text, new_text, 1),
            encoding = "utf-8",
        )
        return f"Edited {path}"
    except Exception as exception:
        return f"Error: {exception}"


def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """
    Dispatch tool call to concrete implementation.

    Parameters:
        name: Tool function name.
        args: Parsed JSON argument object.
    """
    if name == "bash":
        return run_bash(command = args["command"])
    if name == "read_file":
        return run_read_file(path = args["path"], max_lines = args.get("max_lines"))
    if name == "write_file":
        return run_write_file(path = args["path"], content = args["content"])
    if name == "edit_file":
        return run_edit_file(
            path = args["path"],
            old_text = args["old_text"],
            new_text = args["new_text"],
        )
    return f"Unknown tool: {name}"

#!/usr/bin/env python3
"""
Minimal Agent Template - Copy and customize this.

This is the simplest possible working agent.
It has everything you need: 3 tools + loop.

Usage:
    1. Configure .env with LLM_BASE_URL / LLM_API_KEY / LLM_MODEL
    2. python minimal-agent.py
    3. Type commands, 'q' to quit
"""

import os
import json
import logging
import argparse
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from openai import OpenAI
from dotenv import load_dotenv

logger = logging.getLogger(__name__)
WORKDIR = Path.cwd()
SYSTEM_PROMPT = (
    "You are a minimal coding agent.\n"
    "Use tools to complete tasks in the current workspace.\n"
    "Prefer action over explanation.\n"
    "Summarize what changed when done."
)


def parse_args() -> argparse.Namespace:
    """
    Parse CLI arguments for single-shot or interactive mode.

    Parameters:
        None: This function has no input parameters.
    """
    parser = argparse.ArgumentParser(
        description = "Minimal coding agent for this repository.",
    )
    parser.add_argument(
        "query",
        nargs = "?",
        default = "",
        help = "Run one prompt. Leave empty for interactive mode.",
    )
    return parser.parse_args()


load_dotenv()

MODEL = os.getenv("LLM_MODEL")
if not MODEL:
    raise ValueError("Missing LLM_MODEL in environment.")

LLM_SERVER = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": "Execute shell command in workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string"},
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read file contents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "max_lines": {"type": "integer"},
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write full file content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
        },
    },
]


def _safe_path(path: str) -> Path:
    """
    Resolve path inside workspace.

    Parameters:
        path: Relative file path from tool input.
    """
    resolved_path = (WORKDIR / path).resolve()
    if not resolved_path.is_relative_to(WORKDIR):
        raise ValueError(f"Path escapes workspace: {path}")
    return resolved_path


def execute_tool(name: str, args: Dict[str, Any]) -> str:
    """
    Execute one tool call and return output text.

    Parameters:
        name: Tool function name.
        args: Tool argument object.
    """
    if name == "bash":
        try:
            result = subprocess.run(
                args["command"],
                shell = True,
                cwd = WORKDIR,
                capture_output = True,
                text = True,
                timeout = 60,
            )
            return (result.stdout + result.stderr).strip()[:50000] or "(empty)"
        except subprocess.TimeoutExpired:
            return "Error: Timeout (60s)"
        except Exception as exception:
            return f"Error: {exception}"

    if name == "read_file":
        try:
            safe_file = _safe_path(path = args["path"])
            max_lines = int(args.get("max_lines", 1000))
            if max_lines <= 0:
                return "Error: max_lines must be positive."
            lines = safe_file.read_text(encoding = "utf-8").splitlines()
            return "\n".join(lines[:max_lines])[:50000]
        except Exception as exception:
            return f"Error: {exception}"

    if name == "write_file":
        try:
            safe_file = _safe_path(path = args["path"])
            safe_file.parent.mkdir(
                parents = True,
                exist_ok = True,
            )
            safe_file.write_text(
                args["content"],
                encoding = "utf-8",
            )
            return f"Wrote {len(args['content'])} bytes to {args['path']}"
        except Exception as exception:
            return f"Error: {exception}"

    return f"Unknown tool: {name}"


def _build_assistant_message(message: Any) -> Dict[str, Any]:
    """
    Convert OpenAI message object into history format.

    Parameters:
        message: OpenAI response message object.
    """
    assistant_message: Dict[str, Any] = {
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
    return assistant_message


def agent(
    prompt: str,
    history: Optional[List[Dict[str, Any]]] = None,
) -> str:
    """
    Run the agent loop for one user prompt.

    Parameters:
        prompt: User query text.
        history: Shared conversation history for multi-turn mode.
    """
    if history is None:
        history = []

    history.append({"role": "user", "content": prompt})

    while True:
        messages = [
            {
                "role": "system",
                "content": f"{SYSTEM_PROMPT}\nWorkspace: {WORKDIR}",
            },
        ]
        messages.extend(history)

        response = LLM_SERVER.chat.completions.create(
            model = MODEL,
            messages = messages,
            tools = TOOLS,
            max_tokens = 8192,
        )

        llm_response = response.choices[0].message
        if llm_response is None:
            raise ValueError("LLM response is None.")

        history.append(_build_assistant_message(message = llm_response))

        if not llm_response.tool_calls:
            return llm_response.content or ""

        results: List[Dict[str, Any]] = []
        for tool_call in llm_response.tool_calls:
            tool_name = tool_call.function.name
            try:
                tool_args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                tool_args = {}

            logger.info(f"> {tool_name}: {str(tool_args)[:200]}")
            output = execute_tool(
                name = tool_name,
                args = tool_args,
            )
            logger.info(f"  {output[:120]}...")
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
    logging.basicConfig(
        level = logging.INFO,
        format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers = [logging.StreamHandler()],
    )

    arguments = parse_args()
    if arguments.query:
        print(agent(prompt = arguments.query, history = []))
        raise SystemExit(0)

    print(f"Minimal Agent - {WORKDIR}")
    print("Type 'q' to quit.\n")

    shared_history: List[Dict[str, Any]] = []
    while True:
        try:
            query = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if query in ("q", "quit", "exit", ""):
            break
        print(agent(prompt = query, history = shared_history))
        print()

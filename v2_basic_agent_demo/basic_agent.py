import os
import sys
import json
import logging
import subprocess
from typing import List
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_PATH = "prompts/v2_basic_agent.md"

load_dotenv()

WORKSPACE = Path.cwd()

MODEL = os.getenv("LLM_MODEL")

LLM_SERVER = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)

TOOL = [
    # Tool 1: Bash - The gateway to execute everything 
    # Can run any command: git, pip, python, curl, etc.
    {
        "type": "function",
        "function": {
            "name": "bash",
            "description": """Execute shell command. Common patterns include:
- Read: cat/head/tail, grep/find/rg/ls, wc -l
- Write: echo 'content' > file, sed -i 's/old/new/g' file
- Subagent: python v1_bash_agent_demo/bash_agent.py 'task description' (spawns isolated agent, returns summary)""",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "The shell command to execute",
                    }
                },
                "required": ["command"],
            }
        }
    },
    
    # Tool 2: Read File - For understanding existing code
    # Returns file content with optional line limit for large files
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read the content of a file. Returns file content with optional line limit for large files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to read.",
                    },
                    "max_lines": {
                        "type": "integer",
                        "description": "The maximum number of lines to return (default is 1000).",
                    }
                },
                "required": ["file_path"],
            }
        }
    },

    # Tool 3: Write File - For modifying code or creating new files
    # Takes file path and content to write, creates file and parent directories automatically if not exist
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to write.",
                    },
                    "content": {
                        "type": "string",
                        "description": "The content to write to the file.",
                    },
                },
                "required": ["file_path", "content"],
            }
        }
    },

    # Tool 4: Edit File - For modifying existing files with context
    # Uses unified diff format to specify edits, takes file path and diff content(old/next), applies changes to the file (creates backup before editing)
    {
        "type": "function",
        "function": {
            "name": "edit_file",
            "description": "Replace old content with new content in a file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "The path to the file to edit.",
                    },
                    "old_content":{
                        "type": "string",
                        "description": "The original content to be replaced.",
                    },
                    "new_content":{
                        "type": "string",
                        "description": "The new content to replace with.",
                    }
                }
            }
        }
    },
]

with open(SYSTEM_PROMPT_PATH, "r", encoding = "utf-8") as f:
    SYSTEM_PROMPT = f.read()
SYSTEM_PROMPT = SYSTEM_PROMPT.format(workspace = WORKSPACE)

def bash(command: str) -> dict:
    """
    Execute a shell command.

    Parameters:
        command: The shell command to execute.
    """
    try:
        result = subprocess.run(
            command,
            shell = True,
            cwd = WORKSPACE,
            capture_output = True,
            text = True,
            timeout = 300,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {
            "stdout": "",
            "stderr": "(timeout after 300s)",
            "returncode": 124,
        }


def read_file(file_path: str, max_lines: int = 1000) -> dict:
    """
    Read content from a file.

    Parameters:
        file_path: The path to the file to read.
        max_lines: The maximum number of lines to return.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = WORKSPACE / path
    with path.open("r", encoding = "utf-8", errors = "replace") as file:
        if max_lines is None:
            content = file.read()
        else:
            content = "".join(file.readline() for _ in range(max_lines))
    return {"content": content}


def write_file(file_path: str, content: str) -> dict:
    """
    Write content to a file.

    Parameters:
        file_path: The path to the file to write.
        content: The content to write to the file.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = WORKSPACE / path
    path.parent.mkdir(parents = True, exist_ok = True)
    with path.open("w", encoding = "utf-8") as file:
        file.write(content)
    return {"status": "ok"}


def edit_file(file_path: str, old_content: str, new_content: str) -> dict:
    """
    Replace old content with new content in a file.

    Parameters:
        file_path: The path to the file to edit.
        old_content: The original content to be replaced.
        new_content: The new content to replace with.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = WORKSPACE / path
    text = path.read_text(encoding = "utf-8", errors = "replace")
    if old_content not in text:
        return {"status": "not_found"}
    backup_path = path.with_suffix(path.suffix + ".bak")
    backup_path.write_text(text, encoding = "utf-8")
    updated = text.replace(old_content, new_content)
    path.write_text(updated, encoding = "utf-8")
    return {"status": "ok", "backup_path": str(backup_path)}


def chat(prompt: str = None, history: List = None):
    """
    The agent to chat with LLM and execute tool calls in a loop.

    Args:
        prompt (str): The user prompt to start the chat.
        history (list, optional): The chat history for multi-turn conversation.
    Returns:
        str: The final response from the agent.
    """
    if not history:
        history = []

    history.append({"role": "user", "content": prompt})

    while True:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        messages.extend(history)

        response = LLM_SERVER.chat.completions.create(
            model = MODEL,
            messages = messages,
            tools = TOOL,
            max_tokens = 8192
        )

        llm_response = response.choices[0].message

        if llm_response is None:
            raise ValueError("LLM response is None")

        assistant_message = {
            "role": "assistant",
            "content": llm_response.content or ""
        }

        if llm_response.tool_calls:
            assistant_message["tool_calls"] = []
            for tool_call in llm_response.tool_calls:
                assistant_message["tool_calls"].append({
                    "id": tool_call.id,
                    "type": "function",
                    "function": {
                        "name": tool_call.function.name,
                        "arguments": tool_call.function.arguments
                    }
                })

        history.append(assistant_message)

        if not llm_response.tool_calls:
            return llm_response.content

        results = []
        for tool_call in llm_response.tool_calls:
            tool_name = tool_call.function.name
            args = json.loads(tool_call.function.arguments or "{}")

            if tool_name == "bash":
                cmd = args.get("command", "")
                print(f"\033[33m$ {cmd}\033[0m")
                output = bash(**args)
                combined = (output.get("stdout", "") or "") + (output.get("stderr", "") or "")
                print(combined or "(empty)")
            elif tool_name == "read_file":
                output = read_file(**args)
            elif tool_name == "write_file":
                output = write_file(**args)
            elif tool_name == "edit_file":
                output = edit_file(**args)
            else:
                output = {"error": f"Unknown tool: {tool_name}"}

            results.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(output, ensure_ascii = False)[:50000]
            })

        history.extend(results)


def parse_args():
    """
    Parse command line arguments.

    Returns:
        argparse.Namespace: Parsed CLI arguments.
    """
    import argparse

    parser = argparse.ArgumentParser(description = "Basic Agent - Chat with LLM and use tools")
    parser.add_argument(
        "prompt",
        nargs = "?",
        help = "User prompt for the agent"
    )

    return parser.parse_args()


def main():
    """
    Main function to run the basic agent from command line.
    """
    args = parse_args()

    logging.basicConfig(
        level = logging.INFO,
        format = '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers = [logging.StreamHandler()]
    )

    if args.prompt:
        logger.info("=" * 80)
        logger.info("Starting Basic Agent in single-shot mode")
        logger.info("=" * 80)

        try:
            result = chat(args.prompt)
            logger.info("-" * 60)
            logger.info("Final Response:")
            logger.info("-" * 60)
            print(result)
        except Exception as e:
            logger.error(f"Error: {e}")
            return 1
    else:
        logger.info("=" * 80)
        logger.info("Starting Basic Agent in interactive mode")
        logger.info("=" * 80)
        logger.info("Type 'exit' or 'quit' to end the conversation")
        logger.info("-" * 60)

        history = []
        try:
            while True:
                prompt = input("\033[94mUser:\033[0m ").strip()
                if prompt.lower() in ["exit", "quit"]:
                    logger.info("Conversation ended.")
                    break

                if not prompt:
                    continue

                result = chat(prompt, history)
                print(f"\033[92mAssistant:\033[0m {result}")
        except KeyboardInterrupt:
            logger.info("\nConversation interrupted.")
        except Exception as e:
            logger.error(f"Error: {e}")
            return 1


if __name__ == "__main__":
    sys.exit(main())

    

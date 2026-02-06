import os
import sys
import json
import logging
import subprocess
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv

logger = logging.getLogger("V2-Basic-Agent")

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

# TODO: Tool Implementation: Add function implementations for the tools defined above (bash, read_file, write_file, edit_file)

    

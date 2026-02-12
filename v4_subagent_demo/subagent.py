import os
import sys
import json
import logging
import subprocess
from pathlib import Path
from typing import List, Dict

from openai import OpenAI
from dotenv import load_dotenv


logger = logging.getLogger("V4-Subagent")

SYSTEM_PROMPT_PATH = "prompts/v4_subagent.md"

load_dotenv()

WORKSPACE = Path.cwd()

MODEL = os.getenv("LLM_MODEL")

LLM_SERVER = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)

# =============================================================================
# Agent Type Registry - The core of subagent mechanism
# =============================================================================
AGENT_TYPE_REGISTRY = {
    "explore": {
        "tools": ["bash", "read_file"], # Read-only tools
        "system_prompt": "You are an exploration subagent. Search and analyze, but never modify files. Return a concise summary.",
    },
    "code": {
        "tools": ["*"], # all tools
        "system_prompt": "You are a coding subagent. You have full access to implement efficiently changes in the codebase. Follow the plan strictly.",
    },
    "plan": {
        "tools": ["bash", "read_file"], # Read-only tools
        "system_prompt": "You are a planning subagent. Analyze the codebase and output a numbered implementation plan. Do NOT make changes.",
    },
}

# TODO: Implement Subagent class and main agent loop using the above registry
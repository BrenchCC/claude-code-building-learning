import os
import sys
import json
import logging
import subprocess
from typing import List
from pathlib import Path

from openai import OpenAI
from dotenv import load_dotenv


logger = logging.getLogger("V3-Todo-Agent")

SYSTEM_PROMPT_PATH = "prompts/v3_todo_agent.md"

load_dotenv()

WORKSPACE = Path.cwd()

MODEL = os.getenv("LLM_MODEL")

LLM_SERVER = OpenAI(
    base_url = os.getenv("LLM_BASE_URL"),
    api_key = os.getenv("LLM_API_KEY"),
)

# Define the TodoManager class to handle todo list operations   
# TODO: Implement the TodoManager class with methods to add, remove, and list tasks, as well as enforce constraints on task management.
class TodoManager:
    """
    Manages a structured task list with enforced constraints.
    Key features include:


    This gives real-time visibility into what the agent is doing.
    """
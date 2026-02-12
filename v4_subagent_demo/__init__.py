"""v4_subagent.py - Mini Claude Code: Subagent Mechanism (~450 lines)

Core Philosophy: "Divide and Conquer with Context Isolation"
=============================================================
v3 adds planning. But for large tasks like "explore the codebase then
refactor auth", a single agent hits problems:

The Problem - Context Pollution:
-------------------------------
    Single-Agent History:
      [exploring...] cat file1.py -> 500 lines
      [exploring...] cat file2.py -> 300 lines
      ... 15 more files ...
      [now refactoring...] "Wait, what did file1 contain?"

The model's context fills with exploration details, leaving little room
for the actual task. This is "context pollution".

The Solution - Subagents with Isolated Context:
----------------------------------------------
    Main Agent History:
      [Task: explore codebase]
        -> Subagent explores 20 files (in its own context)
        -> Returns ONLY: "Auth in src/auth/, DB in src/models/"
      [now refactoring with clean context]

Each subagent has:
  1. Its own fresh message history
  2. Filtered tools (explore can't write)
  3. Specialized system prompt
  4. Returns only final summary to parent

The Key Insight:
---------------
    Process isolation = Context isolation

By spawning subtasks, we get:
  - Clean context for the main agent
  - Parallel exploration possible
  - Natural task decomposition
  - Same agent loop, different contexts

Agent Type Registry:
-------------------
    | Type    | Tools               | Purpose                     |
    |---------|---------------------|---------------------------- |
    | explore | bash, read_file     | Read-only exploration       |
    | code    | all tools           | Full implementation access  |
    | plan    | bash, read_file     | Design without modifying    |

Typical Flow:
-------------
    User: "Refactor auth to use JWT"

    Main Agent:
      1. Task(explore): "Find all auth-related files"
         -> Subagent reads 10 files
         -> Returns: "Auth in src/auth/login.py..."

      2. Task(plan): "Design JWT migration"
         -> Subagent analyzes structure
         -> Returns: "1. Add jwt lib 2. Create utils..."

      3. Task(code): "Implement JWT tokens"
         -> Subagent writes code
         -> Returns: "Created jwt_utils.py, updated login.py"

      4. Summarize changes to user
"""
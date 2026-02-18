# v4: 子代理编排（含通用运行时能力）

v4 在 todo + 多工具基础上引入 `Task` 子代理。升级后主代理与 `run_task` 子代理链路都共享同一套 runtime 能力。

## 模拟问题
主代理调用 `explore` 子代理统计一级目录数并汇总。

## 决策步骤（编号）
1. 主代理解析运行时配置（stream/thinking/session）。
2. 主代理选择 `Task`，参数 `agent_type = "explore"`。
3. `run_task` 启动隔离上下文的子代理（只读工具集）。
4. 子代理执行目录统计命令并回填结果。
5. 子代理返回简要总结给主代理。
6. 主代理基于子结果生成最终汇总答复。
7. trace 按 actor 记录：`main` 与 `subagent:explore`。
8. reasoning 折叠/下展与 session 保存按统一策略执行。

## Mermaid 全过程流程图
```mermaid
flowchart TD
    A[用户输入任务] --> B[main: 解析 RuntimeOptions]
    B --> C[main: LLM 决策]
    C --> D{是否调用 Task}
    D -->|否| E[main 直接回答]
    D -->|是| F[main -> Task(agent_type=explore)]
    F --> G[subagent:explore 启动隔离上下文]
    G --> H[subagent 使用 bash/read_file 执行统计]
    H --> I[subagent 返回 summary]
    I --> J[main 接收 summary 并汇总]
    J --> K[main 输出最终答案]
    E --> L{reasoning?}
    K --> L
    L -->|有| M[预览+折叠+下展]
    L -->|无| N[直接结束]
    M --> O{save-session?}
    N --> O
    O -->|是| P[写 JSONL: main + subagent:explore]
    O -->|否| Q[完成]
    P --> Q
```

## 运行命令（nano-claude）
```bash
conda run -n nano-claude python v4_subagent_demo/subagent.py \
  "请调用 explore 子代理统计项目根目录一级目录数量并汇总" \
  --stream \
  --thinking auto \
  --reasoning-preview-chars 160 \
  --show-llm-response \
  --save-session
```

## 一次真实输出摘录（简短）
```text
[explore] count first-level dirs
$ find . -mindepth 1 -maxdepth 1 -type d | wc -l
17
[explore] done (1 tools, 1.2s)
Main summary: 子代理统计结果显示当前根目录共有 17 个一级目录。
```

[← v3](./v3_todo_agent.md) | [返回 README](../README.md) | [v5 →](./v5_skills_agent.md)

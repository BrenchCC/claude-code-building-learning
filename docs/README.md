# docs

这个目录用于“指导解析”，用于讲清楚每个版本的设计目标、决策流程和运行示例。

## 文件说明

- `quickstart.md`：快速上手流程（环境、运行、排错入口）。
- `v1_bash_is_everything.md`：v1 的最小 agent 闭环与 bash 决策流程。
- `v2_basic_agent_demo.md`：v2 的结构化工具能力（read/write/edit）。
- `v3_todo_agent.md`：v3 的 todo 状态机、约束和状态迁移。
- `v4_subagent.md`：v4 的主代理/子代理编排与上下文隔离。
- `v5_skills_agent.md`：v5 的 Skill 触发、注入路径与执行链路。

## 阅读建议

1. 先看 `quickstart.md` 确认可运行环境。
2. 再按 `v1 -> v2 -> v3 -> v4 -> v5` 顺序阅读。
3. 阅读每个版本文档时，配合对应脚本实际运行一遍。

# V5 Skills Agent 测试问题集

1. 请读取 README.md，并用 5 条要点总结这个仓库。
2. 请在 examples/v5_test/ 下创建 smoke_note.txt，内容写“hello v5 skills agent”。
3. 请把 examples/v5_test/smoke_note.txt 里的 hello 改成 hi，并告诉我修改结果。
4. 这是一个多步骤任务：先扫描项目结构，再找出所有 demo 版本目录，最后给出对比表。请使用 TodoWrite 持续更新进度。
5. 请先用 Explore 子代理定位所有包含 TodoWrite 的文件，再总结各实现差异。
6. 请先用 Plan 子代理制定“给 v5 增加日志模块”的实施方案，然后再执行实现。
7. 请对 v4_subagent_demo/subagent.py 做一次代码审查，重点看安全性和可维护性。
8. 我想做一个天气查询 MCP server，请给出最小可运行的 Python 版本和注册步骤。
9. 我想从零构建一个“代码重构助手”Agent，请给出能力设计、最小工具集和迭代路线。
10. 请对比 v3_todo_agent_demo 与 v5_skills_agent_demo 的核心架构差异，输出表格。
11. 请新增一个 skill：name = git-helper，description = 常见 git 排错与恢复流程，并写出 SKILL.md 初稿。
12. 如果我要求加载一个不存在的技能，请明确报错并列出当前可用技能，然后给出替代方案。
13. 请执行复杂任务：先规划、再拆子任务、再实施，过程中必须持续更新 TodoWrite。
14. 请总结本轮任务中你调用了哪些工具、为何调用，以及最终变更了哪些文件。

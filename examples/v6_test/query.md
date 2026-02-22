# V6 Compression Agent 测试问题集

1. 请读取 README.md，并用 5 条要点总结这个仓库。
2. 请在 examples/v6_test/ 下创建 smoke_note.txt，内容写“hello v6 compression agent”。
3. 请把 examples/v6_test/smoke_note.txt 里的 hello 改成 hi，并告诉我修改结果。
4. 这是一个多步骤任务：先扫描项目结构，再找出所有 demo 版本目录，最后给出对比表。请使用 TodoWrite 持续更新进度。
5. 请先用 Explore 子代理定位所有包含 todo_write 的文件，再总结各实现差异。
6. 请先用 Plan 子代理制定“为 v6 增加一个新的压缩策略”的实施方案，然后再执行实现。
7. 请对 v6_compression_agent_demo/compression_agent.py 做一次代码审查，重点看压缩逻辑和工具调用安全性。
8. 请执行一个会产生较大输出的 bash 命令，并说明你是否进行了输出压缩或截断处理。
9. 请解释 ContextManager 的三层压缩策略，并给出适合触发 auto_compact 的情景。
10. 请验证一个复杂任务：先规划、再拆子任务、再实施，过程中必须持续更新 TodoWrite。
11. 请总结本轮任务中你调用了哪些工具、为何调用，以及最终变更了哪些文件。
12. 请对比 v5_skills_agent_demo 与 v6_compression_agent_demo 的核心架构差异，输出表格。

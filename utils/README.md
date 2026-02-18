# utils

这个目录是 v1-v5 共用的运行时模块，目标是复用“配置解析、LLM 调用、reasoning 展示、日志与会话保存”。

## 模块说明

- `runtime_config.py`
  - 统一解析 CLI + ENV，产出 `RuntimeOptions`。
  - 支持 `add_runtime_args(parser)` 给各版本脚本挂载通用参数。

- `thinking_policy.py`
  - 处理 thinking 能力判定（`auto/toggle/always/never`）。
  - 根据策略生成请求参数（`enable_thinking`/`reasoning_effort`）。

- `llm_call.py`
  - 封装 stream/non-stream 两条调用路径。
  - 统一返回 `assistant_content`、`assistant_reasoning`、`tool_calls`、`raw_metadata`。
  - 支持 thinking 参数失败后去参重试一次。

- `reasoning_renderer.py`
  - 处理 reasoning 预览、折叠、下展交互（`r`）。

- `trace_logger.py`
  - 控制每轮 LLM 响应日志输出（assistant/tool/reasoning 摘要）。

- `session_store.py`
  - 会话落盘为 JSONL。
  - 文件命名格式：`<model>_<YYYYMMDD_HHMMSS>.jsonl`。

## 在 agent 中的典型接入顺序

1. `add_runtime_args` + `runtime_options_from_args`
2. `resolve_thinking_policy`
3. `call_chat_completion`
4. `ReasoningRenderer` 渲染 reasoning
5. `TraceLogger` 输出调试日志
6. `SessionStore` 记录 assistant/tool 事件

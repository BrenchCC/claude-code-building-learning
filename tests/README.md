# tests

这个目录存放项目测试脚本，分为两类：

1. 版本行为测试（`test_v1.py` ~ `test_v5.py`）
2. 通用运行时能力测试（`test_runtime_config.py`、`test_thinking_policy.py`、`test_reasoning_renderer.py`、`test_session_store.py`）

## 文件说明

- `utils.py`：测试公共工具（LLM 客户端、工具 schema、本地工具执行器、测试循环）。
- `helpers.py`：兼容导入层，复用 `utils.py` 的能力。
- `test_v1.py`：v1（bash-only）能力测试。
- `test_v2.py`：v2（文件工具）能力测试。
- `test_v3.py`：v3（todo 状态机）测试。
- `test_v4.py`：v4（子代理与上下文隔离）测试。
- `test_v5.py`：v5（skill 注入）测试。
- `test_runtime_config.py`：CLI/ENV 优先级与解析测试。
- `test_thinking_policy.py`：thinking 能力判定与参数重试测试。
- `test_reasoning_renderer.py`：reasoning 预览/折叠/下展测试。
- `test_session_store.py`：会话 JSONL 文件命名与结构测试。

## 常用命令

```bash
python tests/test_runtime_config.py
python tests/test_thinking_policy.py
python tests/test_reasoning_renderer.py
python tests/test_session_store.py
```

```bash
python tests/test_v1.py
python tests/test_v2.py
python tests/test_v3.py
python tests/test_v4.py
python tests/test_v5.py
```

## 运行前提

- 会读取项目根目录 `.env`。
- 如需覆盖测试模型配置，可使用：
  - `TEST_BASE_URL`
  - `TEST_API_KEY`
  - `TEST_MODEL`

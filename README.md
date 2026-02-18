# nano-claude-code - 从零开始学 AI 编程助手

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](./LICENSE)

## 项目简介
这是一个从零学习 LLM Coding Agent 的教学仓库。核心主线是 v1-v5 五个可运行脚本：
- v1：bash 单工具闭环
- v2：结构化文件工具
- v3：todo 状态机
- v4：子代理编排
- v5：skill 动态注入

本仓库还包含完整测试脚本、示例输入、以及 skills 下的辅助脚本（如 PDF 处理脚本）。

## 项目结构
```text
.
├── v1_bash_agent_demo/
│   └── bash_agent.py                      # v1 主脚本：bash 单工具 agent
├── v2_basic_agent_demo/
│   └── basic_agent.py                     # v2 主脚本：bash + 文件工具
├── v3_todo_agent_demo/
│   └── todo_agent.py                      # v3 主脚本：todo_write 状态机
├── v4_subagent_demo/
│   └── subagent.py                        # v4 主脚本：Task 子代理编排
├── v5_skills_agent_demo/
│   └── skills_agent.py                    # v5 主脚本：Skill 动态注入
├── v6_compression_agent_demo/
│   └── compression_agent.py               # v6 主脚本：Compression 子代理
├── utils/                                 # v1-v5 通用运行时模块
│   ├── runtime_config.py                  # CLI/ENV 解析与 RuntimeOptions
│   ├── thinking_policy.py                 # thinking 能力探测与参数注入
│   ├── llm_call.py                        # stream/non-stream 统一调用封装
│   ├── reasoning_renderer.py              # reasoning 预览/折叠/下展
│   ├── trace_logger.py                    # LLM 响应调试日志
│   └── session_store.py                   # 会话 JSONL 落盘
├── tests/                                 # 测试与测试辅助
│   ├── helpers.py                         # 通用测试运行器与工具模拟
│   ├── utils.py                           # 共享测试工具定义
│   ├── test_v1.py                         # v1 行为测试
│   ├── test_v2.py                         # v2 行为测试
│   ├── test_v3.py                         # v3 行为/约束测试
│   ├── test_v4.py                         # v4 子代理测试
│   ├── test_v5.py                         # v5 skill 测试
│   ├── test_runtime_config.py             # 通用配置解析测试
│   ├── test_thinking_policy.py            # thinking 策略测试
│   ├── test_reasoning_renderer.py         # reasoning 渲染测试
│   └── test_session_store.py              # session 落盘测试
├── skills/                                # 可加载技能与辅助脚本
│   ├── agent-builder/
│   │   └── scripts/init_agent.py          # 生成 agent 脚手架
│   ├── code-review/
│   │   └── SKILL.md                       # 代码评审技能
│   ├── mcp-builder/
│   │   └── SKILL.md                       # MCP 构建技能
│   └── pdf/
│       ├── SKILL.md                       # PDF 处理技能
│       └── scripts/
│           ├── check_fillable_fields.py
│           ├── extract_form_field_info.py
│           ├── fill_fillable_fields.py
│           ├── convert_pdf_to_images.py
│           ├── create_validation_image.py
│           ├── check_bounding_boxes.py
│           ├── check_bounding_boxes_test.py
│           └── fill_pdf_form_with_annotations.py
├── examples/                              # 示例输入/脚本
│   ├── v1_v2_test/hello.py
│   └── v3_test/scan_py_funcs.py
├── prompts/
│   ├── v1_bash_agent.md
│   ├── v2_basic_agent.md
│   ├── v3_todo_agent.md
│   ├── v4_subagent.md
│   └── v5_skills_agent.md
├── docs/                                  # 指导解析文档
├── requirements.txt
└── .env.example
```

### 脚本职责清单（按入口）
| 入口脚本 | 作用 | 建议何时使用 |
|---|---|---|
| `v1_bash_agent_demo/bash_agent.py` | 最小可用 agent 闭环，便于理解 tool-calling 本质 | 入门、验证模型工具调用 |
| `v2_basic_agent_demo/basic_agent.py` | 增加结构化文件工具，降低纯 bash 文件操作复杂度 | 日常文件读写与小改动 |
| `v3_todo_agent_demo/todo_agent.py` | 引入 `todo_write`，显式规划与状态追踪 | 多步骤任务、有进度要求 |
| `v4_subagent_demo/subagent.py` | 引入 `Task`，支持 explore/plan/code 角色分工 | 复杂任务拆解与上下文隔离 |
| `v5_skills_agent_demo/skills_agent.py` | 引入 `Skill`，按需加载领域知识 | 需要领域知识（PDF/MCP/评审） |

## 快速开始
### 1) 创建并激活 Conda 环境
```bash
conda create -n nano-claude python=3.10 -y
conda activate nano-claude
```

### 2) 安装依赖
```bash
pip install -r requirements.txt
```

### 3) 配置环境变量
```bash
cp .env.example .env
```

`.env` 示例：
```env
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3:latest
```

### 4) 推荐运行方式
激活环境后，直接使用 `python` 运行脚本：
```bash
python <script.py> <args>
```

## v1-v5 通用运行时功能（已统一）
以下参数在 v1-v5 均可用：
- `--show-llm-response / --no-show-llm-response`
- `--stream / --no-stream`
- `--thinking {auto,on,off}`
- `--reasoning-effort {none,low,medium,high}`
- `--reasoning-preview-chars <int>`
- `--save-session / --no-save-session`
- `--session-dir <path>`

对应 ENV（CLI 优先于 ENV）：
- `AGENT_SHOW_LLM_RESPONSE`
- `AGENT_STREAM`
- `AGENT_THINKING_MODE`
- `AGENT_REASONING_EFFORT`
- `AGENT_THINKING_CAPABILITY`
- `AGENT_REASONING_PREVIEW_CHARS`
- `AGENT_SAVE_SESSION`
- `AGENT_SESSION_DIR`
- `AGENT_THINKING_PARAM_STYLE`

### 参数说明（作用 + 默认值）
| CLI 参数 | ENV 变量 | 默认值 | 说明 |
|---|---|---|---|
| `--show-llm-response` | `AGENT_SHOW_LLM_RESPONSE` | `false` | 打印每轮 LLM 调试信息（assistant 文本、tool_calls 摘要、reasoning 摘要）。 |
| `--stream` | `AGENT_STREAM` | `false` | 启用流式输出；关闭时一次性返回完整回答。 |
| `--thinking {auto,on,off}` | `AGENT_THINKING_MODE` | `auto` | 控制 reasoning 展示/请求策略：`on` 尽量开启，`off` 关闭展示，`auto` 自动。 |
| `--reasoning-effort {none,low,medium,high}` | `AGENT_REASONING_EFFORT` | `none` | 请求模型推理强度（若 provider 支持）。 |
| `--reasoning-preview-chars <int>` | `AGENT_REASONING_PREVIEW_CHARS` | `200` | reasoning 预览字符数上限，超出后折叠并可下展。 |
| `--save-session` | `AGENT_SAVE_SESSION` | `false` | 开启会话落盘（JSONL）。 |
| `--session-dir <path>` | `AGENT_SESSION_DIR` | `sessions` | 会话保存目录。 |

额外 ENV（无 CLI 对应）：
- `AGENT_THINKING_CAPABILITY`（默认 `auto`）：thinking 能力模式，`auto/toggle/always/never`。  
  - `auto`：启动轻量探测后自动判定。
- `AGENT_THINKING_PARAM_STYLE`（默认 `auto`）：thinking 参数风格，`auto/enable_thinking/reasoning_effort/both`。  
  - `auto`：根据 provider 兼容性自动选择。

优先级规则：
1. CLI 参数  
2. ENV 变量  
3. 内置默认值

## 核心脚本功能总览
| 脚本 | 主要能力 | 典型用途 | 运行示例 |
|---|---|---|---|
| `v1_bash_agent_demo/bash_agent.py` | bash 单工具 | 用最小闭环完成查询/改动 | `python v1_bash_agent_demo/bash_agent.py "列出当前目录"` |
| `v2_basic_agent_demo/basic_agent.py` | `bash/read_file/write_file/edit_file` | 结构化读写代码文件 | `python v2_basic_agent_demo/basic_agent.py "读取 README 前10行并总结"` |
| `v3_todo_agent_demo/todo_agent.py` | v2 + `todo_write` | 多步骤任务拆解与进度追踪 | `python v3_todo_agent_demo/todo_agent.py "先规划两步再执行"` |
| `v4_subagent_demo/subagent.py` | v3 + `Task` 子代理 | explore/plan/code 角色分工 | `python v4_subagent_demo/subagent.py "调用 explore 分析项目"` |
| `v5_skills_agent_demo/skills_agent.py` | v4 + `Skill` 动态注入 | 任务按需加载领域知识 | `python v5_skills_agent_demo/skills_agent.py "加载 code-review skill 检查脚本"` |

## 每个主脚本可展示的“功能使用”示例
### v1: bash 单工具 + 流式 + 会话保存
```bash
python v1_bash_agent_demo/bash_agent.py \
  "只用 bash 统计根目录一级目录数量" \
  --stream --thinking auto --reasoning-effort low --save-session
```

### v2: 结构化文件读取
```bash
python v2_basic_agent_demo/basic_agent.py \
  "用 read_file 读取 README.md 前 10 行并总结，不使用 cat" \
  --show-llm-response --no-stream
```

### v3: todo 状态机
```bash
python v3_todo_agent_demo/todo_agent.py \
  "先 todo_write 规划两步，再执行并标记 completed" \
  --thinking on --reasoning-effort medium
```

### v4: 子代理编排
```bash
python v4_subagent_demo/subagent.py \
  "主代理调用 explore 子代理统计一级目录并汇总" \
  --stream --reasoning-preview-chars 160
```

### v5: skill 注入
```bash
python v5_skills_agent_demo/skills_agent.py \
  "先加载 code-review skill，再只读检查 v2_basic_agent_demo/basic_agent.py 并给两点建议" \
  --show-llm-response --save-session
```

## 测试脚本总览与用法
### 新增通用能力测试
| 脚本 | 覆盖点 | 命令 |
|---|---|---|
| `tests/test_runtime_config.py` | CLI/ENV 优先级、布尔/枚举解析 | `python tests/test_runtime_config.py` |
| `tests/test_thinking_policy.py` | capability 组合、去参重试 | `python tests/test_thinking_policy.py` |
| `tests/test_reasoning_renderer.py` | 预览截断、折叠、下展 | `python tests/test_reasoning_renderer.py` |
| `tests/test_session_store.py` | 文件命名、JSONL 结构 | `python tests/test_session_store.py` |

### 版本测试脚本
| 脚本 | 目标 |
|---|---|
| `tests/test_v1.py` | bash-only 行为 |
| `tests/test_v2.py` | 多工具协作与文件操作 |
| `tests/test_v3.py` | todo 约束与状态流转 |
| `tests/test_v4.py` | 子代理类型与上下文隔离 |
| `tests/test_v5.py` | skill 加载与注入机制 |

运行示例：
```bash
python tests/test_v3.py
```


## docs 指导解析（每部分讲解什么）
- `docs/quickstart.md`：快速启动路径与最小可运行步骤。
- `docs/v1_bash_is_everything.md`：讲解 v1 的最小 Agent 闭环与 bash 决策流程。
- `docs/v2_basic_agent_demo.md`：讲解结构化文件工具如何替代纯 bash 文件操作。
- `docs/v3_todo_agent.md`：讲解 todo 状态机、约束校验、状态迁移。
- `docs/v4_subagent.md`：讲解主代理与子代理分工、上下文隔离、任务回传。
- `docs/v5_skills_agent.md`：讲解 Skill 触发、注入路径与后续工具执行。

## 文档导航
- `docs/quickstart.md`
- `docs/v1_bash_is_everything.md`
- `docs/v2_basic_agent_demo.md`
- `docs/v3_todo_agent.md`
- `docs/v4_subagent.md`
- `docs/v5_skills_agent.md`

## 常见问题
### 1) 连不上模型服务
- 检查 `.env` 是否正确。
- 检查本地 Ollama / 远端 API 是否可访问。

### 2) 脚本有参数但不生效
- 先看 `--help`：`python v3_todo_agent_demo/todo_agent.py --help`
- 确认是否被 ENV 覆盖（CLI 优先）。

### 3) 为什么没有保存会话文件
- 需要显式开启 `--save-session`（默认关闭）。
- 默认目录是 `sessions/`，可用 `--session-dir` 改写。

## License
MIT，见 `LICENSE`。

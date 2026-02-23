# v6: 上下文压缩

**核心洞察：遗忘是一种能力，不是缺陷。**

v0-v5 有一个隐含假设：对话历史可以无限增长。现实中不是这样。

## 问题

```
200K token 的上下文窗口：
  [系统提示词]     ~2K tokens
  [工具定义]        ~8K tokens
  [对话历史]        持续增长...
  [第 50 次工具调用] -> 接近 180K tokens
  [第 60 次工具调用] -> 超过 200K, 请求失败
```

一个复杂的重构任务可能需要 100+ 次工具调用。不压缩，Agent 就会撞墙。

## 两层压缩流水线

不是一种压缩，而是两层递进：

```
每轮 Agent 循环：
+------------------+
| 工具调用结果      |
+------------------+
        |
        v
[第 1 层: 微压缩]              (静默, 每轮自动)
保留最近 3 个工具结果。
替换更早的结果为:
"[Old tool result content cleared]"
仅当预估节省 >= MIN_SAVINGS (20000 tokens) 时才清理。
        |
        v
[检查: tokens > threshold?]    threshold = ctx_window - output_reserve - 13000
        |
   否 --+-- 是
   |         |
   v         v
继续    [第 2 层: 自动压缩]          (接近上限时)
        整体对话压缩为摘要。
        恢复最近 5 个文件。
        替换全部消息（无保留最近 N 条）。

全程: 完整转录保存到磁盘 (JSONL)。
```

| 层级 | 触发 | 做什么 | 用户感知 |
|------|------|--------|---------|
| 微压缩 | 每轮自动 | 清理旧工具输出 | 无感知 |
| 自动压缩 | 接近上限时 | 整个对话压缩为摘要 | 看到提示 |

## 动态阈值

自动压缩的阈值不是固定常量，而是根据模型的实际限制动态计算：

```python
def auto_compact_threshold(context_window=200000, max_output=16384):
    """threshold = context_window - min(max_output, 20000) - 13000"""
    output_reserve = min(max_output, 20000)
    return context_window - output_reserve - 13000
    # 200K 窗口: 200000 - 16384 - 13000 = 170616
```

13000 的缓冲用于系统提示词、工具定义和其他开销。`min(max_output, 20000)` 的上限防止 max_output 很大的模型过早触发压缩。

## should_compact: 阈值检查

`should_compact` 仅检查总 token 数是否超过阈值：

```python
def should_compact(self, messages):
    total = sum(self.estimate_tokens(json.dumps(m, default=str)) for m in messages)
    return total > self.TOKEN_THRESHOLD
```

没有额外的收益保护。收益保护在微压缩中实现（见下文）。

## 微压缩：静默清理

每轮对话后，替换旧的大型工具输出为占位符，保留最近几个：

```python
COMPACTABLE_TOOLS = {"bash", "read_file", "write_file", "edit_file",
                     "glob", "grep", "list_dir", "notebook_edit"}
KEEP_RECENT = 3

def micro_compact(self, messages):
    """替换旧的大型工具结果为占位符"""
    tool_result_indices = find_tool_results(messages, COMPACTABLE_TOOLS)
    to_compact = tool_result_indices[:-KEEP_RECENT]

    # 预估总节省量，低于 MIN_SAVINGS (20000) 则跳过
    estimated_savings = sum(estimate_tokens(block) for block in to_compact if estimate_tokens(block) > 1000)
    if estimated_savings >= MIN_SAVINGS:
        for block in to_compact:
            if estimate_tokens(block) > 1000:
                block["content"] = "[Old tool result content cleared]"

    return messages
```

关键：只清理**内容**，保留工具调用的结构。模型仍然知道它调用过什么，只是看不到旧输出了。仅当预估节省量 >= MIN_SAVINGS（20000 tokens）时才执行清理。

## Token 估算

使用基于字符数的公式估算 token 数：

```python
@staticmethod
def estimate_tokens(text: str) -> int:
    # ~4 characters per token
    return len(text) // 4
```

约 4 个字符对应 1 个 token。

## 自动压缩阈值

阈值通过公式动态计算，不是固定百分比：

```python
def auto_compact_threshold(context_window=200000, max_output=16384):
    output_reserve = min(max_output, 20000)
    return context_window - output_reserve - 13000
    # 200K 窗口: 200000 - 16384 - 13000 = 170616 (85.3%)
```

注意：本仓库的简化实现不包含外部文件变更监听或系统级附件注入逻辑。

## 自动压缩：替换全部消息

当上下文超过动态阈值时触发。auto_compact 替换整个消息列表，没有"保留最近 N 条"的行为：

```python
def auto_compact(self, messages):
    # 1. 保存完整转录到磁盘（永不丢失）
    self.save_transcript(messages)

    # 2. 压缩前捕获最近读取的文件
    restored_files = self.restore_recent_files(messages)

    # 3. 用模型生成摘要
    summary = call_chat_completion(
        client = LLM_SERVER,
        model = MODEL,
        messages = [
            {"role": "system", "content": "You are a conversation summarizer. Be concise but thorough."},
            {"role": "user", "content": "Summarize this conversation..."},
        ],
        max_tokens = 2000,
    ).assistant_content

    # 4. 用摘要替换全部消息（无保留最近 N 条）
    result = [
        {"role": "user", "content": f"[Conversation compressed]\n\n{summary}"},
        {"role": "assistant", "content": "Understood. I have the context from the compressed conversation. Continuing work."},
    ]
    # 恢复文件内容
    for rf in restored_files:
        result.append(rf)
        result.append({"role": "assistant", "content": "Noted, file content restored."})
    return result
```

**关键设计**：摘要注入到对话历史（user message），不修改系统提示词。

## 压缩后文件恢复

压缩后，最近读取的文件会被恢复到上下文中，避免 Agent 需要重新读取：

```python
MAX_RESTORE_FILES = 5
MAX_RESTORE_TOKENS_PER_FILE = 5000
MAX_RESTORE_TOKENS_TOTAL = 50000

def restore_recent_files(messages):
    """扫描消息中的 read_file 调用，恢复最近读取的文件"""
    # 从后往前遍历消息，收集不重复的文件路径
    # 读取每个文件，截断到 MAX_RESTORE_TOKENS_PER_FILE
    # 达到 MAX_RESTORE_FILES 或 MAX_RESTORE_TOKENS_TOTAL 时停止
```

这确保 Agent 在压缩后仍保留对最近工作文件的感知，无需重新读取。

## 大型输出降级

单次工具输出过大时，存盘返回预览：

```python
def handle_large_output(self, output: str) -> str:
    if self.estimate_tokens(output) <= self.MAX_OUTPUT_TOKENS:
        return output
    filename = f"output_{int(time.time())}.txt"
    path = TRANSCRIPTS_DIR / filename
    path.write_text(output)
    preview = output[:2000]
    return f"Output too large ({self.estimate_tokens(output)} tokens). Saved to: {path}\n\nPreview:\n{preview}..."
```

## 子代理也压缩

v6 的子代理有独立的上下文窗口，同样执行压缩：

```python
def run_subagent(prompt, agent_type):
    sub_messages = [{"role": "user", "content": prompt}]

    while True:
        if should_compact(sub_messages):
            sub_messages = auto_compact(sub_messages)
        sub_messages = micro_compact(sub_messages)

        response = call_api(sub_messages)
        if response.stop_reason != "tool_use":
            break
        # ...

    return extract_final_text(response)
```

压缩的磁盘持久化设计为后续机制奠定基础：后续章节引入的任务系统和多代理机制，数据都存在磁盘上，不受压缩影响。

## 对比

| 方面 | v5 以前（无压缩） | v6（两层压缩 + 转录） |
|------|-------------|---------------|
| 最大对话长度 | 受限于上下文窗口 | 理论上无限 |
| 长任务可靠性 | 上下文溢出后崩溃 | 优雅降级 |
| 历史数据 | 全在内存 | 磁盘持久化 + 内存摘要 |
| 恢复能力 | 无 | 从摘要或转录恢复 |

## 更深的洞察

> **人类的工作记忆也是有限的。**

我们不会记住写过的每一行代码，而是记住"做了什么、为什么做、当前状态"。压缩模拟了这种认知模式：

- 微压缩 = 短期记忆自动衰减
- 全量压缩 = 从细节记忆转为概念记忆
- 磁盘转录 = 可回溯的长期记忆

完整记录永远在磁盘上。压缩只影响工作记忆，不影响存档。

---

**上下文有限，工作无限。压缩让 Agent 永不停歇。**

[← v5](./v5_skills_agent.md) | [返回 README](../README.md)

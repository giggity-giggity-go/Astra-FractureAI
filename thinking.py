"""Filtering helpers for hidden model reasoning content."""

import re
from typing import Any, List

def clean_thinking(text: str) -> str:
    """Non-streaming: strip inline <think>...</think>, <thought>...</thought>, and code block thinking (§6.1).

    选型背景(设计 doc §6.1 + 用户在 brainstorming 阶段确定的 Plan A):
        OpenAI SDK 在 mini-max-M3 / 部分国产兼容模型下,
        `reasoning_effort="low"` 与 `extra_body={"thinking":{"type":"disabled"}}` 都会被忽略,
        thinking 仍以 <think>...</think> 形式漏到 content 字段。
        业内调研过的 LiteLLM / LangChain / one-api / new-api 都各有边界(详见调研报告),
        没有"一行 sdk 调用就 ok"的方案,所以选自实现 regex + 流式状态机。

    Layer 3(三层防御的兜底层)职责:
        Layer 1 reasoning_effort     → 标准 OpenAI 通道,部分模型有效
        Layer 2 extra_body.thinking  → 私有逃生通道,MiniMax 文档承诺但实测无效
        Layer 3 clean_thinking(本函数)→ 前两层全失败时唯一可靠保证,绝不能省

    覆盖的三种 thinking 格式:
        - <think>...</think>        多数模型(MiniMax / Qwen / DeepSeek 部分)
        - <thought>...</thought>     部分老版本/不同方言
        - ```thinking ... ```         markdown 代码块风格(罕见但出现过)

    边界条件:模型可能输出**未闭合**的 <think>(被截断);
        第三、第四条 regex 处理这种情况,不抛异常、尽力保留正文。
    """
    if not text:
        return ""
    # Strip paired <think>...</think> and <thought>...</thought>
    cleaned = re.sub(r"<(think|thought)>[\s\S]*?</\1>", "", text, flags=re.IGNORECASE)
    # Strip markdown ```thinking ... ``` blocks
    cleaned = re.sub(r"```(?:thinking|thought)[\s\S]*?```", "", cleaned, flags=re.IGNORECASE)
    # Strip unclosed leading think/thought or unclosed trailing blocks
    cleaned = re.sub(r"^<(?:think|thought)>[\s\S]*?(?=\n\n|\Z)", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<(?:think|thought)>[\s\S]*?\Z", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def extract_final_text(choice_or_message: Any) -> str:
    """Extract final answer from OpenAI SDK response, ignoring reasoning_content (§6.2)."""
    if hasattr(choice_or_message, "message"):
        msg = choice_or_message.message
    else:
        msg = choice_or_message

    content = getattr(msg, "content", "") or ""
    return clean_thinking(content)


class StreamThinkingStripper:
    """Finite State Machine for real-time streaming <think>...</think> removal (§7.1)."""

    def __init__(self) -> None:
        self.buffer = ""
        self.in_think = False

    def feed(self, delta: str) -> str:
        if not delta:
            return ""
        self.buffer += delta
        output: List[str] = []

        while self.buffer:
            if not self.in_think:
                start_idx = self.buffer.find("<think>")
                if start_idx == -1:
                    # Check for partial prefix like "<", "<th", etc.
                    partial_match = False
                    for i in range(1, min(len(self.buffer), 7) + 1):
                        suffix = self.buffer[-i:]
                        if "<think>".startswith(suffix):
                            output.append(self.buffer[:-i])
                            self.buffer = suffix
                            partial_match = True
                            break
                    if not partial_match:
                        output.append(self.buffer)
                        self.buffer = ""
                    break
                else:
                    output.append(self.buffer[:start_idx])
                    self.buffer = self.buffer[start_idx + len("<think>"):]
                    self.in_think = True
            else:
                end_idx = self.buffer.find("</think>")
                if end_idx == -1:
                    # In think block, discard everything except possible partial closing tag
                    partial_match = False
                    for i in range(1, min(len(self.buffer), 8) + 1):
                        suffix = self.buffer[-i:]
                        if "</think>".startswith(suffix):
                            self.buffer = suffix
                            partial_match = True
                            break
                    if not partial_match:
                        self.buffer = ""
                    break
                else:
                    self.buffer = self.buffer[end_idx + len("</think>"):]
                    self.in_think = False

        return "".join(output)

    def flush(self) -> str:
        """Flush any remaining non-think buffer at stream end."""
        if not self.in_think and self.buffer:
            res = self.buffer
            self.buffer = ""
            return res
        self.buffer = ""
        return ""

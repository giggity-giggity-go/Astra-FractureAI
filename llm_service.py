"""Prompt construction and OpenAI-compatible LLM routing."""

import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

from image_service import build_image_url

SYSTEM_PROMPT = """You are a senior orthopedic radiology AI assistant. You receive:
  1) An X-ray image attached by the user
  2) A structured JSON payload containing YOLO model outputs (anatomical
     position, fracture extent, morphological classification) with per-detection
     confidence scores

Produce a thorough, clinically rigorous assessment combining visual evidence
with the YOLO findings. Structure your response in plain Markdown with these
sections:

  ## Impression
  One-paragraph synthesis: suspected fracture location, fracture line morphology,
  displacement tendency, and confidence calibration against the YOLO scores.

  ## YOLO Correlation
  For each YOLO detection above 0.25 confidence, explain how the visual
  evidence supports or contradicts the model's call. Flag any discrepancy.

  ## Recommended Workup
  Suggest further imaging (CT 3D reconstruction, MRI, dedicated views) only
  when clinically warranted. Avoid ordering studies reflexively.

  ## Acute Management
  Immobilization, weight-bearing status, splint vs cast, specialty referral
  urgency, red-flag symptoms that should trigger ED return.

  ## Safety Disclaimer (mandatory final paragraph)
  State explicitly that this analysis is AI-assisted and does NOT replace
  in-person evaluation by a licensed radiologist or orthopedic surgeon.

Constraints:
  - Use precise anatomical terminology; do not invent eponyms
  - Quantify uncertainty; never fabricate lab values or measurements
  - If the image quality is insufficient, say so and recommend repeat imaging
  - Output in English unless the user explicitly requests another language"""


USER_TEXT_TEMPLATE = (
    "Below is the patient's X-ray image and the consolidated YOLO detection "
    "payload from three parallel models (position / range / kind).\n\n"
    "**YOLO detection payload:**\n"
    "```json\n{payload}\n```\n\n"
    "Please provide your clinical assessment per the system instructions."
)


def build_clinical_messages(
    image_base64: str,
    mime: str,
    yolo_result: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Build standardized prompt for orthopedic clinical advice combining vision & YOLO data (§5.4).

    Returns OpenAI Vision chat messages: 1 system (role+task) + 1 user (text payload + image_url).
    """
    yolo_summary = {
        "positions": yolo_result.get("positions", []),
        "range": yolo_result.get("range", []),
        "kind": yolo_result.get("kind", []),
    }

    # ensure_ascii=False keeps any non-ASCII (e.g. patient names) readable;
    # the surrounding labels are English so the LLM gets English keys.
    user_text = USER_TEXT_TEMPLATE.format(
        payload=json.dumps(yolo_summary, ensure_ascii=False, indent=2)
    )

    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_text},
                build_image_url(image_base64, mime=mime, detail="high"),
            ],
        },
    ]


def chat_once(client: Any, logger: logging.Logger, model: str, messages: List[Dict[str, Any]], stream: bool = False) -> Any:
    """Execute single chat completion with 3-layer thinking defense (§5.3 & §8.2).

    三层防御叠加顺序(详见 design doc §8.2 + 调研报告 `extra-body-vs-reasoning-effort`):
        Layer 1: `reasoning_effort="low"`
            OpenAI 标准字段,标准 chat.completions 路径识别;
            gpt-6-astra / o-series / deepseek-reasoner 等都识别(取值范围略不同)。
        Layer 2: `extra_body={"thinking": {"type": "disabled"}}`
            厂商私有逃生通道,SDK 只做透传;MiniMax 文档承诺支持,实测**无效**(已记入 memory)。
        Layer 3: 调用方拿到响应后,流式走 StreamThinkingStripper、
            非流式走 extract_final_text() → clean_thinking()。
            **Layer 3 是唯一可靠保证**,无论上层模型怎么换,只要它吐 thinking 就能兜住。

    为什么不 fail-fast 直接报错:
        部分老版本 / 国产兼容模型对 reasoning_effort / extra_body 严格 schema 校验,
        不识别会直接 400。这里"被忽略"和"被拒绝"是两种行为 ——
        静默忽略无害(多几字节 JSON),严格拒绝必须降级,所以 try/except 是必要的。
        降级后的"裸调"等价于 OpenAI 1.x 旧版 SDK 行为,绝大多数模型都能跑。
    """
    params: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": 2000,
        "stream": stream,
        # Layer 1: reasoning_effort (OpenAI standard)
        "reasoning_effort": "low",
        # Layer 2: extra_body thinking disabled (MiniMax/third-party vendor fallback)
        "extra_body": {"thinking": {"type": "disabled"}},
    }

    try:
        return client.chat.completions.create(**params)
    except Exception as e:
        # If model rejected extra_body or reasoning_effort, degrade gracefully.
        # 这里必须用宽 except — OpenAI SDK 的异常类型在版本间不稳定(APIError /
        # BadRequestError / TypeError 都见过),窄 except 会漏;后续由上层
        # explain_with_fallback 再做模型级兜底。
        logger.warning("Primary param invoke failed on model %s: %s. Retrying without extra params.", model, e)
        params.pop("reasoning_effort", None)
        params.pop("extra_body", None)
        return client.chat.completions.create(**params)


def model_candidates(primary_model: str, fallback_model: str, requested_model: Optional[str] = None) -> List[str]:
    """Return the requested configured model followed by the configured fallback."""
    preferred = requested_model or primary_model
    return list(dict.fromkeys(model for model in (preferred, fallback_model) if model))


def explain_with_fallback(
    image_base64: str,
    mime: str,
    yolo_result: Dict[str, Any],
    requested_model: Optional[str] = None,
    *,
    primary_model: str,
    fallback_model: str,
    client: Any,
    logger: logging.Logger,
    chat_fn: Callable[..., Any],
    extract_fn: Callable[[Any], str],
) -> Tuple[str, str]:
    """Execute non-streaming explanation with primary -> fallback model routing (§8.2).

    双层 fallback 的设计意图(为什么不像 chat_once 那样只调一次然后报错):
        1) 医疗 Demo 的成功率 > 完美性 —— Product Hunt 评审可能 5 秒后刷新页面,
           多换一次模型只多花 2-4 秒,但换来的"还有响应"远比"500 Internal Error"好。
        2) Astra 模型 2026-09-18 才上线,前 48 小时配额可能瞬时打爆,fallback 自动顶上。
        3) Primary 失败模式可观察:日志里能区分 "primary 卡顿" vs "primary 拒绝 thinking 参数"。

    失败兜底边界:
        - 两层都返回空字符串(content=="" / None)也视作失败,继续 fallback。
        - 两层全抛异常才上抛 RuntimeError → /api/explain 捕获后转 502。
        - 不在这里做"重试同模型",重复失败已说明不是网络抖动,重试没意义。
    """
    messages = build_clinical_messages(image_base64, mime, yolo_result)
    candidates = model_candidates(primary_model, fallback_model, requested_model)

    for index, model in enumerate(candidates):
        label = "primary" if index == 0 else "fallback"
        try:
            logger.info("Calling %s LLM: %s", label, model)
            resp = chat_fn(model, messages, stream=False)
            content = extract_fn(resp.choices[0])
            if content:
                return content, model
            logger.warning("%s LLM %s returned empty content", label.capitalize(), model)
        except Exception as e:
            logger.error("%s LLM %s failed: %s", label.capitalize(), model, e)

    # 上层 /api/explain 会把 RuntimeError 翻译成 HTTP 502 Bad Gateway:
    #   502 而非 500,因为 LLM 是"上游网关"角色,符合 RFC 7231 对 Bad Gateway 的语义。
    #   前端拿到 502 时显示"AI 服务暂不可用,请稍后重试",而非"系统错误"。
    raise RuntimeError("All LLM backends failed to generate explanation")

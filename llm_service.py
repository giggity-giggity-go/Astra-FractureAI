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
    yolo_summary = {
        "positions": yolo_result.get("positions", []),
        "range": yolo_result.get("range", []),
        "kind": yolo_result.get("kind", []),
    }
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


def _supports_optional_parameters(error: Exception) -> bool:
    message = str(error).lower()
    return any(marker in message for marker in (
        "unknown parameter",
        "unsupported parameter",
        "unrecognized request argument",
        "extra_body",
        "reasoning_effort",
    )) and any(marker in message for marker in ("parameter", "argument", "extra_body", "reasoning_effort"))


def chat_once(client: Any, logger: logging.Logger, model: str, messages: List[Dict[str, Any]], stream: bool = False) -> Any:
    """Execute single chat completion with 3-layer thinking defense (§5.3 & §8.2).

    Retry policy: same model is retried only when the upstream rejects the
    optional thinking parameters (unsupported parameter / extra_body /
    reasoning_effort schema). All other errors propagate so explain_with_fallback
    can route to the configured fallback model. Logging uses the exception
    type only — never the raw exception text — so provider URLs, request IDs,
    and bearer tokens are not echoed into application logs.
    """
    params: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": 2000,
        "stream": stream,
        "reasoning_effort": "low",
        "extra_body": {"thinking": {"type": "disabled"}},
    }

    try:
        return client.chat.completions.create(**params)
    except Exception as error:
        if not _supports_optional_parameters(error):
            raise
        logger.warning("LLM rejected optional thinking parameters for model %s; retrying without them", model)
        params.pop("reasoning_effort")
        params.pop("extra_body")
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
    """Execute non-streaming explanation with primary -> fallback model routing (§8.2)."""
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
        except Exception as error:
            logger.warning("%s LLM %s failed with %s", label.capitalize(), model, type(error).__name__)
    raise RuntimeError("All LLM backends failed to generate explanation")

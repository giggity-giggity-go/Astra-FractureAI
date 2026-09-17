"""Astra-FractureAI Backend Service
Flask + Ultralytics Cloud YOLO (3 models parallel) + OpenAI SDK (Vision + 3-layer thinking defense + fallback)

Specification: D:\\WORKSTATION\\ChatGPT Competition\\Astra-FractureAI后端设计.md
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import io
import json
import logging
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, stream_with_context
from flask_cors import CORS
from openai import OpenAI
from PIL import Image, ImageOps, UnidentifiedImageError
import requests

# ==============================================================================
# 1. Environment & Logging Configuration (§9)
# ==============================================================================
_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_PATH = os.path.join(_BASE_DIR, ".env")
# override=True:让 .env 里的值覆盖 shell 环境变量。否则如果用户在系统层
# `setx YOLO_API_KEY=...` 设过旧值(或者 IDE 帮忙 export 过),.env 改了也没用,
# app 永远读到 shell 里的旧值。这是 2026-09-17 E2E spike 反复 401 的根因之一。
if os.path.exists(_ENV_PATH):
    load_dotenv(_ENV_PATH, override=True)
else:
    load_dotenv(override=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("AstraFractureAI")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
# 模型优先级(详见 design doc §5.3):
#   1) LLM_MODEL_PRIMARY  — GPT-6 Astra Challenge 主模型;空时回退到 OPENAI_MODEL
#   2) OPENAI_MODEL       — 旧版兼容字段,留作 .env 平滑迁移
#   3) MiniMax-M3         — 兜底默认;Astra 还没发布/额度耗尽时仍能跑通 demo
# 生产部署 Product Hunt 前必须把 LLM_MODEL_PRIMARY 改成 gpt-6-astra
LLM_MODEL_PRIMARY = (
    os.getenv("LLM_MODEL_PRIMARY")
    or os.getenv("OPENAI_MODEL")
    or "MiniMax-M3"
)
# Fallback 模型,Primary 抛任何异常都自动切这里(§8.2)
# 选 deepseek-chat:便宜、响应快、医疗问答可接受
LLM_FALLBACK = os.getenv("LLM_FALLBACK", "deepseek-chat")

YOLO_API_KEY = os.getenv("YOLO_API_KEY", "")
YOLO_URLS: Dict[str, Optional[str]] = {
    "position": os.getenv("YOLO_BASE_URL_POSITION"),
    "range": os.getenv("YOLO_BASE_URL_RANGE"),
    "kind": os.getenv("YOLO_BASE_URL_KIND"),
}
YOLO_TIMEOUT = int(os.getenv("YOLO_TIMEOUT", "30"))
PORT = int(os.getenv("PORT", "8080"))


def validate_env() -> None:
    """Validate required environment variables at startup (§9.3)."""
    required = {
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "OPENAI_BASE_URL": OPENAI_BASE_URL,
        "YOLO_API_KEY": YOLO_API_KEY,
        "YOLO_BASE_URL_POSITION": YOLO_URLS["position"],
        "YOLO_BASE_URL_RANGE": YOLO_URLS["range"],
        "YOLO_BASE_URL_KIND": YOLO_URLS["kind"],
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        err_msg = f"Missing required env vars: {missing}"
        logger.error(err_msg)
        raise RuntimeError(err_msg)
    logger.info(
        "Environment variables validated successfully. Primary LLM: %s, Fallback: %s",
        LLM_MODEL_PRIMARY,
        LLM_FALLBACK,
    )


# Run validation immediately
validate_env()

# Initialize OpenAI Client
openai_client = OpenAI(
    api_key=OPENAI_API_KEY,
    base_url=OPENAI_BASE_URL,
)

# ==============================================================================
# 2. Image Preprocessing Pipeline (§11.5 - Option C)
# ==============================================================================
_ALLOWED_MAGIC: Tuple[bytes, ...] = (
    b"\x89PNG\r\n\x1a\n",   # PNG
    b"\xff\xd8\xff",         # JPEG
    b"GIF87a", b"GIF89a",    # GIF
    b"RIFF",                 # WebP
)
MAX_IMAGE_BYTES = 20 * 1024 * 1024  # 20MB limit aligned with OpenAI


def validate_image(raw: bytes) -> None:
    """Validate image raw bytes size and magic headers (§11.5.1)."""
    if len(raw) > MAX_IMAGE_BYTES:
        raise ValueError(f"Image too large: {len(raw) / (1024 * 1024):.1f}MB exceeds 20MB limit")
    if len(raw) < 16:
        raise ValueError("Image data too short (< 16 bytes)")
    if not any(raw.startswith(m) for m in _ALLOWED_MAGIC):
        raise ValueError("Unsupported format (only PNG/JPG/GIF/WebP accepted)")


def preprocess_image(
    raw: bytes,
    max_size: int = 1024,
    quality: int = 85,
) -> Tuple[str, str, bytes]:
    """Compress image, strip EXIF metadata, auto-orient, and convert to JPEG.

    Returns:
        (base64_str, mime_type, jpeg_bytes)

    Notes (设计 doc §11.5.2 - 选 C 的原因):
        - EXIF 自动转置:医生手机拍的 X 光片常带 EXIF Orientation=6/8(横竖颠倒),
          不处理会导致 YOLO / Vision 把左右搞反,误诊风险高。ImageOps.exif_transpose()
          会读取 EXIF 然后旋转像素,旋转后 EXIF 标记一并清除。
        - max_size=1024:OpenAI Vision 在长边 ≤ 1024 时按 "low detail" 计费(~85 tokens),
          再大就被切 512px tile,token 暴增且延迟上升。骨折 X 光的关键信息(骨折线、骨块)
          在 1024px 下仍清晰可辨。
        - quality=85 + optimize=True:在医疗影像可接受范围内最大化压缩。
          q>90 体积翻倍但肉眼难分辨差异;q<80 文字标注/细小骨折线开始模糊。
        - 转 RGB:JPEG 不支持 RGBA / P / LA(透明通道会被丢),统一转 RGB。
    """
    validate_image(raw)
    try:
        img = Image.open(io.BytesIO(raw))
        # Auto-transpose based on EXIF orientation if present.
        # 仅吞掉 transpose 自身的解析异常;真正的图片损坏会被外层 UnidentifiedImageError 接住。
        try:
            img = ImageOps.exif_transpose(img)
        except Exception:
            pass

        if img.mode in ("RGBA", "P", "LA"):
            img = img.convert("RGB")

        if max(img.size) > max_size:
            # Pillow 12 把 LANCZOS 重命名到 Image.Resampling 命名空间;新旧两个常量都能用,
            # 这里用全限定写法,避免 IDE 在新装环境里提示找不到。
            img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        jpeg_bytes = buf.getvalue()
        import base64
        b64_str = base64.b64encode(jpeg_bytes).decode("ascii")
        return b64_str, "image/jpeg", jpeg_bytes
    except UnidentifiedImageError as e:
        raise ValueError(f"Failed to parse image: {e}")


def build_image_url(image_base64: str, mime: str = "image/jpeg", detail: str = "auto") -> Dict[str, Any]:
    """Construct OpenAI Vision standard image_url content block (§11.2)."""
    return {
        "type": "image_url",
        "image_url": {
            "url": f"data:{mime};base64,{image_base64}",
            "detail": detail,
        },
    }


# ==============================================================================
# 3. Clean Thinking & Reasoning Parser (§6 & §7 - Plan A)
# ==============================================================================
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


# ==============================================================================
# 4. YOLO Cloud Prediction Service (§4)
# ==============================================================================
class YOLOCloudService:
    """Ultralytics Cloud YOLO inference service for position, range, and kind models."""

    def __init__(self) -> None:
        self.api_key = YOLO_API_KEY
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        self.urls = YOLO_URLS
        self.timeout = YOLO_TIMEOUT

    def _call_model(
        self,
        model_type: str,
        image_bytes: bytes,
        conf: float = 0.25,
        iou: float = 0.7,
        imgsz: int = 640,
    ) -> Dict[str, Any]:
        url = self.urls.get(model_type)
        if not url:
            return {
                "success": False,
                "error": f"{model_type} model API URL not configured",
                "code": "URL_NOT_CONFIGURED",
                "processing_time": 0,
            }

        args = {"conf": conf, "iou": iou, "imgsz": imgsz}
        start_time = time.time()
        try:
            files = {"file": ("image.jpg", io.BytesIO(image_bytes), "image/jpeg")}
            resp = requests.post(
                url=url,
                headers=self.headers,
                data=args,
                files=files,
                timeout=self.timeout,
            )
            elapsed = time.time() - start_time
            if resp.status_code != 200:
                logger.error(
                    "YOLO %s failed status=%d body=%s",
                    model_type,
                    resp.status_code,
                    resp.text[:300],
                )
                return {
                    "success": False,
                    "error": f"HTTP {resp.status_code}: {resp.text[:200]}",
                    "code": f"HTTP_{resp.status_code}",
                    "processing_time": elapsed,
                }

            result_json = resp.json()
            return self._parse_result(model_type, result_json, elapsed)

        except requests.exceptions.Timeout:
            logger.error("YOLO %s prediction timed out", model_type)
            return {
                "success": False,
                "error": "Request timed out",
                "code": "TIMEOUT",
                "processing_time": self.timeout,
            }
        except requests.exceptions.RequestException as e:
            logger.error("YOLO %s network exception: %s", model_type, e)
            return {
                "success": False,
                "error": str(e),
                "code": "NETWORK_ERROR",
                "processing_time": time.time() - start_time,
            }
        except Exception as e:
            logger.error("YOLO %s unexpected error: %s", model_type, e)
            return {
                "success": False,
                "error": str(e),
                "code": "INTERNAL_ERROR",
                "processing_time": time.time() - start_time,
            }

    @staticmethod
    def _parse_result(model_type: str, raw_result: Dict[str, Any], elapsed: float) -> Dict[str, Any]:
        try:
            images = raw_result.get("images", [])
            if not images:
                return {"success": True, "data": [], "processing_time": elapsed}

            results = images[0].get("results", [])
            data: List[Dict[str, Any]] = []
            for r in results:
                item: Dict[str, Any] = {
                    "name": r.get("name"),
                    "class": r.get("class"),
                    "confidence": r.get("confidence"),
                }
                if model_type in ("position", "range"):
                    item["box"] = r.get("box")
                    item["segments"] = r.get("segments")
                data.append(item)

            return {"success": True, "data": data, "processing_time": elapsed}
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to parse result: {e}",
                "code": "PARSE_ERROR",
                "processing_time": elapsed,
            }

    def predict_all(
        self,
        image_bytes: bytes,
        conf: float = 0.25,
        iou: float = 0.7,
        imgsz: int = 640,
    ) -> Tuple[Dict[str, Any], int]:
        """Execute 3 models in parallel via ThreadPoolExecutor(max_workers=3) (§4.4)."""
        start_total = time.time()
        with ThreadPoolExecutor(max_workers=3) as executor:
            fut_pos = executor.submit(self._call_model, "position", image_bytes, conf, iou, imgsz)
            fut_range = executor.submit(self._call_model, "range", image_bytes, conf, iou, imgsz)
            fut_kind = executor.submit(self._call_model, "kind", image_bytes, conf, iou, imgsz)

            res_pos = fut_pos.result()
            res_range = fut_range.result()
            res_kind = fut_kind.result()

        total_wall_time = (time.time() - start_total) * 1000

        pos_time_ms = res_pos.get("processing_time", 0) * 1000
        range_time_ms = res_range.get("processing_time", 0) * 1000
        kind_time_ms = res_kind.get("processing_time", 0) * 1000

        # Structured errors array (§4.4)
        errors: List[Dict[str, Any]] = []
        if not res_pos.get("success"):
            errors.append({"model": "position", "message": res_pos.get("error", ""), "code": res_pos.get("code", "ERROR")})
        if not res_range.get("success"):
            errors.append({"model": "range", "message": res_range.get("error", ""), "code": res_range.get("code", "ERROR")})
        if not res_kind.get("success"):
            errors.append({"model": "kind", "message": res_kind.get("error", ""), "code": res_kind.get("code", "ERROR")})

        # Check if all 3 failed
        if len(errors) == 3:
            return {
                "success": False,
                "error": "All 3 YOLO models failed",
                "errors": errors,
                "processing_time": round(total_wall_time, 2),
            }, 502

        # Partial success or full success -> HTTP 200 (§4.4.1)
        response_payload = {
            "success": True,
            "positions": res_pos.get("data", []) if res_pos.get("success") else [],
            "range": res_range.get("data", []) if res_range.get("success") else [],
            "kind": res_kind.get("data", []) if res_kind.get("success") else [],
            "processing_time": round(total_wall_time, 2),
            "position_time": round(pos_time_ms, 2),
            "range_time": round(range_time_ms, 2),
            "kind_time": round(kind_time_ms, 2),
            "errors": errors,
        }
        return response_payload, 200


yolo_service = YOLOCloudService()


# ==============================================================================
# 5. LLM Fallback & Invocation Service (§5 & §8)
# ==============================================================================

# Module-level prompt constants (English-only, OpenAI Vision best-practice).
# Promoted out of build_clinical_messages so they can be:
#   - overridden in tests
#   - swapped for i18n variants (zh-CN, etc.) without touching the function body
#   - reviewed by medical domain experts without reading Python
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


def chat_once(model: str, messages: List[Dict[str, Any]], stream: bool = False) -> Any:
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
        return openai_client.chat.completions.create(**params)
    except Exception as e:
        # If model rejected extra_body or reasoning_effort, degrade gracefully.
        # 这里必须用宽 except — OpenAI SDK 的异常类型在版本间不稳定(APIError /
        # BadRequestError / TypeError 都见过),窄 except 会漏;后续由上层
        # explain_with_fallback 再做模型级兜底。
        logger.warning("Primary param invoke failed on model %s: %s. Retrying without extra params.", model, e)
        params.pop("reasoning_effort", None)
        params.pop("extra_body", None)
        return openai_client.chat.completions.create(**params)


def explain_with_fallback(
    image_base64: str,
    mime: str,
    yolo_result: Dict[str, Any],
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

    # 1. Try Primary
    try:
        logger.info("Calling primary LLM: %s", LLM_MODEL_PRIMARY)
        resp = chat_once(LLM_MODEL_PRIMARY, messages, stream=False)
        content = extract_final_text(resp.choices[0])
        if content:
            return content, LLM_MODEL_PRIMARY
    except Exception as e:
        logger.error("Primary LLM %s failed: %s", LLM_MODEL_PRIMARY, e)

    # 2. Try Fallback
    try:
        logger.warning("Attempting fallback LLM: %s", LLM_FALLBACK)
        resp = chat_once(LLM_FALLBACK, messages, stream=False)
        content = extract_final_text(resp.choices[0])
        if content:
            return content, LLM_FALLBACK
    except Exception as e:
        logger.error("Fallback LLM %s failed: %s", LLM_FALLBACK, e)

    # 上层 /api/explain 会把 RuntimeError 翻译成 HTTP 502 Bad Gateway:
    #   502 而非 500,因为 LLM 是"上游网关"角色,符合 RFC 7231 对 Bad Gateway 的语义。
    #   前端拿到 502 时显示"AI 服务暂不可用,请稍后重试",而非"系统错误"。
    raise RuntimeError("All LLM backends failed to generate explanation")


# ==============================================================================
# 6. Flask Application & Endpoints (§3, §4, §5)
# ==============================================================================
app = Flask(__name__)
CORS(app)


@app.route("/api/health", methods=["GET"])
def health_check() -> Any:
    """Health check endpoint (§3)."""
    # 用 timezone.utc 而非 datetime.UTC(Python 3.11+ 才有),
    # 兼容 conda 环境里当前安装的 Python 3.12 默认 datetime 子类路径。
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "models": {
            "primary": LLM_MODEL_PRIMARY,
            "fallback": LLM_FALLBACK,
            "yolo_urls": {k: bool(v) for k, v in YOLO_URLS.items()},
        },
    }), 200


@app.route("/api/detect", methods=["POST"])
def detect_endpoint() -> Any:
    """Run YOLO 3-model parallel detection (§4).

    Input: multipart/form-data with 'file', and optional 'conf', 'iou', 'imgsz'.
    """
    if "file" not in request.files:
        return jsonify({"success": False, "error": "Missing 'file' in multipart request"}), 400

    file_storage = request.files["file"]
    raw_bytes = file_storage.read()

    # Preprocess and validate image (§11.5)
    try:
        _, _, jpeg_bytes = preprocess_image(raw_bytes)
    except ValueError as e:
        return jsonify({"success": False, "error": str(e), "code": "INVALID_IMAGE"}), 400

    # Parse query/form parameters with defaults
    try:
        conf = float(request.form.get("conf", 0.25))
        iou = float(request.form.get("iou", 0.7))
        imgsz = int(request.form.get("imgsz", 640))
    except ValueError:
        return jsonify({"success": False, "error": "Invalid hyperparameter format"}), 400

    payload, status_code = yolo_service.predict_all(jpeg_bytes, conf=conf, iou=iou, imgsz=imgsz)
    return jsonify(payload), status_code


@app.route("/api/explain", methods=["POST"])
def explain_endpoint() -> Any:
    """Generate clinical recommendations from X-ray image and YOLO results (§5).

    Input: JSON { image_base64: str, yolo_result: dict, stream?: bool }
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be JSON", "code": "INVALID_JSON"}), 400

    image_b64 = data.get("image_base64")
    if not image_b64:
        return jsonify({"error": "Missing 'image_base64'", "code": "MISSING_PARAM"}), 400

    # Clean data URL prefix if provided
    if "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]

    # Decode base64 to validate and preprocess (§11.5.1)
    import base64
    import binascii
    try:
        raw_bytes = base64.b64decode(image_b64, validate=True)
    except (binascii.Error, ValueError):
        return jsonify({"error": "Invalid base64 encoding", "code": "INVALID_BASE64"}), 400

    try:
        clean_b64, mime, _ = preprocess_image(raw_bytes)
    except ValueError as e:
        return jsonify({"error": str(e), "code": "INVALID_IMAGE"}), 400

    yolo_result = data.get("yolo_result", {})
    stream_requested = bool(data.get("stream", False))

    if not stream_requested:
        # Non-streaming mode
        try:
            explanation, model_used = explain_with_fallback(clean_b64, mime, yolo_result)
            return jsonify({
                "explanation": explanation,
                "model": model_used,
            }), 200
        except Exception as e:
            logger.error("Explain endpoint error: %s", e)
            return jsonify({
                "error": "All LLM backends failed",
                "detail": str(e),
                "code": "LLM_FAILURE",
            }), 502

    # Streaming mode (§7.2 SSE)
    def generate_sse():
        stripper = StreamThinkingStripper()
        messages = build_clinical_messages(clean_b64, mime, yolo_result)
        selected_model = LLM_MODEL_PRIMARY

        try:
            resp_stream = chat_once(selected_model, messages, stream=True)
            for chunk in resp_stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                text_delta = getattr(delta, "content", "") or ""
                cleaned_chunk = stripper.feed(text_delta)
                if cleaned_chunk:
                    yield f"data: {json.dumps({'text': cleaned_chunk, 'model': selected_model})}\n\n"

            tail = stripper.flush()
            if tail:
                yield f"data: {json.dumps({'text': tail, 'model': selected_model})}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as stream_err:
            logger.error("Stream generation failed: %s", stream_err)
            err_json = json.dumps({"error": str(stream_err), "code": "STREAM_ERROR"})
            yield f"data: {err_json}\n\n"
            yield "data: [DONE]\n\n"

    return Response(
        stream_with_context(generate_sse()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ==============================================================================
# 7. Main Entry Point (§9)
# ==============================================================================
if __name__ == "__main__":
    logger.info("Starting Astra-FractureAI backend on port %d...", PORT)
    app.run(host="0.0.0.0", port=PORT, debug=False)

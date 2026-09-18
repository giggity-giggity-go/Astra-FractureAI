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
from flask import Flask, Response, jsonify, request, send_from_directory, stream_with_context
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


def configured_models() -> List[str]:
    """Return configured LLM model names in preference order without duplicates."""
    return list(dict.fromkeys(model for model in (LLM_MODEL_PRIMARY, LLM_FALLBACK) if model))


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
from image_service import (
    MAX_IMAGE_BYTES,
    build_image_url,
    preprocess_image,
    validate_image,
)


# ==============================================================================
# 3. Clean Thinking & Reasoning Parser (§6 & §7 - Plan A)
# ==============================================================================
from thinking import StreamThinkingStripper, clean_thinking, extract_final_text


# ==============================================================================
# 4. YOLO Cloud Prediction Service (§4)
# ==============================================================================
from yolo_service import YOLOCloudService

yolo_service = YOLOCloudService(YOLO_API_KEY, YOLO_URLS, YOLO_TIMEOUT, logger)


# ==============================================================================
# 5. LLM Fallback & Invocation Service (§5 & §8)
# ==============================================================================

# Module-level prompt constants (English-only, OpenAI Vision best-practice).
# Promoted out of build_clinical_messages so they can be:
#   - overridden in tests
#   - swapped for i18n variants (zh-CN, etc.) without touching the function body
#   - reviewed by medical domain experts without reading Python
from llm_service import (
    SYSTEM_PROMPT,
    USER_TEXT_TEMPLATE,
    build_clinical_messages,
)
import llm_service as _llm_service


def chat_once(model: str, messages: List[Dict[str, Any]], stream: bool = False) -> Any:
    return _llm_service.chat_once(openai_client, logger, model, messages, stream=stream)


def model_candidates(requested_model: Optional[str] = None) -> List[str]:
    return _llm_service.model_candidates(LLM_MODEL_PRIMARY, LLM_FALLBACK, requested_model)


def explain_with_fallback(
    image_base64: str,
    mime: str,
    yolo_result: Dict[str, Any],
    requested_model: Optional[str] = None,
) -> Tuple[str, str]:
    return _llm_service.explain_with_fallback(
        image_base64, mime, yolo_result, requested_model,
        primary_model=LLM_MODEL_PRIMARY,
        fallback_model=LLM_FALLBACK,
        client=openai_client,
        logger=logger,
        chat_fn=chat_once,
        extract_fn=extract_final_text,
    )


# ==============================================================================
# 6. Flask Application & Endpoints (§3, §4, §5)
# ==============================================================================
app = Flask(__name__)
CORS(app)
FRONTEND_DIR = os.path.join(_BASE_DIR, "frontend")


@app.route("/", methods=["GET"])
def frontend_index() -> Any:
    """Serve the no-build frontend from the same origin as the API."""
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/frontend/<path:filename>", methods=["GET"])
def frontend_asset(filename: str) -> Any:
    """Serve frontend JavaScript, styles, and other local assets."""
    return send_from_directory(FRONTEND_DIR, filename)


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
            "available": configured_models(),
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

    # Detection coordinates refer to the preprocessed image sent upstream, which can
    # be smaller than the browser's source image. Return that coordinate space so
    # the Canvas client can project boxes and masks without guessing.
    with Image.open(io.BytesIO(jpeg_bytes)) as prepared_image:
        detection_width, detection_height = prepared_image.size

    # Parse query/form parameters with defaults
    try:
        conf = float(request.form.get("conf", 0.25))
        iou = float(request.form.get("iou", 0.7))
        imgsz = int(request.form.get("imgsz", 640))
    except ValueError:
        return jsonify({"success": False, "error": "Invalid hyperparameter format"}), 400

    if not 0.01 <= conf <= 1.0:
        return jsonify({"success": False, "error": "conf must be between 0.01 and 1.00"}), 400
    if not 0.0 <= iou <= 0.95:
        return jsonify({"success": False, "error": "iou must be between 0.00 and 0.95"}), 400
    if imgsz not in {320, 640, 1280}:
        return jsonify({"success": False, "error": "imgsz must be one of 320, 640, or 1280"}), 400

    payload, status_code = yolo_service.predict_all(jpeg_bytes, conf=conf, iou=iou, imgsz=imgsz)
    payload["image_size"] = {"width": detection_width, "height": detection_height}
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
    requested_model = data.get("llm_model") or LLM_MODEL_PRIMARY
    if not isinstance(requested_model, str) or requested_model not in configured_models():
        return jsonify({
            "error": "Requested LLM model is not configured",
            "code": "INVALID_MODEL",
            "available_models": configured_models(),
        }), 400

    if not stream_requested:
        # Non-streaming mode
        try:
            explanation, model_used = explain_with_fallback(
                clean_b64, mime, yolo_result, requested_model=requested_model
            )
            return jsonify({
                "explanation": explanation,
                "model": model_used,
            }), 200
        except Exception as e:
            logger.error("Explain endpoint error: %s", e)
            return jsonify({
                "error": "All LLM backends failed",
                "code": "LLM_FAILURE",
            }), 502

    # Streaming mode (§7.2 SSE)
    def generate_sse():
        messages = build_clinical_messages(clean_b64, mime, yolo_result)
        emitted_text = False

        for selected_model in model_candidates(requested_model):
            stripper = StreamThinkingStripper()
            try:
                resp_stream = chat_once(selected_model, messages, stream=True)
                for chunk in resp_stream:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta
                    text_delta = getattr(delta, "content", "") or ""
                    cleaned_chunk = stripper.feed(text_delta)
                    if cleaned_chunk:
                        emitted_text = True
                        payload = json.dumps(
                            {"text": cleaned_chunk, "model": selected_model},
                            ensure_ascii=False,
                        )
                        yield f"data: {payload}\n\n"

                tail = stripper.flush()
                if tail:
                    emitted_text = True
                    payload = json.dumps(
                        {"text": tail, "model": selected_model},
                        ensure_ascii=False,
                    )
                    yield f"data: {payload}\n\n"
                yield "data: [DONE]\n\n"
                return

            except Exception as stream_err:
                logger.error("Stream generation failed on model %s: %s", selected_model, stream_err)
                if emitted_text:
                    break
                logger.warning("Trying next configured model before any text was emitted")

        err_json = json.dumps({
            "error": "The configured LLM service could not complete the stream",
            "code": "STREAM_ERROR",
        })
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

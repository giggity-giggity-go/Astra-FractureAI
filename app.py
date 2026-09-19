"""Astra-FractureAI Flask API and same-origin frontend delivery."""

from datetime import datetime, timezone
import io
import json
import logging
import os
import re
import threading
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from flask import Flask, Response, g, has_request_context, jsonify, request, send_from_directory, stream_with_context
from flask_cors import CORS
from openai import OpenAI
from PIL import Image
from werkzeug.exceptions import HTTPException, RequestEntityTooLarge

from detection_task_store import DetectionTaskStore
from image_service import preprocess_image
from security_config import load_security_settings
from thinking import StreamThinkingStripper, clean_thinking, extract_final_text
from yolo_service import YOLOCloudService
import llm_service as _llm_service
from llm_service import build_clinical_messages

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_ENV_PATH = os.path.join(_BASE_DIR, ".env")
load_dotenv(_ENV_PATH if os.path.exists(_ENV_PATH) else None, override=True)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("AstraFractureAI")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = getattr(g, "request_id", "-") if has_request_context() else "-"
        return True


logger.addFilter(_RequestIdFilter())
SETTINGS = load_security_settings()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL_PRIMARY = os.getenv("LLM_MODEL_PRIMARY") or os.getenv("OPENAI_MODEL") or "gpt-6-astra"
LLM_FALLBACK = os.getenv("LLM_FALLBACK", "gpt-5.6-sol")
YOLO_API_KEY = os.getenv("YOLO_API_KEY", "")
YOLO_URLS: Dict[str, Optional[str]] = {
    "position": os.getenv("YOLO_BASE_URL_POSITION"),
    "range": os.getenv("YOLO_BASE_URL_RANGE"),
    "kind": os.getenv("YOLO_BASE_URL_KIND"),
}
YOLO_TIMEOUT = int(os.getenv("YOLO_TIMEOUT", "12"))
PORT = int(os.getenv("PORT", "8080"))
YOLO_ALLOWED_HOSTS = tuple(host.strip() for host in os.getenv("YOLO_ALLOWED_HOSTS", "").split(",") if host.strip())
_PLACEHOLDER_VALUES = {"replace-me", "your-api-key", "changeme", "your.ultralytics.cloud"}


def validate_env() -> None:
    required = {
        "OPENAI_API_KEY": OPENAI_API_KEY,
        "OPENAI_BASE_URL": OPENAI_BASE_URL,
        "YOLO_API_KEY": YOLO_API_KEY,
        "YOLO_BASE_URL_POSITION": YOLO_URLS["position"],
        "YOLO_BASE_URL_RANGE": YOLO_URLS["range"],
        "YOLO_BASE_URL_KIND": YOLO_URLS["kind"],
    }
    invalid = [name for name, value in required.items() if not value or str(value).strip().lower() in _PLACEHOLDER_VALUES]
    if invalid:
        raise RuntimeError(f"Missing or placeholder environment variables: {', '.join(invalid)}")
    if any(host.lower() in _PLACEHOLDER_VALUES for host in YOLO_ALLOWED_HOSTS):
        raise RuntimeError("YOLO_ALLOWED_HOSTS contains a placeholder value")
    if not 1 <= YOLO_TIMEOUT <= 60:
        raise RuntimeError("Invalid YOLO_TIMEOUT configuration")


validate_env()
openai_client = OpenAI(api_key=OPENAI_API_KEY, base_url=OPENAI_BASE_URL, timeout=SETTINGS.llm_timeout_seconds, max_retries=0)
yolo_service = YOLOCloudService(YOLO_API_KEY, YOLO_URLS, YOLO_TIMEOUT, logger, max_concurrency=SETTINGS.yolo_max_concurrency, allowed_hosts=YOLO_ALLOWED_HOSTS)
task_store = DetectionTaskStore(SETTINGS.task_ttl_seconds, SETTINGS.task_cache_max_items, SETTINGS.task_cache_max_bytes)
llm_admission = threading.BoundedSemaphore(SETTINGS.llm_max_concurrency)


def configured_models() -> List[str]:
    return list(dict.fromkeys(model for model in (LLM_MODEL_PRIMARY, LLM_FALLBACK) if model))


def chat_once(model: str, messages: List[Dict[str, Any]], stream: bool = False) -> Any:
    return _llm_service.chat_once(openai_client, logger, model, messages, stream=stream)


def model_candidates(requested_model: Optional[str] = None) -> List[str]:
    return _llm_service.model_candidates(LLM_MODEL_PRIMARY, LLM_FALLBACK, requested_model)


def explain_with_fallback(image_base64: str, mime: str, yolo_result: Dict[str, Any], requested_model: Optional[str] = None) -> Tuple[str, str]:
    return _llm_service.explain_with_fallback(image_base64, mime, yolo_result, requested_model, primary_model=LLM_MODEL_PRIMARY, fallback_model=LLM_FALLBACK, client=openai_client, logger=logger, chat_fn=chat_once, extract_fn=extract_final_text)


def _close_stream(stream: Any) -> None:
    closer = getattr(stream, "close", None)
    if callable(closer):
        closer()


app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = SETTINGS.max_request_bytes
FRONTEND_DIR = os.path.join(_BASE_DIR, "frontend")
if SETTINGS.allowed_cors_origins:
    CORS(app, resources={r"/api/*": {"origins": list(SETTINGS.allowed_cors_origins)}}, supports_credentials=False)


def api_error(code: str, message: str, status: int) -> tuple[Any, int]:
    return jsonify({"success": False, "code": code, "error": message, "request_id": g.get("request_id", "-")}), status


@app.before_request
def assign_request_id() -> None:
    candidate = request.headers.get("X-Request-ID", "")
    g.request_id = candidate if re.fullmatch(r"[A-Za-z0-9_-]{8,64}", candidate) else uuid.uuid4().hex
    if request.content_length is not None and request.content_length > SETTINGS.max_request_bytes:
        raise RequestEntityTooLarge()


@app.after_request
def add_security_headers(response: Response) -> Response:
    response.headers["X-Request-ID"] = g.get("request_id", "-")
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.errorhandler(RequestEntityTooLarge)
def request_too_large(_: RequestEntityTooLarge) -> tuple[Any, int]:
    return api_error("REQUEST_TOO_LARGE", "The request exceeds the allowed size.", 413)


@app.errorhandler(HTTPException)
def http_error(error: HTTPException) -> Any:
    if request.path.startswith("/api/"):
        return api_error("HTTP_ERROR", "The request could not be completed.", error.code or 500)
    return error


@app.errorhandler(Exception)
def unexpected_error(error: Exception) -> tuple[Any, int]:
    logger.exception("Unhandled API error: %s", type(error).__name__)
    return api_error("INTERNAL_ERROR", "The request could not be completed.", 500)


@app.route("/", methods=["GET"])
def frontend_index() -> Any:
    return send_from_directory(FRONTEND_DIR, "index.html")


@app.route("/frontend/<path:filename>", methods=["GET"])
def frontend_asset(filename: str) -> Any:
    return send_from_directory(FRONTEND_DIR, filename)


@app.route("/api/health", methods=["GET"])
def health_check() -> Any:
    # Informational only: the frontend model dropdown is pinned to a fixed list
    # (gpt-6-astra / gpt-5.6-sol / gpt-5.6-luna / gpt-5.6-terra) and never reads
    # this payload. Routing always follows LLM_MODEL_PRIMARY / LLM_FALLBACK
    # from .env. YOLO retry/timeout policy lives in yolo_service._call_model.
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "models": {
            "primary": LLM_MODEL_PRIMARY,
            "fallback": LLM_FALLBACK,
            "available": configured_models(),
            "yolo_configured": {task: bool(url) for task, url in YOLO_URLS.items()},
        },
    }), 200


def _read_upload() -> bytes:
    if "file" not in request.files:
        raise ValueError("MISSING_FILE")
    stream = request.files["file"].stream
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = stream.read(65536)
        if not chunk:
            break
        size += len(chunk)
        if size > SETTINGS.max_image_bytes:
            raise ValueError("IMAGE_TOO_LARGE")
        chunks.append(chunk)
    return b"".join(chunks)


def _hyperparameters() -> tuple[float, float, int]:
    try:
        conf = float(request.form.get("conf", 0.25))
        iou = float(request.form.get("iou", 0.7))
        imgsz = int(request.form.get("imgsz", 640))
    except ValueError as exc:
        raise ValueError("INVALID_PARAMETERS") from exc
    if not 0.01 <= conf <= 1.0 or not 0.0 <= iou <= 0.95 or imgsz not in {320, 640, 1280}:
        raise ValueError("INVALID_PARAMETERS")
    return conf, iou, imgsz


@app.route("/api/detect", methods=["POST"])
def detect_endpoint() -> Any:
    try:
        raw_bytes = _read_upload()
        _, _, jpeg_bytes = preprocess_image(raw_bytes)
        conf, iou, imgsz = _hyperparameters()
    except ValueError as error:
        errors = {
            "MISSING_FILE": ("MISSING_FILE", "An image file is required."),
            "IMAGE_TOO_LARGE": ("IMAGE_TOO_LARGE", "The image exceeds the allowed size."),
            "INVALID_PARAMETERS": ("INVALID_PARAMETERS", "Detection parameters are invalid."),
        }
        code, message = errors.get(str(error), ("INVALID_IMAGE", "The uploaded image could not be processed."))
        return api_error(code, message, 400)
    with Image.open(io.BytesIO(jpeg_bytes)) as prepared_image:
        image_size = {"width": prepared_image.width, "height": prepared_image.height}
    payload, status_code = yolo_service.predict_all(jpeg_bytes, conf=conf, iou=iou, imgsz=imgsz)
    if status_code != 200:
        safe_errors = [
            {"model": error.get("model", "unknown"), "message": "Model service is unavailable", "code": error.get("code", "UPSTREAM_ERROR")}
            for error in payload.get("errors", []) if isinstance(error, dict)
        ]
        return jsonify({
            "success": False,
            "error": "Detection services are unavailable.",
            "errors": safe_errors,
            "code": payload.get("code", "UPSTREAM_UNAVAILABLE"),
            "request_id": g.request_id,
        }), status_code
    payload["image_size"] = image_size
    try:
        image_base64, mime, _ = preprocess_image(jpeg_bytes)
        task_id, expires_at = task_store.create(image_base64, mime, payload, image_size)
    except ValueError:
        return api_error("CAPACITY_EXCEEDED", "Detection results cannot be retained right now.", 429)
    payload["detection_id"] = task_id
    payload["detection_expires_at"] = expires_at.isoformat().replace("+00:00", "Z")
    payload["request_id"] = g.request_id
    return jsonify(payload), 200


@app.route("/api/explain", methods=["POST"])
def explain_endpoint() -> Any:
    if request.content_length is not None and request.content_length > SETTINGS.max_json_bytes:
        return api_error("REQUEST_TOO_LARGE", "The request exceeds the allowed size.", 413)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return api_error("INVALID_JSON", "Request body must be a JSON object.", 400)
    task_id = data.get("detection_id")
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,128}", task_id):
        return api_error("MISSING_DETECTION_ID", "A valid detection reference is required.", 400)
    requested_model = data.get("llm_model") or LLM_MODEL_PRIMARY
    if not isinstance(requested_model, str) or requested_model not in configured_models():
        return api_error("INVALID_MODEL", "Requested model is unavailable.", 400)
    if not llm_admission.acquire(blocking=False):
        return api_error("CAPACITY_EXCEEDED", "AI capacity is temporarily unavailable.", 429)
    task, task_error = task_store.consume(task_id)
    if task is None:
        llm_admission.release()
        return api_error(task_error, "The detection reference is unavailable or has expired.", 410 if task_error != "TASK_NOT_FOUND" else 404)
    stream_requested = data.get("stream", False) is True
    if not stream_requested:
        try:
            explanation, model_used = explain_with_fallback(task.image_base64, task.mime, task.yolo_result, requested_model)
            return jsonify({"explanation": explanation, "model": model_used, "request_id": g.request_id}), 200
        except Exception:
            logger.warning("Non-streaming LLM request failed")
            return api_error("LLM_FAILURE", "The AI service could not complete the request.", 502)
        finally:
            llm_admission.release()

    def generate_sse() -> Any:
        messages = build_clinical_messages(task.image_base64, task.mime, task.yolo_result)
        emitted_text = False
        completed = False
        terminal_error: Optional[Dict[str, str]] = None
        output_bytes = 0
        event_count = 0
        deadline = time.monotonic() + SETTINGS.sse_max_duration_seconds
        try:
            for selected_model in model_candidates(requested_model):
                stream = None
                stripper = StreamThinkingStripper()
                try:
                    stream = chat_once(selected_model, messages, stream=True)
                    for chunk in stream:
                        if time.monotonic() >= deadline:
                            terminal_error = {"error": "The AI stream exceeded its allowed duration.", "code": "STREAM_TIMEOUT", "request_id": g.request_id}
                            break
                        if not getattr(chunk, "choices", None):
                            continue
                        text_delta = getattr(chunk.choices[0].delta, "content", "") or ""
                        cleaned = stripper.feed(text_delta)
                        if cleaned:
                            encoded = cleaned.encode("utf-8")
                            if output_bytes + len(encoded) > SETTINGS.sse_max_output_bytes or event_count >= SETTINGS.sse_max_events:
                                terminal_error = {"error": "The AI stream exceeded its allowed output limit.", "code": "STREAM_LIMIT", "request_id": g.request_id}
                                break
                            emitted_text = True
                            output_bytes += len(encoded)
                            event_count += 1
                            yield f"data: {json.dumps({'text': cleaned, 'model': selected_model}, ensure_ascii=False)}\n\n"
                    if terminal_error is not None:
                        break
                    tail = stripper.flush()
                    if tail:
                        encoded = tail.encode("utf-8")
                        if output_bytes + len(encoded) > SETTINGS.sse_max_output_bytes or event_count >= SETTINGS.sse_max_events:
                            terminal_error = {"error": "The AI stream exceeded its allowed output limit.", "code": "STREAM_LIMIT", "request_id": g.request_id}
                            break
                        emitted_text = True
                        output_bytes += len(encoded)
                        event_count += 1
                        yield f"data: {json.dumps({'text': tail, 'model': selected_model}, ensure_ascii=False)}\n\n"
                    completed = True
                    break
                except GeneratorExit:
                    raise
                except Exception:
                    logger.warning("Streaming LLM request failed for configured model")
                    if emitted_text:
                        terminal_error = {"error": "The AI service could not complete the stream.", "code": "STREAM_ERROR", "request_id": g.request_id}
                        break
                finally:
                    if stream is not None:
                        _close_stream(stream)
            if not completed:
                terminal_error = terminal_error or {"error": "The AI service could not complete the stream.", "code": "STREAM_ERROR", "request_id": g.request_id}
                yield f"data: {json.dumps(terminal_error)}\n\n"
            yield "data: [DONE]\n\n"
        finally:
            llm_admission.release()

    return Response(stream_with_context(generate_sse()), mimetype="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


if __name__ == "__main__":
    debug_mode = os.getenv("FLASK_DEBUG", "").lower() in ("1", "true", "yes", "on")
    logger.warning(
        "Starting local development server on port %d (debug=%s, use_reloader=%s)",
        PORT, debug_mode, debug_mode,
    )
    app.run(host="127.0.0.1", port=PORT, debug=debug_mode, use_reloader=debug_mode)

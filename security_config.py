"""Runtime limits and safe environment parsing."""

from dataclasses import dataclass
import os


def _positive_int(name: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    value = os.getenv(name, str(default))
    try:
        parsed = int(value)
    except ValueError as exc:
        raise RuntimeError(f"Invalid {name} configuration") from exc
    if parsed < minimum or (maximum is not None and parsed > maximum):
        raise RuntimeError(f"Invalid {name} configuration")
    return parsed


@dataclass(frozen=True)
class SecuritySettings:
    max_request_bytes: int
    max_image_bytes: int
    max_json_bytes: int
    max_image_pixels: int
    max_image_width: int
    max_image_height: int
    max_image_ratio: int
    task_ttl_seconds: int
    task_cache_max_items: int
    task_cache_max_bytes: int
    yolo_max_concurrency: int
    llm_max_concurrency: int
    llm_timeout_seconds: int
    sse_max_duration_seconds: int
    sse_max_output_bytes: int
    sse_max_events: int
    allowed_cors_origins: tuple[str, ...]


def load_security_settings() -> SecuritySettings:
    max_image_bytes = _positive_int("MAX_IMAGE_BYTES", 20 * 1024 * 1024, maximum=50 * 1024 * 1024)
    max_request_bytes = _positive_int("MAX_REQUEST_BYTES", max_image_bytes + 1024 * 1024, maximum=52 * 1024 * 1024)
    max_json_bytes = _positive_int("MAX_JSON_BYTES", max_image_bytes * 2, maximum=50 * 1024 * 1024)
    if max_request_bytes < max_image_bytes + 64 * 1024:
        raise RuntimeError("MAX_REQUEST_BYTES must allow multipart overhead")
    origins = tuple(
        origin.strip() for origin in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if origin.strip()
    )
    if any(origin == "*" or not origin.startswith(("https://", "http://")) for origin in origins):
        raise RuntimeError("Invalid CORS_ALLOWED_ORIGINS configuration")
    return SecuritySettings(
        max_request_bytes=max_request_bytes,
        max_image_bytes=max_image_bytes,
        max_json_bytes=max_json_bytes,
        max_image_pixels=_positive_int("MAX_IMAGE_PIXELS", 20_000_000, maximum=100_000_000),
        max_image_width=_positive_int("MAX_IMAGE_WIDTH", 8192, maximum=16384),
        max_image_height=_positive_int("MAX_IMAGE_HEIGHT", 8192, maximum=16384),
        max_image_ratio=_positive_int("MAX_IMAGE_RATIO", 12, maximum=100),
        task_ttl_seconds=_positive_int("DETECTION_TASK_TTL_SECONDS", 300, maximum=3600),
        task_cache_max_items=_positive_int("DETECTION_TASK_CACHE_MAX_ITEMS", 32, maximum=256),
        task_cache_max_bytes=_positive_int("DETECTION_TASK_CACHE_MAX_BYTES", 256 * 1024 * 1024, maximum=512 * 1024 * 1024),
        yolo_max_concurrency=_positive_int("YOLO_MAX_CONCURRENCY", 3, maximum=16),
        llm_max_concurrency=_positive_int("LLM_MAX_CONCURRENCY", 2, maximum=16),
        llm_timeout_seconds=_positive_int("LLM_TIMEOUT_SECONDS", 45, maximum=120),
        sse_max_duration_seconds=_positive_int("SSE_MAX_DURATION_SECONDS", 60, maximum=180),
        sse_max_output_bytes=_positive_int("SSE_MAX_OUTPUT_BYTES", 128 * 1024, maximum=1024 * 1024),
        sse_max_events=_positive_int("SSE_MAX_EVENTS", 512, maximum=4096),
        allowed_cors_origins=origins,
    )

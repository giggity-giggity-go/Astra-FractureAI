"""Image validation and preprocessing helpers."""

import base64
import io
from typing import Any, Dict, Tuple

from PIL import Image, ImageOps, UnidentifiedImageError

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

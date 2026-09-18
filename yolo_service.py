"""Ultralytics Cloud YOLO adapter and parallel prediction orchestration."""

from concurrent.futures import ThreadPoolExecutor
import io
import time
from typing import Any, Dict, List, Optional, Tuple

import requests


class YOLOCloudService:
    """Ultralytics Cloud YOLO inference service for position, range, and kind models."""

    def __init__(self, api_key: str, urls: Dict[str, Optional[str]], timeout: int, logger: Any) -> None:
        self.api_key = api_key
        self.headers = {"Authorization": f"Bearer {self.api_key}"}
        self.urls = urls
        self.timeout = timeout
        self.logger = logger

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
                self.logger.error(
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
            self.logger.error("YOLO %s prediction timed out", model_type)
            return {
                "success": False,
                "error": "Request timed out",
                "code": "TIMEOUT",
                "processing_time": self.timeout,
            }
        except requests.exceptions.RequestException as e:
            self.logger.error("YOLO %s network exception: %s", model_type, e)
            return {
                "success": False,
                "error": str(e),
                "code": "NETWORK_ERROR",
                "processing_time": time.time() - start_time,
            }
        except Exception as e:
            self.logger.error("YOLO %s unexpected error: %s", model_type, e)
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

"""Lazy ONNX model registry with stub mode for testing."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

_MODEL_DIR = Path.home() / ".hades" / "models"

# Download URLs — update when mirror locations change
_URLS: dict[str, str] = {
    "mobilenet_ssd_coco_int8.onnx": (
        "https://github.com/PINTO0309/PINTO_model_zoo/releases/download/"
        "137_MobileNetV2-SSDLite/mobilenetv2_ssdlite_coco_int8.onnx"
    ),
    "yolov8n_fp16.onnx": (
        "https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8n.onnx"
    ),
    "yolov8m_fp32.onnx": (
        "https://github.com/ultralytics/assets/releases/download/v8.2.0/yolov8m.onnx"
    ),
}


class _ZeroStub:
    """Returned by all getters in stub mode — callable, returns None."""

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        return None


class ModelRegistry:
    """Manages pretrained model loading with lazy imports and optional stub mode.

    In stub mode all getters return a _ZeroStub so unit tests never require
    heavy dependencies (onnxruntime, ahrs, filterpy, scikit-image).
    """

    def __init__(self, stub: bool = False) -> None:
        self._stub = stub
        self._cache: dict[str, Any] = {}

    def get_mobilenet_ssd(self) -> Any:
        if self._stub:
            return _ZeroStub()
        return self._load_onnx("mobilenet_ssd_coco_int8.onnx")

    def get_yolov8n(self) -> Any:
        if self._stub:
            return _ZeroStub()
        return self._load_onnx("yolov8n_fp16.onnx")

    def get_yolov8m(self) -> Any:
        if self._stub:
            return _ZeroStub()
        return self._load_onnx("yolov8m_fp32.onnx")

    def get_madgwick_filter(self) -> Any:
        if self._stub:
            return _ZeroStub()
        if "madgwick" not in self._cache:
            import ahrs.filters  # noqa: PLC0415
            self._cache["madgwick"] = ahrs.filters.Madgwick()
        return self._cache["madgwick"]

    def get_ekf(self) -> Any:
        if self._stub:
            return _ZeroStub()
        if "ekf" not in self._cache:
            from filterpy.kalman import ExtendedKalmanFilter  # noqa: PLC0415
            self._cache["ekf"] = ExtendedKalmanFilter(dim_x=6, dim_z=3)
        return self._cache["ekf"]

    def get_astar_planner(self) -> Callable:
        if self._stub:
            return lambda *a, **kw: []
        if "astar" not in self._cache:
            from skimage.graph import route_through_array  # noqa: PLC0415

            def _planner(occupancy_grid, start, end):
                path, _ = route_through_array(occupancy_grid, start, end, fully_connected=True)
                return path

            self._cache["astar"] = _planner
        return self._cache["astar"]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_onnx(self, filename: str) -> Any:
        if filename in self._cache:
            return self._cache[filename]
        import onnxruntime as ort  # noqa: PLC0415
        path = _MODEL_DIR / filename
        if not path.exists():
            url = _URLS.get(filename, "")
            if not url:
                raise FileNotFoundError(f"No download URL for {filename}")
            self._download(url, path)
        session = ort.InferenceSession(str(path))
        self._cache[filename] = session
        return session

    @staticmethod
    def _download(url: str, dest: Path) -> None:
        import urllib.request  # noqa: PLC0415
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"[ModelRegistry] Downloading {dest.name} …")
        urllib.request.urlretrieve(url, dest)
        print(f"[ModelRegistry] Saved to {dest}")

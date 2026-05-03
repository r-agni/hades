import pytest
import sys

from hades.cesium import (
    DEFAULT_CESIUM_EXTENSION_ZIP_URL,
    assert_isaac_runtime_compatible,
    parse_version,
    runtime_config,
)


def test_cesium_defaults_point_to_requested_release(monkeypatch) -> None:
    monkeypatch.delenv("CESIUM_EXTENSION_ZIP_URL", raising=False)
    monkeypatch.setenv("CESIUM_ION_TOKEN", "token-for-test")

    cfg = runtime_config()

    assert cfg.extension_zip_url == DEFAULT_CESIUM_EXTENSION_ZIP_URL
    assert "v0.28.0" in cfg.extension_zip_url
    if sys.platform.startswith("win"):
        assert "windows-x86_64" in cfg.extension_zip_url
    else:
        assert "linux-x86_64" in cfg.extension_zip_url
    assert cfg.latitude_deg == 35.17
    assert cfg.longitude_deg == -114.57
    assert cfg.height_m == 165.0


def test_cesium_token_is_required(monkeypatch) -> None:
    monkeypatch.delenv("CESIUM_ION_TOKEN", raising=False)
    monkeypatch.setenv("CESIUM_DISABLE_DOTENV", "1")

    with pytest.raises(RuntimeError, match="CESIUM_ION_TOKEN"):
        runtime_config()


def test_isaac_runtime_gate_rejects_kit_107() -> None:
    with pytest.raises(RuntimeError, match="Kit 109"):
        assert_isaac_runtime_compatible(app_version="5.1.0", build_version="107.3.3")


def test_isaac_runtime_gate_accepts_kit_109() -> None:
    assert_isaac_runtime_compatible(app_version="6.0.0", build_version="109.0.0")


def test_isaac_runtime_gate_rejects_kit_110() -> None:
    with pytest.raises(RuntimeError, match="Kit 109"):
        assert_isaac_runtime_compatible(app_version="6.0.0", build_version="110.0.0")


def test_parse_version_accepts_build_strings() -> None:
    assert parse_version("107.3.3+production.229672") == (107, 3, 3)
    assert parse_version("Isaac Sim 6.0") == (6, 0, 0)

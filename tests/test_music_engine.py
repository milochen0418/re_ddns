"""The Mac-side music engine helper (music_engine/music_engine.py): tokens, the size that fits a
Mac, and whether the weights are whole. Standard-library code, imported from its file."""

import base64
import hashlib
import hmac
import importlib.util
import json
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("music_engine", ROOT / "music_engine" / "music_engine.py")
engine = importlib.util.module_from_spec(spec)
spec.loader.exec_module(engine)


def _token(secret: str, **claims) -> str:
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    head = b64(json.dumps({"alg": "HS256"}).encode())
    body = b64(json.dumps({"aud": "music-engine", "exp": time.time() + 60, **claims}).encode())
    return f"{head}.{body}." + b64(hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest())


def test_only_a_token_signed_with_the_platform_secret_for_this_audience_opens_the_door():
    assert engine.verify("Bearer " + _token("s3cret", sub="ai-hub"), "s3cret")["sub"] == "ai-hub"
    for bad, why in (
        ("Bearer " + _token("other"), "wrong signature"),
        ("Bearer " + _token("s3cret", aud="ai-hub"), "something else"),
        ("Bearer " + _token("s3cret", exp=time.time() - 1), "expired"),
        ("Basic abc", "Bearer"),
        ("", "Bearer"),
    ):
        with pytest.raises(ValueError, match=why):
            engine.verify(bad, "s3cret")


def test_the_size_follows_the_memory():
    assert engine.choose_tier(16) == "small"
    assert engine.choose_tier(0) == "standard", "unknown memory doesn't mean a small Mac"
    assert engine.choose_tier(24) == "standard"
    assert engine.choose_tier(64) == "standard"
    assert engine.TIERS["small"]["gb"] < engine.TIERS["standard"]["gb"]
    assert set(engine.PARTS) == set(engine.TIERS)


def test_a_part_is_whole_only_with_its_config_its_weights_and_no_download_left(tmp_path):
    root = tmp_path
    part = root / "acestep-v15-turbo"
    part.mkdir()
    assert not engine.part_whole(root, "acestep-v15-turbo")
    (part / "config.json").write_text("{}")
    assert not engine.part_whole(root, "acestep-v15-turbo"), "no weights yet"
    with open(part / "model.safetensors", "wb") as f:
        f.truncate(150_000_000)
    assert engine.part_whole(root, "acestep-v15-turbo")
    pending = root / ".cache" / "huggingface" / "download" / "acestep-v15-turbo"
    pending.mkdir(parents=True)
    (pending / "model.safetensors.incomplete").write_bytes(b"x")
    assert not engine.part_whole(root, "acestep-v15-turbo"), "still downloading"


def test_what_is_missing_is_said_per_part(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "CHECKPOINTS", tmp_path)
    assert engine.weights_missing("small") == engine.PARTS["small"]
    for name in ("vae", "Qwen3-Embedding-0.6B"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "config.json").write_text("{}")
        with open(tmp_path / name / "w.safetensors", "wb") as f:
            f.truncate(150_000_000)
    assert engine.weights_missing("small") == ["acestep-v15-turbo", "acestep-5Hz-lm-0.6B"]


def test_room_is_checked_before_an_install(monkeypatch):
    monkeypatch.setattr(engine, "disk_free_gb", lambda path=None: 12.0)
    monkeypatch.setattr(engine, "memory_gb", lambda: 24.0)
    monkeypatch.setattr(engine, "installed_gb", lambda tier: 0.0)
    ok, why = engine.fits("standard")
    assert not ok and "GB free" in why
    monkeypatch.setattr(engine, "disk_free_gb", lambda path=None: 200.0)
    monkeypatch.setattr(engine, "memory_gb", lambda: 8.0)
    ok, why = engine.fits("small")
    assert not ok and "16 GB" in why
    monkeypatch.setattr(engine, "memory_gb", lambda: 24.0)
    assert engine.fits("standard") == (True, "")

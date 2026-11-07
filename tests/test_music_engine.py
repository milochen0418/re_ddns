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


def test_a_song_lets_the_planner_think_and_a_cover_does_not(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "UPLOADS", tmp_path)
    song = engine.release_body("j1", {"caption": "synthwave", "lyrics": "[Verse 1]\nla", "language": "zh", "duration": 60})
    assert song["task_type"] == "text2music" and song["thinking"] is True and "use_cot_caption" not in song
    assert song["audio_duration"] == 60 and song["use_random_seed"] is True and song["seed"] == -1
    audio = base64.b64encode(b"ID3fake").decode()
    cover = engine.release_body("j2", {"task": "cover", "caption": "rock", "lyrics": "[Instrumental]", "audio_b64": audio, "audio_format": "mp3", "cover_strength": 0.75, "thinking": True})
    assert cover["thinking"] is False and cover["use_cot_caption"] is False and cover["use_cot_language"] is False, "ACE-Step plans nothing for a cover"
    assert cover["audio_cover_strength"] == 0.75 and Path(cover["src_audio_path"]).read_bytes() == b"ID3fake"
    assert "reference_audio_path" not in cover and "chunk_mask_mode" not in cover


def test_a_seed_makes_the_same_song_again(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "UPLOADS", tmp_path)
    body = engine.release_body("j3", {"caption": "x", "seed": 1234})
    assert body["use_random_seed"] is False and body["seed"] == 1234


def test_a_repaint_reaches_the_model_only_in_its_window(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "UPLOADS", tmp_path)
    audio = base64.b64encode(b"ID3take").decode()
    body = engine.release_body("j4", {"task": "repaint", "caption": "x", "lyrics": "y", "audio_b64": audio, "repaint_start": 30, "repaint_end": 52.5, "repaint_mode": "aggressive"})
    assert body["repainting_start"] == 30.0 and body["repainting_end"] == 52.5 and body["chunk_mask_mode"] == "explicit"
    assert body["repaint_mode"] == "aggressive" and body["thinking"] is False
    odd = engine.release_body("j5", {"task": "repaint", "audio_b64": audio, "repaint_start": 0, "repaint_mode": "wild"})
    assert "repaint_mode" not in odd and odd["repainting_end"] == -1


def test_the_recording_can_also_be_the_sound_to_aim_for(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "UPLOADS", tmp_path)
    audio = base64.b64encode(b"ID3song").decode()
    body = engine.release_body("j6", {"task": "cover", "audio_b64": audio, "reference": "source"})
    assert body["reference_audio_path"] == body["src_audio_path"]

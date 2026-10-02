"""Tests for the streaming gateway.

Fast tests (no model) run always; engine tests are skipped unless
RUN_ENGINE_TESTS=1 and local weights are present.
"""

import os

import numpy as np
import pytest
from fastapi.testclient import TestClient

import gateway.app as app_mod

WEIGHTS = os.path.join(app_mod.MODEL_DIR, "kokoro-v1_0.pth")
VOICE = os.path.join(app_mod.VOICE_DIR, f"{app_mod.DEFAULT_VOICE}.pt")
engine_required = pytest.mark.skipif(
    not (os.environ.get("RUN_ENGINE_TESTS") == "1" and os.path.isfile(WEIGHTS)),
    reason="set RUN_ENGINE_TESTS=1 with local weights to run engine tests",
)


@pytest.fixture()
def client():
    with TestClient(app_mod.app) as c:
        yield c


def test_split_sentences_keeps_order_and_content():
    text = "One two. Three four! Five six? Seven"
    assert app_mod.split_sentences(text) == ["One two.", "Three four!", "Five six?", "Seven"]


def test_split_sentences_handles_newlines_and_multiple_spaces():
    assert app_mod.split_sentences("Hello  there.\n\nSecond line.") == ["Hello there.", "Second line."]


def test_split_sentences_caps_long_run_on_sentences():
    text = ("word " * 500).strip()
    chunks = app_mod.split_sentences(text)
    assert len(chunks) > 1
    assert all(len(c) <= app_mod.MAX_CHUNK_CHARS for c in chunks)


def test_split_sentences_joins_back_to_original():
    text = ("word " * 500).strip()
    assert " ".join(app_mod.split_sentences(text)) == text


def test_split_sentences_empty_input():
    assert app_mod.split_sentences("   \n  \n ") == []


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "loading")


def test_voices_lists_default(client):
    data = client.get("/voices").json()
    assert data["default"] == app_mod.DEFAULT_VOICE


def test_speak_rejects_blank_text(client):
    assert client.post("/speak", json={"text": "   "}).status_code == 400


def test_speak_rejects_unknown_voice(client):
    assert client.post("/speak", json={"text": "hi", "voice": "nope_xyz"}).status_code == 404


def test_voice_path_rejects_traversal(client):
    assert client.post("/speak", json={"text": "hi", "voice": "../etc/passwd"}).status_code in (400, 404)


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_encode_mp3_roundtrip():
    sr = app_mod.SAMPLE_RATE
    t = np.linspace(0, 1.0, sr, endpoint=False)
    tone = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
    data = app_mod.encode_mp3(tone)
    assert len(data) > 1000
    has_id3 = data[:3] == b"ID3"
    has_frame_sync = data[0] == 0xFF and (data[1] & 0xE0) == 0xE0
    assert has_id3 or has_frame_sync


@engine_required
def test_synthesize_produces_audio():
    audio = app_mod.synthesize("Hello world.", VOICE, 1.0)
    assert audio.dtype == np.float32
    assert len(audio) > 4800  # >= 0.2s at 24kHz


@engine_required
def test_speak_streams_valid_mp3(client):
    r = client.post("/speak", json={"text": "One sentence. Another one.", "voice": app_mod.DEFAULT_VOICE})
    assert r.status_code == 200
    assert r.headers["content-type"] == "audio/mpeg"
    assert len(r.content) > 5000

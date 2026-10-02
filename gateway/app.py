"""Streaming TTS gateway.

POST /speak synthesizes text sentence-by-sentence and streams MP3 back, so
playback on the phone starts after the first sentence instead of the whole text.
The Kokoro-82M engine runs in-process: one worker owns one loaded model, which
avoids the startup serialisation that multi-worker setups introduce.
"""

import asyncio
import os
import re
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass

import numpy as np
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

MODEL_DIR = os.environ.get("MODEL_DIR", "models/Kokoro-82M")
VOICE_DIR = os.path.join(MODEL_DIR, "voices")
DEFAULT_VOICE = os.environ.get("DEFAULT_VOICE", "af_heart")
SAMPLE_RATE = 24000
BITRATE = os.environ.get("MP3_BITRATE", "128k")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

SENT_SPLIT = re.compile(r"(?<=[.!?\u3002\uff01\uff1f])\s+")
MAX_CHUNK_CHARS = 420

app = FastAPI(title="mac-voice-service", version="1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_model = None
_pipe = None
_lock = threading.Lock()


@dataclass
class SpeakRequest:
    text: str
    voice: str = DEFAULT_VOICE
    speed: float = 1.0


def engine():
    global _model, _pipe
    if _pipe is None:
        from kokoro import KPipeline
        from kokoro.model import KModel

        t0 = time.perf_counter()
        _model = KModel(
            repo_id="hexgrad/Kokoro-82M",
            config=os.path.join(MODEL_DIR, "config.json"),
            model=os.path.join(MODEL_DIR, "kokoro-v1_0.pth"),
        ).eval()
        _pipe = KPipeline(lang_code="a", repo_id="hexgrad/Kokoro-82M", model=_model)
        print(f"[engine] loaded locally in {time.perf_counter() - t0:.1f}s", flush=True)
    return _pipe


def split_sentences(text: str) -> list[str]:
    out: list[str] = []
    for raw in re.split(r"\n+", text.strip()):
        raw = raw.strip()
        if not raw:
            continue
        for part in SENT_SPLIT.split(raw):
            # Collapse internal runs of spaces/tabs so pasted columns don't stall G2P.
            part = re.sub(r"[ \t]+", " ", part).strip()
            while len(part) > MAX_CHUNK_CHARS:
                cut = part.rfind(" ", 0, MAX_CHUNK_CHARS)
                cut = cut if cut > 0 else MAX_CHUNK_CHARS
                out.append(part[:cut].strip())
                part = part[cut:].strip()
            if part:
                out.append(part)
    return out


def available_voices() -> list[str]:
    try:
        return sorted(f[:-3] for f in os.listdir(VOICE_DIR) if f.endswith(".pt"))
    except OSError:
        return []


def voice_path(voice: str) -> str:
    if "/" in voice or ".." in voice:
        raise HTTPException(status_code=400, detail="bad voice")
    if not voice.endswith(".pt"):
        voice = f"{voice}.pt"
    path = os.path.join(VOICE_DIR, voice)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"unknown voice: {voice[:-3]}")
    return path


def synthesize(text: str, voice: str, speed: float) -> np.ndarray:
    pipe = engine()
    with _lock:
        blocks = [np.asarray(a) for _, _, a in pipe(text, voice=voice, speed=speed, split_pattern=None)]
    if not blocks:
        raise HTTPException(status_code=422, detail="no audio produced")
    return np.concatenate(blocks)


def encode_mp3(audio: np.ndarray) -> bytes:
    """Encode PCM to MP3 via piped ffmpeg; MPEG frames concatenate cleanly across chunks."""
    proc = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-f", "f32le", "-ar", str(SAMPLE_RATE), "-ac", "1", "-i", "-",
            "-c:a", "libmp3lame", "-b:a", BITRATE, "-f", "mp3", "-",
        ],
        input=audio.astype(np.float32).tobytes(),
        stdout=subprocess.PIPE,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise HTTPException(status_code=500, detail="mp3 encode failed")
    return proc.stdout


@app.get("/health")
def health():
    return {"status": "ok" if _pipe is not None else "loading", "model": MODEL_DIR,
            "voices": len(available_voices())}


@app.get("/voices")
def voices():
    return {"default": DEFAULT_VOICE, "voices": available_voices()}


@app.post("/speak")
async def speak(req: SpeakRequest, request: Request):
    if not req.text or not req.text.strip():
        raise HTTPException(status_code=400, detail="text is required")
    voice = voice_path(req.voice)
    speed = max(0.5, min(2.0, float(req.speed or 1.0)))
    sentences = split_sentences(req.text)

    async def stream():
        loop = asyncio.get_running_loop()
        t0 = time.perf_counter()
        produced, first = 0.0, True
        for i, sent in enumerate(sentences):
            if await request.is_disconnected():
                print(f"[speak] client disconnected after {i} chunks", flush=True)
                return
            audio = await loop.run_in_executor(None, synthesize, sent, voice, speed)
            data = await loop.run_in_executor(None, encode_mp3, audio)
            produced += len(audio) / SAMPLE_RATE
            if first:
                print(f"[speak] first chunk in {time.perf_counter() - t0:.2f}s "
                      f"({len(audio) / SAMPLE_RATE:.2f}s audio, {len(data)} bytes)", flush=True)
                first = False
            yield data
        elapsed = time.perf_counter() - t0
        print(f"[speak] streamed {i + 1}/{len(sentences)} sentences, {produced:.1f}s audio "
              f"in {elapsed:.2f}s (RTF {elapsed / max(produced, 1e-6):.2f})", flush=True)

    return StreamingResponse(
        stream(),
        media_type="audio/mpeg",
        headers={
            "Content-Disposition": 'inline; filename="speech.mp3"',
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-store",
        },
    )


@app.get("/")
def index():
    return FileResponse(os.path.join(STATIC_DIR, "index.html"), media_type="text/html")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load weights and run one synthesis so the first user request isn't penalised.

    Measured here: model load ~1.2s, but the first synthesis cost ~4.7s extra
    (torch JIT + spacy/espeak init) — 6.0s to first byte versus 1.3s when warm.
    """

    def warm():
        try:
            engine()
            voice = os.path.join(VOICE_DIR, f"{DEFAULT_VOICE}.pt")
            if os.path.isfile(voice):
                t0 = time.perf_counter()
                encode_mp3(synthesize("Warming up.", voice, 1.0))
                print(f"[engine] warm in {time.perf_counter() - t0:.1f}s", flush=True)
        except Exception as exc:  # never block startup on a failed warmup
            print(f"[engine] warmup failed: {exc}", flush=True)

    threading.Thread(target=warm, daemon=True).start()
    yield


app.router.lifespan_context = lifespan

# mac-voice-service

Self-hosted streaming text-to-speech. Send it any text, hear it on your phone
within about a second. No cloud APIs, no per-character bill.

- **Engine:** [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache 2.0), running locally on CPU.
- **Gateway:** FastAPI, `POST /speak` → sentence chunking → streamed MP3.
- **Phone:** PWA over Tailscale, or an iOS Shortcut from the share sheet.

## Why this design

Docker on macOS (OrbStack included) cannot reach the Metal GPU, so containers get CPU
only. Kokoro-82M is small enough that this is fine: measured **RTF 0.34** on a 30-core
ARM64 CPU, i.e. roughly three times faster than real time, with **0.9–1.3 s** to the
first audio byte. Playback therefore always stays ahead of synthesis.

Sentence-level chunking is what makes it feel instant. Kokoro's own default splits only
on newlines (`split_pattern=r'\n+'`), which would emit one long block and delay playback
until the whole text was rendered. The gateway splits on sentence boundaries instead, so
the first sentence is playing while the rest is still being generated.

The engine runs in-process with a single worker: one process owns one loaded model, so
there is no per-worker startup stampede and no shared-memory copy of the weights.

## Quick start (native, fastest)

```bash
make models   # venv + deps + weights (~356 MB), idempotent
make run      # http://localhost:8000
```

Then open the page, type something, tap **Read**. Or from a terminal:

```bash
curl -N localhost:8000/speak -H 'Content-Type: application/json' \
  -d '{"text":"Hello from your own machine.","voice":"af_heart"}' \
  -o speech.mp3
```

`-N` disables curl buffering so you can watch the stream arrive chunk by chunk.

## OrbStack

```bash
orb start
docker compose build          # pulls python:3.12-slim + torch CPU
docker compose up -d
orb diag --show networking    # optional: confirm port publishing
open http://localhost:8000
```

Weights live in `./models` on the host and mount read-only, so container rebuilds never
re-download them. The healthcheck waits up to 70 s for the model to load and warm up.

If `docker compose build` is slow, note that torch resolves from the CPU wheel index;
the image is ~2 GB and this is a one-off cost.

### Phone access

Install Tailscale on the Mac **and** the phone, then browse to
`http://<mac-tailscale-name>:8000`. Add it to the Home Screen for a near-native app.

A `tailscale` sidecar is included but commented out in `docker-compose.yml`: it needs
`/dev/net/tun`, which OrbStack may not expose. Running Tailscale as the macOS app is
simpler and also gives you MagicDNS. If you do enable the sidecar, set `TS_AUTHKEY`
in `.env`.

### iOS Shortcut (share-sheet route)

1. Shortcuts → New Shortcut → Add Action **Get Contents of URL**.
   - URL: `http://<mac>:8000/speak`
   - Method: POST, Headers `Content-Type: application/json`
   - Request body JSON: `{"text":"###ShortcutInputText###","voice":"af_heart"}`
2. Add **Play Audio** (or Open URL).
3. Enable *Use as share sheet shortcut* and show on the Home Screen.

`ShortcutInputText` substitutes whatever you shared — a webpage selection, an email, etc.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `POST` | `/speak` | `{text, voice?, speed?}` → streamed `audio/mpeg` |
| `GET` | `/voices` | list the 54 local voices |
| `GET` | `/health` | liveness, model dir, voice count |
| `GET` | `/` | PWA client |

`voice` defaults to `af_heart`; the first character encodes language (`a`/`b` = US/UK)
and gender. `speed` is clamped to 0.5–2.0.

## Testing

```bash
make test     # 14 tests; engine tests need local weights
make bench    # first-byte latency + RTF against a running service
```

Verified behaviour, not just unit coverage: streaming chunks arrive incrementally,
concatenated MP3 decodes to the full duration (no gapless-boundary loss), and a client
that hangs up mid-stream stops server-side synthesis instead of rendering the rest.

## Notes on the local environment

- Python must be 3.12: `kokoro` declares `<3.13`, and the system interpreter here is
  3.13, hence the `uv`-managed venv.
- Pin `transformers>=4.40`: an unpinned resolve pulls `transformers==4.12.2`, whose
  `tokenizers` has no aarch64 wheel and fails trying to compile Rust.
- `espeak-ng` and `ffmpeg` are runtime dependencies (phonemisation and MP3 encoding).
- Weights load fully offline via `KModel(config=..., model=...)`; passing only a local
  `repo_id` is not enough, because Kokoro would still hit the Hub for `config.json`.

## Upgrade path

For more expressive voices or voice cloning, run Orpheus or Chatterbox natively with
`mlx-audio` (MLX uses the GPU, which containers cannot) and point the gateway at it:

```bash
TTS_URL=http://host.docker.internal:8883/v1/audio/speech
```

The gateway, PWA, and Shortcut stay unchanged. On 256 GB of unified memory a 7B model
fits comfortably; keep Kokoro warm for latency-sensitive requests and route long-form
reading to the larger model.

## Layout

```
gateway/app.py           FastAPI service: chunking, synthesis, streaming
gateway/static/index.html  PWA phone client
docker-compose.yml       service + optional Tailscale sidecar
Dockerfile               python:3.12-slim + espeak-ng + ffmpeg + torch CPU
scripts/fetch_models.sh  weights download (idempotent)
scripts/stream_probe.py  latency measurement client
tests/test_gateway.py    unit + engine tests
```

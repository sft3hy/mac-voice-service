# Repository notes

## What this is
Streaming TTS microservice: Kokoro-82M (Apache 2.0) on local CPU behind a FastAPI
gateway that splits text into sentences and streams MP3 to a phone over Tailscale.

## Environment constraints (learned the hard way)
- **Python 3.12 is mandatory.** `kokoro` requires `<3.13`; system python here is 3.13,
  so use the `uv`-managed `.venv` (`make models` provisions it).
- **Pin `transformers>=4.40`.** Unpinned resolves `kokoro` → `transformers==4.12.2` →
  `tokenizers` with no aarch64 wheel, failing on a Rust build.
- Runtime apt deps: `espeak-ng` (phonemisation), `ffmpeg`/libmp3lame (MP3 encoding).
- **Offline weight loading requires explicit paths**: `KModel(repo_id=..., config=<path>,
  model=<path>)`. Passing a local dir as `repo_id` alone raises RepositoryNotFoundError,
  because KModel always calls `hf_hub_download` for `config.json`. Voices accept a direct
  `.pt` path.
- No GPU in containers on macOS: OrbStack/Docker cannot reach Metal, so CPU only.
  Native runs are the fastest path; MLX is the GPU upgrade path (see README).

## Sandbox notes
- Containers cannot run in this dev sandbox: the docker daemon starts only as root with
  `--iptables=false --bridge=none --storage-driver=vfs`, and layer extraction then fails
  with `unshare: operation not permitted`. Validate natively (same ARM64 CPU path) and
  run `docker compose` on the user's Mac.
- Port 8000 is occupied by the OpenHands agent server — use 8321 for local testing.
- `browser_type` reports success but its `text` field only ever shows the placeholder;
  confirm real input via server logs, not the accessibility tree.

## Perf baselines (30-core ARM64 CPU)
- Model load ~1.0 s; first audio byte ~0.9–1.3 s warm, ~6 s cold without startup warmup
  (torch JIT + spacy/espeak init). Keep the lifespan warmup — do not remove it.
- RTF ~0.34 (≈3× real time); 33 s of audio in ~11 s.

## Gotchas
- Kokoro's default `split_pattern=r'\n+'` splits only on newlines. Pass
  `split_pattern=None` and chunk sentences in the gateway, or playback waits for the
  whole text.
- Concatenated MP3 frames are valid and gapless; `ffprobe` reports 24 kHz mono, so decode
  checks must not assume 44.1 kHz.
- `uvicorn --workers 1` is deliberate: the model is a per-process singleton.

## Test / run
```bash
make models && make test && make run   # then browse http://localhost:8321
```

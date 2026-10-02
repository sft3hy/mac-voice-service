I want to stand up a microservice on my new Mac Studio 256 gigabyte unified memory. And I want this service to be text to speech. I want it to all be open source, so free, no cloud APIs that cost money. And I want it to be able to stream audio to my phone where it will read it off to me. This service should work with any text that I send it and immediately stream it to my phone. Will you help me design an architecture that does this that I can run via Docker in Orbstack?

Designing a streaming TTS microservice architecture for a Mac setup.
Designing a streaming TTS microservice architecture for a Mac setup.
The one catch: Docker/OrbStack on a Mac can't access the Metal GPU, so containers run on CPU only. That's fine for Kokoro-82M, an open-source (Apache 2.0) model with very good quality that runs faster than real time on Apple Silicon CPU. Your 256 GB is massive overkill for it, which leaves room for bigger models later.

Architecture

Phone ──(Tailscale)──► Gateway (FastAPI) ──► Kokoro-FastAPI
 plays stream           splits text into      generates audio
                        sentences, streams    per sentence
TTS engine: the Kokoro-FastAPI container (ARM64 CPU image). It exposes an OpenAI-compatible /v1/audio/speech endpoint with streaming.
Gateway (small FastAPI app): accepts POST /speak with any text, splits it into sentences, sends each to Kokoro as it goes, and streams the audio back as chunked MP3 or Opus. Sentence-level chunking is what makes playback start in about a second, even for long text.
Phone access: Tailscale (free for personal use) puts your phone and Mac on a private network, so it works anywhere with no port forwarding or public exposure. Run it on the Mac host, or as a sidecar container.
Phone client, pick one:
A simple PWA with a text box and an <audio> element pointed at the stream (works on iOS Safari).
An iOS Shortcut that POSTs text and plays the response. This is great for "read this" from the share sheet.
Compose sketch

yaml
services:
  tts:
    image: ghcr.io/remsky/kokoro-fastapi-cpu:latest
    restart: unless-stopped
  gateway:
    build: ./gateway
    environment:
      TTS_URL: http://tts:8880/v1/audio/speech
    ports: ["8000:8000"]
    depends_on: [tts]
Upgrade path: if you want more expressive voices (Orpheus, Chatterbox, voice cloning), run that model natively on the Mac with MLX (mlx-audio) to use the GPU. Then just change TTS_URL to http://host.docker.internal:PORT. The gateway and phone client stay the same.

Want me to write the gateway code and PWA client next, or do you prefer the Shortcut route for the phone side?

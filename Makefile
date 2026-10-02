.PHONY: models venv run test bench clean

VENV ?= .venv
PORT ?= 8321

# Weights + venv in one shot (idempotent).
models:
	@bash scripts/fetch_models.sh

# Native run — uses the Apple Silicon CPU directly, fastest option.
run:
	MODEL_DIR=$(CURDIR)/models/Kokoro-82M $(VENV)/bin/python -m uvicorn gateway.app:app \
	  --host 0.0.0.0 --port $(PORT) --workers 1

test:
	MODEL_DIR=$(CURDIR)/models/Kokoro-82M RUN_ENGINE_TESTS=1 $(VENV)/bin/python -m pytest tests -q -p no:warnings

# Measure first-byte latency and real-time factor against a running service.
bench:
	$(VENV)/bin/python scripts/stream_probe.py http://127.0.0.1:$(PORT)

clean:
	rm -rf out __pycache__ .pytest_cache
	@echo "kept models/ (delete manually if you really want to)"

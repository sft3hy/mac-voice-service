"""Client-side streaming probe: times each chunk as it arrives."""

import sys
import time

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8321"
TEXT = (
    "First chunk should arrive soon. The second one lands right after. "
    "Here is a third sentence to confirm steady streaming."
)

t0 = time.time()
sizes = []
raw = b""
with httpx.Client(timeout=180) as client:
    with client.stream("POST", f"{BASE}/speak", json={"text": TEXT, "voice": "af_heart"}) as r:
        print("status", r.status_code, "| content-type", r.headers.get("content-type"))
        if r.status_code != 200:
            print(r.read()[:300])
            raise SystemExit(1)
        for block in r.iter_bytes():
            if not sizes:
                print("FIRST BYTES at %.2fs (%d bytes)" % (time.time() - t0, len(block)))
            sizes.append(len(block))
            raw += block

print("blocks: %d | total %d bytes in %.2fs" % (len(sizes), len(raw), time.time() - t0))
open("out/stream.mp3", "wb").write(raw)

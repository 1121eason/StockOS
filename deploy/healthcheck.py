"""Private container liveness check; no provider request or financial mutation."""

import json
import urllib.request

with urllib.request.urlopen("http://127.0.0.1:8511/api/operations/health", timeout=5) as response:
    state = json.load(response)
if not state.get("worker_running"):
    raise SystemExit("background worker is not healthy")

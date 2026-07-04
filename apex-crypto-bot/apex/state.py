"""State persistence — survives restarts. Saves open_position + paper_balance to a json file."""
import os
import json
import time
from datetime import datetime, timezone

STATE_FILE = os.getenv("STATE_FILE", "/tmp/apex-state.json")


def save(paper_balance, open_position):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump({"paperBalance": paper_balance, "openPosition": open_position,
                       "savedAt": datetime.now(timezone.utc).isoformat()}, f, indent=2)
    except Exception as e:
        print(f"[STATE] Cannot save state: {e}")


def load(default_balance=None):
    try:
        if not os.path.exists(STATE_FILE):
            return None
        with open(STATE_FILE) as f:
            data = json.load(f)
        saved_at = datetime.fromisoformat(data["savedAt"])
        age = time.time() - saved_at.timestamp()
        if age > 24 * 60 * 60:
            print("[STATE] State too old (>24h) — ignored, fresh start.")
            return None
        print(f"[STATE] ♻️  State restored from {data['savedAt']}")
        if data.get("openPosition"):
            p = data["openPosition"]
            print(f"[STATE] 📌 Position recovered: {p['side']} {p.get('symbol')} @ ${p['entryPrice']}")
        return data
    except Exception as e:
        print(f"[STATE] Cannot read state: {e}")
        return None


def clear():
    try:
        os.remove(STATE_FILE)
    except OSError:
        pass

#!/usr/bin/env python3
"""Regenerate config/bot-config-fields.json from apex/settings_policy.

The licence server (server.js) filters the configuration it returns down to
the keys the bot can actually apply. That list lives in Python, so rather than
keep a second copy in JavaScript — the copy that drifts the day someone adds a
setting on one side only — both read one generated file.

A test asserts the file still matches the tables, so a forgotten regeneration
fails loudly instead of silently starving the bot of a setting.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "apex-forex-bot"))
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")

from apex import settings_policy as sp  # noqa: E402

OUT = os.path.join(ROOT, "config", "bot-config-fields.json")
existing = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}

doc = {
    "_comment": existing.get("_comment", []),
    "runtime": sorted(sp.REMOTE_SETTABLE),
    "provisioning": sorted(sp.REMOTE_PROVISIONING),
}
os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(doc, f, indent=2)
    f.write("\n")
print(f"wrote {OUT}: {len(doc['runtime'])} runtime, "
      f"{len(doc['provisioning'])} provisioning")

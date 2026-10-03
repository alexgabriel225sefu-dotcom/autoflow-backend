"""APEX TRADE BOT (Python) — run: python main.py"""
# Force line-buffered stdout/stderr so the trading loop's print() output reaches
# the host log viewer in real time even when started as `python main.py`
# (without -u) and PYTHONUNBUFFERED isn't set — otherwise the logs look empty.
import sys
try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

# Scrub credentials out of everything printed from here on. Installed at the
# entrypoint, BEFORE the bot is imported, so it covers module-level output and
# any print() added later by someone who has never heard of apex/redact.py —
# which is the point of doing it centrally rather than per log line.
from apex import redact
redact.install()

from apex.bot import main

if __name__ == "__main__":
    main()

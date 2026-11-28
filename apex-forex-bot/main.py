"""Retired process entry.

The web platform is `platform_server.py`. Running this file does not start
a trading loop.
"""
import sys

try:
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)
except Exception:
    pass

from apex import redact
redact.install()


def main():
    print("This entry no longer starts a service. "
          "Start the platform with: python -u platform_server.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

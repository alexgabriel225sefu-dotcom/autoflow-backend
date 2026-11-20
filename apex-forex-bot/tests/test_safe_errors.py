"""Regression checks for provider-error redaction at API boundaries."""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from apex.platform.safe_errors import message


def _check(label, condition):
    if not condition:
        raise AssertionError(label)
    print(f"ok   {label}")


secret = "access_token=super-secret-token-value"
out = message(ValueError(secret + " https://broker.example.test/x C:\\private\\trace.log"))
_check("access tokens are redacted", "super-secret-token-value" not in out)
_check("URLs are redacted", "broker.example.test" not in out)
_check("paths are redacted", "private" not in out)
_check("messages are bounded", len(message("x" * 1000)) <= 300)
print("all safe-error checks passed")

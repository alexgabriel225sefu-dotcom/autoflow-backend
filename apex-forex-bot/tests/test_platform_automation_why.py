"""Regression tests for the dashboard's automation explanation read."""
import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from apex.platform import api


def main():
    old_auth = api._authenticate
    old_status = api._auto.status
    old_query = api._jstore.query
    try:
        api._authenticate = lambda headers, fresh=False: SimpleNamespace(user_id="u1")
        api._auto.status = lambda user_id: {"state": "running"}
        api._jstore.query = lambda user_id, **kw: {
            "entries": [{"status": "hold", "ts": 1, "decision": {"reason": "market closed"}}]
        }
        status, body = api._dispatch("GET", "automation/why", {}, None)
        assert status == 200, (status, body)
        assert body["ok"] is True
        assert body["summary"] == "Automation is watching for a setup."
        assert body["recorded"][0]["reason"] == "market closed"

        status, body = api._dispatch("POST", "automation/why", {}, None)
        assert status == 404, (status, body)
    finally:
        api._authenticate = old_auth
        api._auto.status = old_status
        api._jstore.query = old_query
    print("test_platform_automation_why: PASS")


if __name__ == "__main__":
    main()

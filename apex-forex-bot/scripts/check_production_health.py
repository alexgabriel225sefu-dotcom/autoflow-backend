#!/usr/bin/env python3
"""Read-only production monitor for Apex4Traders.

The script is deliberately small and dependency-free so it can run from a
free GitHub Actions job or from any external cron. It performs only HTTP GETs.
It never calls an authenticated route and never writes to the services.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

API_HEALTHZ = "https://apex4traders-api.onrender.com/healthz"
API_READYZ = "https://apex4traders-api.onrender.com/readyz"
WEB_HOME = "https://apex4traders-web.onrender.com/"
TIMEOUT_SEC = float(os.getenv("A4T_MONITOR_TIMEOUT_SEC", "20"))
RETRIES = int(os.getenv("A4T_MONITOR_RETRIES", "2"))
EXPECTED_API_COMMIT = (os.getenv("A4T_EXPECTED_API_COMMIT") or "").strip()


@dataclass
class Result:
    name: str
    ok: bool
    message: str
    detail: dict[str, Any]


def _get(url: str) -> tuple[int | None, str, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": "apex4traders-monitor/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:  # nosec B310 - fixed HTTPS URLs
            charset = resp.headers.get_content_charset() or "utf-8"
            body = resp.read(1024 * 1024).decode(charset, errors="replace")
            return resp.status, body, None
    except urllib.error.HTTPError as exc:
        body = exc.read(1024 * 1024).decode("utf-8", errors="replace")
        return exc.code, body, None
    except Exception as exc:  # transport failure is the alert
        return None, "", f"{type(exc).__name__}: {exc}"


def fetch(url: str) -> tuple[int | None, str, str | None]:
    last: tuple[int | None, str, str | None] = (None, "", "not attempted")
    for attempt in range(RETRIES + 1):
        last = _get(url)
        status, _body, error = last
        if error is None and status is not None:
            return last
        if attempt < RETRIES:
            time.sleep(min(2 ** attempt, 5))
    return last


def _json(body: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        data = json.loads(body)
    except json.JSONDecodeError as exc:
        return None, f"invalid JSON: {exc}"
    if not isinstance(data, dict):
        return None, "JSON response is not an object"
    return data, None


def _release_commit(data: dict[str, Any]) -> str:
    release = data.get("release") if isinstance(data.get("release"), dict) else {}
    return str(release.get("commit") or "").strip()


def _commit_problem(name: str, data: dict[str, Any]) -> str | None:
    commit = _release_commit(data)
    if not commit:
        return f"{name} does not report release.commit"
    if EXPECTED_API_COMMIT and not commit.startswith(EXPECTED_API_COMMIT):
        return (f"{name} is running commit {commit}, expected "
                f"{EXPECTED_API_COMMIT}; the deploy may not have taken")
    return None


def check_healthz() -> Result:
    status, body, error = fetch(API_HEALTHZ)
    if error:
        return Result("api_healthz", False, f"transport failure: {error}", {"url": API_HEALTHZ})
    data, json_error = _json(body)
    if status != 200:
        return Result("api_healthz", False, f"HTTP {status}", {"url": API_HEALTHZ, "body": body[:500]})
    if json_error or data is None:
        return Result("api_healthz", False, json_error or "invalid JSON", {"url": API_HEALTHZ})
    if data.get("ok") is not True or data.get("status") != "ok":
        return Result("api_healthz", False, "liveness JSON is not ok", {"payload": data})
    commit_problem = _commit_problem("healthz", data)
    if commit_problem:
        return Result("api_healthz", False, commit_problem, {"payload": data})
    return Result("api_healthz", True, "backend process is alive", {"commit": _release_commit(data)})


def check_readyz() -> Result:
    status, body, error = fetch(API_READYZ)
    if error:
        return Result("api_readyz", False, f"transport failure: {error}", {"url": API_READYZ})
    data, json_error = _json(body)
    if json_error or data is None:
        return Result("api_readyz", False, json_error or "invalid JSON", {"status": status, "body": body[:500]})
    checks = data.get("checks") if isinstance(data.get("checks"), list) else []
    failed = [c for c in checks if isinstance(c, dict) and c.get("status") == "fail"]
    if status != 200 or data.get("ok") is not True or data.get("status") != "ok" or failed:
        names = [str(c.get("name")) for c in failed if c.get("name")]
        return Result(
            "api_readyz",
            False,
            "readiness failed: " + (", ".join(names) if names else f"HTTP {status}"),
            {"url": API_READYZ, "failedChecks": failed, "payload": data},
        )
    commit_problem = _commit_problem("readyz", data)
    if commit_problem:
        return Result("api_readyz", False, commit_problem, {"payload": data})
    return Result("api_readyz", True, "backend dependencies are ready", {"commit": _release_commit(data)})


# A selector that only exists if the app's own stylesheet was built and
# served. Deliberately a token name rather than a colour: the value may be
# re-approved, the token is the thing the whole palette is defined against.
STYLESHEET_MARKER = os.getenv("A4T_MONITOR_CSS_MARKER", "--a4t-accent")
_CSS_HREF = re.compile(r'href="(/_next/static/[^"]+\.css)"')


def check_web() -> Result:
    status, body, error = fetch(WEB_HOME)
    if error:
        return Result("web_home", False, f"transport failure: {error}", {"url": WEB_HOME})
    if status != 200:
        return Result("web_home", False, f"HTTP {status}", {"url": WEB_HOME, "body": body[:500]})
    if "Apex" not in body and "apex" not in body:
        return Result("web_home", False, "home page did not contain Apex copy", {"url": WEB_HOME})
    return Result("web_home", True, "web home page is reachable", {"status": status})


def check_web_stylesheet() -> Result:
    """The page can be whole and still be broken.

    THE FAILURE THIS EXISTS FOR, which has shipped twice.

    Both times the web service broke, it answered HTTP 200 with every word of
    copy present and NO WORKING STYLESHEET — a build served a CSS chunk from a
    previous build, or an empty one. Every content check passes on that page:
    the markup is right, the text is right, nothing errors. It is simply
    unreadable, and it is the landing page an advertisement pays to put in
    front of a stranger.

    So this follows the stylesheet the home page actually links, rather than
    guessing a path, and asks whether the app's own tokens are in it. A chunk
    that 200s with the wrong contents is the whole point; checking only that
    the URL answers would miss it exactly as the content check does.
    """
    status, body, error = fetch(WEB_HOME)
    if error or status != 200:
        # check_web already alerts on this. Reporting it twice turns one
        # outage into two pages, and the second one says nothing new.
        return Result("web_css", True, "skipped: the home page is already alerting",
                      {"skipped": True})

    hrefs = _CSS_HREF.findall(body)
    if not hrefs:
        return Result("web_css", False,
                      "the home page links no stylesheet at all",
                      {"url": WEB_HOME})

    href = hrefs[0]
    url = WEB_HOME.rstrip("/") + href
    status, css, error = fetch(url)
    if error:
        return Result("web_css", False, f"stylesheet transport failure: {error}", {"url": url})
    if status != 200:
        return Result("web_css", False, f"stylesheet returned HTTP {status}", {"url": url})
    if STYLESHEET_MARKER not in css:
        return Result(
            "web_css", False,
            f"the served stylesheet does not define {STYLESHEET_MARKER} — "
            f"the page will render unstyled",
            {"url": url, "bytes": len(css)})
    return Result("web_css", True, "the served stylesheet carries the app tokens",
                  {"bytes": len(css)})


def run() -> list[Result]:
    return [check_healthz(), check_readyz(), check_web(),
            check_web_stylesheet()]


def main() -> int:
    results = run()
    for result in results:
        prefix = "OK" if result.ok else "FAIL"
        print(f"{prefix} {result.name}: {result.message}")
        if result.detail:
            print(json.dumps(result.detail, sort_keys=True, ensure_ascii=False))
        if not result.ok:
            # GitHub Actions annotation. Other runners treat it as plain text.
            print(f"::error title={result.name}::{result.message}")
    return 0 if all(r.ok for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

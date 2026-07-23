"""Crypto market sentiment — Alternative.me Fear & Greed Index.

Free, no API key, no account needed: a single 0-100 market-wide score
(0 = Extreme Fear, 100 = Extreme Greed) built from volatility, momentum/
volume, social media, surveys and BTC dominance. This is CONTEXT for the
AI signal, not a prediction — it nudges confidence, it never picks a
direction on its own.

Same fail-open contract as news.py: if the feed is unreachable, empty, or
malformed, callers get None and trading proceeds unaffected.
"""
import threading
import time

import requests

_URL = "https://api.alternative.me/fng/?limit=1"
_TTL = 3600  # the index only updates once a day; re-fetch hourly is plenty
_TIMEOUT = (3.05, 6)

_cache = {"ts": 0.0, "value": None, "label": None}
_state = {"fetching": False, "fails": 0, "next_retry": 0.0}
_lock = threading.Lock()


def _do_fetch():
    try:
        r = requests.get(_URL, headers={"User-Agent": "ApexBot/1.0"}, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        row = (data.get("data") or [{}])[0]
        value = int(row["value"])
        label = row.get("value_classification") or _label_for(value)
        with _lock:
            _cache["value"] = value
            _cache["label"] = label
            _cache["ts"] = time.time()
            _state["fails"] = 0
            _state["next_retry"] = 0.0
    except Exception as ex:
        with _lock:
            _state["fails"] += 1
            backoff = min(_TTL, 60 * (2 ** (_state["fails"] - 1)))
            _state["next_retry"] = time.time() + backoff
        print(f"[SENTIMENT] feed unavailable ({ex}) — fail-open, retry in ~{int(backoff)}s")
    finally:
        with _lock:
            _state["fetching"] = False


def _label_for(value):
    if value <= 24:  return "Extreme Fear"
    if value <= 44:  return "Fear"
    if value <= 55:  return "Neutral"
    if value <= 75:  return "Greed"
    return "Extreme Greed"


def fear_greed():
    """Returns {"value": 0-100, "label": str} or None (fail-open — never
    raises, never blocks the trading loop on a slow/down feed)."""
    now = time.time()
    with _lock:
        fresh = _cache["value"] is not None and now - _cache["ts"] < _TTL
        should_fetch = not fresh and not _state["fetching"] and now >= _state["next_retry"]
        if should_fetch:
            _state["fetching"] = True
        value, label = _cache["value"], _cache["label"]
    if should_fetch:
        threading.Thread(target=_do_fetch, name="sentiment-refresh", daemon=True).start()
    if value is None:
        return None
    return {"value": value, "label": label}

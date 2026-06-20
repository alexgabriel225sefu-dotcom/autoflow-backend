"""Affiliate data — per-user isolated JSON storage."""
import json
import os
import time
import random
import string

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_IDX = os.path.join(_DIR, "_index.json")   # ref_code → chat_id


def _path(chat_id):
    os.makedirs(_DIR, exist_ok=True)
    return os.path.join(_DIR, f"{chat_id}.json")


def _load(chat_id):
    try:
        return json.loads(open(_path(str(chat_id))).read())
    except Exception:
        return None


def _save(chat_id, data):
    with open(_path(str(chat_id)), "w") as f:
        json.dump(data, f, indent=2)


def _load_index():
    try:
        return json.loads(open(_IDX).read())
    except Exception:
        return {}


def _save_index(idx):
    os.makedirs(_DIR, exist_ok=True)
    with open(_IDX, "w") as f:
        json.dump(idx, f, indent=2)


def _gen_code():
    chars = string.ascii_uppercase + string.digits
    return "".join(random.choices(chars, k=8))


# ─── Public API ───────────────────────────────────────────

def register(chat_id, username=""):
    """Register new affiliate. Returns (data, is_new)."""
    chat_id = str(chat_id)
    existing = _load(chat_id)
    if existing:
        return existing, False
    idx = _load_index()
    code = _gen_code()
    while code in idx:
        code = _gen_code()
    data = {
        "chat_id": chat_id,
        "username": username,
        "ref_code": code,
        "registered_at": time.time(),
        "clicks": 0,
        "sales": [],
        "total_earned": 0.0,
        "total_paid": 0.0,
        "payout_requests": [],
    }
    _save(chat_id, data)
    idx[code] = chat_id
    _save_index(idx)
    return data, True


def get(chat_id):
    return _load(str(chat_id))


def get_by_code(ref_code):
    """Returns (chat_id, data) or (None, None)."""
    idx = _load_index()
    chat_id = idx.get(ref_code.strip().upper())
    if not chat_id:
        return None, None
    return chat_id, _load(chat_id)


def record_click(ref_code):
    """Increment click counter for this ref code."""
    chat_id, data = get_by_code(ref_code)
    if not data:
        return False
    data["clicks"] = data.get("clicks", 0) + 1
    _save(chat_id, data)
    return True


def record_sale(ref_code, amount_usd, commission_pct=0.30, product="Apex Bot"):
    """Record a sale. Returns (chat_id, commission) or (None, 0)."""
    chat_id, data = get_by_code(ref_code)
    if not data:
        return None, 0.0
    commission = round(float(amount_usd) * commission_pct, 2)
    data.setdefault("sales", []).append({
        "time": time.time(),
        "product": product,
        "amount": float(amount_usd),
        "commission": commission,
        "paid": False,
    })
    data["total_earned"] = round(data.get("total_earned", 0.0) + commission, 2)
    _save(chat_id, data)
    return chat_id, commission


def request_payout(chat_id, method, address):
    """Request payout. Returns request dict or error dict."""
    chat_id = str(chat_id)
    data = _load(chat_id)
    if not data:
        return {"error": "not_registered"}
    pending = round(data.get("total_earned", 0) - data.get("total_paid", 0), 2)
    if pending < 10:
        return {"error": "minimum", "pending": pending}
    req = {
        "time": time.time(),
        "amount": pending,
        "method": method,
        "address": address,
        "status": "pending",
    }
    data.setdefault("payout_requests", []).append(req)
    _save(chat_id, data)
    return req


def mark_paid(chat_id, amount):
    chat_id = str(chat_id)
    data = _load(chat_id)
    if not data:
        return False
    data["total_paid"] = round(data.get("total_paid", 0.0) + float(amount), 2)
    for req in reversed(data.get("payout_requests", [])):
        if req["status"] == "pending":
            req["status"] = "paid"
            break
    _save(chat_id, data)
    return True


def all_affiliates():
    """All affiliates sorted by earnings."""
    if not os.path.isdir(_DIR):
        return []
    result = []
    for fname in os.listdir(_DIR):
        if fname.endswith(".json") and not fname.startswith("_"):
            d = _load(fname[:-5])
            if d:
                result.append(d)
    return sorted(result, key=lambda x: x.get("total_earned", 0), reverse=True)

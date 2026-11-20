"""An instrument halt must catch the symbol in any of its spellings."""
import os, sys
import tempfile
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp())
os.environ.setdefault("ALLOW_PLAINTEXT_DEV_STORAGE", "true")
os.environ.setdefault("APP_ENV", "dev")
os.environ.setdefault("ALLOW_LOCAL_BACKEND_DEV", "true")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from apex.platform import emergency as EM

assert EM._norm_sym("EUR_USD") == EM._norm_sym("eur/usd") == EM._norm_sym("EURUSD") == "EURUSD"
src = open(os.path.join(os.path.dirname(EM.__file__), "emergency.py")).read()
assert "_norm_sym(symbol) in" in src, "check() must compare normalised symbols"
uls = open(os.path.join(os.path.dirname(EM.__file__), "..", "user_loop.py")).read()
fn = uls[uls.index("def force_trade"):]
assert "_is_live_cfg(cfg) or not" in fn, "snapshot must treat a live cfg as live"
assert "live_risk_refusal(units, sym" in fn, "force_trade must hold the live 1% cap"
print("emergency symbol forms ok")

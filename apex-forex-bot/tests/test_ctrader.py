"""cTrader connector tests — offline parts only (symbol mapping, OAuth state
signing, broker selection). The protobuf socket layer needs a live cTrader app
and is validated separately against a real demo account.

Run: python tests/test_ctrader.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["PAPER_TRADING"] = "true"
os.environ["TELEGRAM_BOT_TOKEN"] = "test:secret-token"

from apex.brokers import ctrader  # noqa: E402
from apex import ctrader_oauth as oauth  # noqa: E402
from apex import user_loop  # noqa: E402


def check(label, condition, detail=""):
    status = "✅" if condition else "❌"
    print(f"  {status} {label}")
    if not condition:
        print(f"      got: {detail}")
        check.failed += 1


check.failed = 0

print("\n🧪 cTRADER TESTS\n")

print("1. Symbol mapping (Underscore/slash → cTrader)")
check("EUR_USD → EURUSD", ctrader._to_ct_symbol("EUR_USD") == "EURUSD")
check("EUR/USD → EURUSD", ctrader._to_ct_symbol("EUR/USD") == "EURUSD")
check("lowercase usd_jpy → USDJPY", ctrader._to_ct_symbol("usd_jpy") == "USDJPY")

print("\n2. Price digits / scale")
check("JPY pair has 3 digits", ctrader.CtraderBroker._digits("USD_JPY") == 3)
check("EUR_USD has 5 digits", ctrader.CtraderBroker._digits("EUR_USD") == 5)
check("FX scale is 1e5", ctrader.CtraderBroker._scale("EUR_USD") == 100000.0)

print("\n3. OAuth state signing")
st = oauth.make_state("987654")
check("roundtrip recovers chat id", oauth.parse_state(st) == "987654", oauth.parse_state(st))
check("tampered state rejected", oauth.parse_state(st[:-2] + "00") is None)
check("garbage state rejected", oauth.parse_state("xxxxx") is None)
check("empty state rejected", oauth.parse_state("") is None)

print("\n4. OAuth callback guards")
s1, _ = oauth.handle_callback({"error": ["access_denied"]})
check("error param → 400", s1 == 400, s1)
s2, _ = oauth.handle_callback({"code": ["abc"], "state": ["forged"]})
check("forged state → 400", s2 == 400, s2)
s3, _ = oauth.handle_callback({})
check("missing code → 400", s3 == 400, s3)

print("\n5. Broker selection in user_loop")
b_ct, _ = user_loop._make_broker({
    "ctrader_access_token": "tok", "ctrader_account_id": 12345,
    "ctrader_env": "demo", "paper": True})
check("cTrader creds → CtraderBroker", b_ct.__class__.__name__ == "CtraderBroker",
      b_ct.__class__.__name__)

b_yh, _ = user_loop._make_broker({"paper": True})
check("paper + no broker → yahoo module",
      getattr(b_yh, "__name__", "") .endswith("yahoo"), getattr(b_yh, "__name__", b_yh))

print("\n6. Broker label")
check("ctrader label",
      user_loop._broker_label({"ctrader_access_token": "t", "ctrader_account_id": 1},
                              type("C", (), {"CTRADER_ENV": "live"})) == "cTrader (live)")

print("\n" + "=" * 50)
if check.failed:
    print(f"❌ {check.failed} CHECK(S) FAILED")
    sys.exit(1)
print("✅ ALL cTRADER TESTS PASSED")

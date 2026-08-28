"""The account's money is ONE number, and it is cTrader's.

This file exists because the platform had three implementations of the same
figure and they disagreed with each other and with the client's own terminal.

  * the trading loop set `floatingPnl` to the FOCUSED position's P&L alone;
  * the full Mini App payload re-derived it with a candle read per position;
  * the poll route summed what it could price and counted the rest as zero.

Telegram read the first, so a client holding two trades was shown one trade's
result under an account-wide label. The Mini App alternated between the second
and the third depending on which one answered last. None of them matched
cTrader, because all three multiplied a mid price locally while cTrader's own
figure is net of swap and commission — a gap that grows every day a position
is held.

Worse, `dash["positions"]` was never written at all. Five readers took the
resulting empty list at face value: the SSE stream published it and blanked the
Mini App's position panel between polls, the risk screen showed no exposure,
the symbol chart drew no entry lines, and the copilot answered "you have no
open positions" — labelled FACT — to a client holding two.

So the rules asserted here are:

  1. the loop publishes the positions it read, priced, instead of discarding
     them;
  2. the floating figure covers every position, not the focused one;
  3. it comes from cTrader's own net unrealised P&L, which is the only figure
     that can match the client's terminal;
  4. a position that could not be priced is reported as unpriced — never
     counted as zero, because a confident wrong equity is worse than an
     admittedly incomplete one;
  5. no screen prints an estimated or partial figure as if it were the
     account's own.

Run: python tests/test_equity_truth.py
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

failures = []


def check(name, cond, detail=""):
    print(f"  OK   {name}" if cond else f"  FAIL {name} {detail}")
    if not cond:
        failures.append(name)


def src(*parts):
    return open(os.path.join(ROOT, *parts), encoding="utf-8").read()


LOOP = src("apex", "user_loop.py")
BOT = src("apex", "bot.py")
CT = src("apex", "brokers", "ctrader.py")
STREAM = src("apex", "stream.py")
TG = src("apex", "telegram.py")
HTML = src("apex", "static", "terminal.html")

print("\n1. cTrader's own unrealised P&L is available to read")
check("the broker exposes it", "def get_positions_pnl" in CT)
check("...via the dedicated request, not a reconciliation guess",
      "ProtoOAGetPositionUnrealizedPnLReq" in CT
      and "ProtoOAGetPositionUnrealizedPnLRes" in CT)
check("...and it is imported",
      "ProtoOAGetPositionUnrealizedPnLReq, ProtoOAGetPositionUnrealizedPnLRes" in CT)
check("the NET figure is used, not the gross",
      "netUnrealizedPnL" in CT and "row.grossUnrealizedPnL" not in CT,
      "gross omits swap and commission, which is exactly the gap that made "
      "our number disagree with the client's terminal")
check("money is scaled by the response's own moneyDigits",
      re.search(r'digits = getattr\(res, "moneyDigits", 2\)', CT) is not None,
      "an unscaled integer moves a client's equity by two decimal places")
check("a broker failure raises rather than reporting a flat account",
      "return {}" in CT.split("def get_positions_pnl")[1].split("def ")[0]
      and "PAPER_TRADING" in CT.split("def get_positions_pnl")[1].split("def ")[0],
      "the only empty dict returned must be the paper-trading one")

print("\n2. The loop publishes the positions it read")
check("a positions list reaches the dash", 'dash["positions"] = ' in LOOP,
      "five readers consumed dash['positions'] while nothing ever wrote it")
check("...built from the broker's own read", "_pos_rows = list(all_positions or [])" in LOOP)
check("...falling back to the focused position when that read failed",
      "if not _pos_rows and open_pos:" in LOOP)

print("\n3. Floating covers the whole account, from cTrader")
check("the loop asks the broker for it", "broker.get_positions_pnl()" in LOOP)
check("the figure is a sum over every position, not one of them",
      "_float += float(_net)" in LOOP)
check("equity is balance plus that sum",
      'dash["equityLive"] = round(float(paper_balance or 0) + _float, 2)' in LOOP)
check("the focused-only version is gone",
      '_float = float((dash["openPosition"] or {}).get("pnlUsd") or 0.0)' not in LOOP,
      "this line was the whole bug: one position's P&L under an account label")

print("\n4. An unpriced position is unpriced, never zero")
check("they are counted", "_unpriced += 1" in LOOP)
check("...and the position reports no P&L rather than 0",
      '_row["pnlUsd"] = None' in LOOP)
check("...and the count is published", 'dash["unpricedPositions"] = _unpriced' in LOOP)
check("the equity figure carries its own provenance",
      'dash["equitySource"]' in LOOP)
check("...with a distinct value for an incomplete one",
      '"partial" if _unpriced' in LOOP,
      "a floor presented as an equity is a confident wrong number")
check("a stale P&L cannot survive into an estimate",
      '_row.pop("pnlUsd", None)' in LOOP,
      "_price_open_position returns its input untouched when it cannot price")

print("\n5. No route computes a second version of the figure")
# The two Mini App money routes must READ the loop's number, not re-derive it.
_data = BOT[BOT.index('"/api/app/data"'):BOT.index('"/api/app/history"')]
_tick = BOT[BOT.index("/api/app/tick"):BOT.index("# ── Mini App: history")]
for label, block in (("the full payload", _data), ("the poll", _tick)):
    check(f"{label} reads floatingPnl from the loop",
          'udash.get("floatingPnl")' in block)
    check(f"{label} publishes the provenance",
          '"equitySource": udash.get("equitySource")' in block
          or '"equitySource": equity_source' in block)
check("the full payload no longer re-prices other positions itself",
      "br.get_all_positions() if not u.get" not in _data,
      "that was one candle read per position and a third disagreeing answer")
check("equity is composed from the balance the same response reports",
      "round(float(balance_live) + floating, 2)" in _data,
      "an equity that does not equal the balance printed beside it plus the "
      "floating printed beside that reads as broken even when both are right")
check("the poll prefers the broker's per-position figure",
      '_brk.get("pnlSource") == "broker"' in _tick)

print("\n6. Every screen that shows the number also shows what it is worth")
check("the stream carries the provenance",
      '"equitySource": dash.get("equitySource")' in STREAM)
check("...and the position ids the client's own terminal uses",
      '"positionId": p.get("positionId")' in STREAM)
check("Telegram says when the figure is only an estimate",
      "estimated — cTrader is the exact figure" in TG)
check("...and when it is incomplete", "incomplete —" in TG)
check("...and it reports equity, not just floating",
      "Equity:" in TG and "balance + floating, as cTrader computes it" in TG)

print("\n7. The Mini App builds that line once, for all three paths")
check("there is a single balance-line renderer", "function balanceLine(d)" in HTML)
check("the full refresh uses it", "Q('balSub').innerHTML=balanceLine(d);" in HTML)
check("the poll uses it", "Q('balSub').innerHTML=balanceLine(t);" in HTML)
check("the stream uses it", "Q('balSub').innerHTML=balanceLine(ev);" in HTML)
check("no path builds the line inline any more",
      HTML.count("'Balance $'+") == 1,
      "the one occurrence must be inside balanceLine itself")
check("the estimate is labelled on screen",
      "estimated, cTrader is exact" in HTML)
check("an incomplete figure is labelled on screen",
      "position(s) unpriced" in HTML)
check("floating shows even when no position is focused",
      "(d.positions && d.positions.length) || d.position || fl !== 0" in HTML,
      "gating on the focused position hid the figure from a client holding a "
      "trade the platform was not currently watching")

print("\n8. Nothing here can move money or take the loop down")
_blk = LOOP[LOOP.index('dash["positions"] = ') - 4000:LOOP.index('dash["unpricedPositions"]')]
check("the publish block places no order",
      not any(x in _blk for x in ("place_order", "force_close", "close_position",
                                  "amend_sltp")))
check("a broker failure is caught, not raised into the tick",
      "except Exception as e:" in _blk and "unrealised P&L read" in _blk)

print("\n9. The money scaling actually works (executed, not grepped)")
# moneyDigits is the one place here that can be wrong by a factor of 100, and
# no string assertion can catch that. Drive the real method with a stand-in
# response instead.
import types as _t

class _Row:
    def __init__(self, pid, net):
        self.positionId, self.netUnrealizedPnL = pid, net
        self.grossUnrealizedPnL = net + 999   # must never be the one picked

class _Res:
    def __init__(self, rows, digits):
        self.positionUnrealizedPnL, self.moneyDigits = rows, digits

try:
    from apex.brokers import ctrader as _ct

    # The cTrader SDK is not installed in every environment (its import in
    # ctrader.py is guarded for exactly that reason). The arithmetic under test
    # is OURS — the moneyDigits scaling and the net-vs-gross choice — so a
    # stand-in request object keeps it genuinely executed rather than skipped
    # wherever the wheel happens to be absent. _rpc is overridden below, so
    # nothing is ever sent.
    if not getattr(_ct, "_SDK_OK", False):
        class _StubReq:
            ctidTraderAccountId = 0
        _ct.ProtoOAGetPositionUnrealizedPnLReq = _StubReq
        _ct.ProtoOAGetPositionUnrealizedPnLRes = object

    class _Fake(_ct.CtraderBroker):
        def __init__(self, res):
            self._c = _t.SimpleNamespace(PAPER_TRADING=False)
            self._res = res
        def _ctid(self):
            return 1
        def _rpc(self, req, res_cls, timeout=15):
            return self._res

    # Cents, the usual case for a USD account: 12345 -> $123.45
    got = _Fake(_Res([_Row(7, 12345), _Row(8, -2500)], 2)).get_positions_pnl()
    check("cents scale to dollars", got == {"7": 123.45, "8": -25.0}, str(got))
    check("...so the account total is the sum of them",
          round(sum(got.values()), 2) == 98.45, str(sum(got.values())))

    # A different moneyDigits must move the point, not be ignored.
    got3 = _Fake(_Res([_Row(7, 12345)], 3)).get_positions_pnl()
    check("moneyDigits is honoured, not assumed", got3 == {"7": 12.345}, str(got3))

    # Gross is deliberately larger; picking it would silently overstate P&L.
    check("the gross figure is never returned",
          all(abs(v) < 900 for v in got.values()), str(got))

    # A paper account asks the broker nothing at all.
    _paper = _Fake(_Res([_Row(7, 12345)], 2))
    _paper._c = _t.SimpleNamespace(PAPER_TRADING=True)
    check("a paper account reads no live P&L", _paper.get_positions_pnl() == {})
except Exception as e:
    check("the P&L reader runs", False, f"{type(e).__name__}: {e}")

print("\n" + "=" * 50)
if failures:
    print(f"FAILED {len(failures)}: {', '.join(failures[:8])}")
    sys.exit(1)
print("ALL EQUITY-TRUTH CHECKS PASSED - one number, and it is the broker's.")

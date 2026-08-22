"""Per-user trading loop manager — each client gets their own isolated loop."""
import os
import threading
import time
from datetime import datetime
from apex import user_store, indicators, ai, strategies, forex, news, market
from apex import access, sentinel, institutional, cot, ledger
from apex import automation, gates, ownership, news_alerts
from apex import strategy_api
# Registering the shipped modules is what makes strategy_api.get() return
# anything. Without this the registry is empty, every lookup misses, and the
# loop silently falls back to calling the engine directly -- working, but with
# no §14 provenance on any trade.
strategy_api.load_builtins()
from apex import config as cfg_mod
# Imported under an alias: `ev` is already a local variable inside _loop (the
# news-window event), and a module-level `ev` would be shadowed for the whole
# function scope.
from apex import ev as ev_engine
from apex import shadow
from apex.brokers.ctrader import CtraderBroker as _CtraderBroker


_loops = {}   # user_id → {"thread": Thread, "running": bool, "dash": dict}
_lock  = threading.Lock()

# The candle-close fallback used when a broker-side close is discovered with no
# get_closed_deal_pnl() record (restart gap, multi-position sweep) prices the
# exit off broker.get_candles(symbol, ...) — if that ever returns another
# instrument's candle (bad cache key, symbol-ID collision), entryPrice and
# exit_price belong to two different assets and forex.pnl_usd() reports a
# nonsense PnL. A same-symbol close during a single bot-downtime gap never
# legitimately moves more than this — treat anything past it as an
# untrustworthy estimate rather than a fact worth alerting on.
_MAX_PLAUSIBLE_GAP_MOVE = 0.5  # 50% — generous even for a bad gap


def _plausible_exit_price(entry_price, exit_price):
    """True if exit_price could plausibly be the SAME symbol's price as
    entry_price (guards the candle-close PnL fallback against fetching the
    wrong instrument)."""
    try:
        entry_price = float(entry_price)
        exit_price = float(exit_price)
    except (TypeError, ValueError):
        return False
    if entry_price <= 0 or exit_price <= 0:
        return False
    return abs(exit_price - entry_price) / entry_price <= _MAX_PLAUSIBLE_GAP_MOVE



def _phantom_levels(price, side, ind, symbol):
    """Stop and target a refused entry would have been given.

    Mirrors the live SL/TP rule rather than sharing it: that block runs inside
    `if entry_ok`, which by definition never executes for a blocked trade.
    Approximate is fine here — the phantom only has to answer "target or stop
    first", and both branches use the same distances the real order would.
    """
    pip = forex.pip_size(symbol, price)
    atr_v = 0.0
    try:
        atr_v = float((ind or {}).get("atr") or 0)
    except (TypeError, ValueError):
        atr_v = 0.0
    if getattr(cfg_mod, "ATR_STOPS", False) and atr_v > 0:
        sl_dist, tp_dist = 2.5 * atr_v, 5.0 * atr_v
        floor_abs = 20.0 * pip
        if sl_dist < floor_abs:
            sl_dist, tp_dist = floor_abs, 2.0 * floor_abs
    else:
        sl_dist = cfg_mod.STOP_LOSS_PIPS * pip
        tp_dist = cfg_mod.TAKE_PROFIT_PIPS * pip
        if tp_dist < sl_dist:
            tp_dist = 2.0 * sl_dist
    if side == "BUY":
        return round(price - sl_dist, 6), round(price + tp_dist, 6)
    return round(price + sl_dist, 6), round(price - tp_dist, 6)


def _currency_legs(symbol):
    """The ISO currency codes a symbol is exposed to, for the news calendar.

    Handles both spellings the bot uses: EUR_USD (manual /symbol) and EURUSD
    (every Auto-Pilot symbol). Metals map to their quote currency plus the
    metal code, so XAUUSD is still guarded against USD releases. Anything that
    is not a recognisable 6-character pair returns no legs rather than a
    garbage one, leaving the guard fail-open as designed.
    """
    s = (symbol or "").upper().replace("_", "").replace("/", "").replace("-", "")
    if len(s) == 6 and s.isalpha():
        return [s[:3], s[3:]]
    return []


def _nrm(x):
    """Broker-agnostic symbol key (EUR_USD / EUR/USD / eurusd → EURUSD).
    Module-level so the startup recovery can key off it too — it used to be
    re-defined inside every tick of the loop, below the point where recovery
    runs."""
    return (x or "").upper().replace("_", "").replace("/", "").replace("-", "")


# Restart recovery has exactly three outcomes, and which one is chosen is the
# most safety-critical decision the process makes at startup. It lived inline
# inside a two-thousand-line loop, where the only way to check it was to read
# it. Extracted verbatim so it can be EXERCISED — the loop below calls this
# and behaves exactly as before.
ADOPT = "ADOPT"                    # broker says the position is still open
KEEP_TRACKED = "KEEP_TRACKED"      # broker never answered — do not guess
CONFIRMED_CLOSED = "CONFIRMED_CLOSED"   # broker answered, definitively flat


# Leverage is a property of the INSTRUMENT, not of the build. Regulated
# brokers cap crypto CFDs around 1:2–1:5 while FX majors get 1:30, so one
# constant per process cannot describe an account that now holds both.
#
# This mattered more than it looks. `calc_units` uses leverage only for the
# margin cap — so an assumed 30x on a 5x instrument does not merely overstate
# capacity, it makes the cap check a different question than the one the
# broker will ask. The position that "uses 8.7% of the account" at 30x needs
# 52% of it at 5x, and the guard that exists to prevent exactly that reports
# the wrong number without failing.
_LEV_CACHE = {}
_LEV_STATIC_CRYPTO = 5.0
_LEV_STATIC_FX = 30.0


def leverage_for_symbol(broker, cfg, symbol):
    """The broker's real leverage for `symbol`, cached, with a per-INSTRUMENT
    fallback rather than a per-build one.

    An explicit client setting always wins — `cfg.LEVERAGE` is already the
    resolved value when the user set one, and second-guessing it here would
    silently override a deliberate choice.
    """
    sym = _nrm(symbol)
    if not sym:
        return float(getattr(cfg, "LEVERAGE", _LEV_STATIC_FX))
    if sym in _LEV_CACHE:
        return _LEV_CACHE[sym]
    static = _LEV_STATIC_CRYPTO if forex.is_crypto(sym) else _LEV_STATIC_FX
    lev = static
    try:
        if broker is not None and hasattr(broker, "leverage_for"):
            got = float(broker.leverage_for(symbol) or 0)
            if got > 0:
                lev = got
    except Exception as e:
        # Best-effort refinement, never a hard dependency — but the fallback
        # is now the right ORDER OF MAGNITUDE for the instrument, which is the
        # part that was wrong.
        print(f"[UserLoop] leverage_for({symbol}) failed, using {static}x: {e}")
    _LEV_CACHE[sym] = lev
    return lev


def flash_spike_pct_for(cfg, symbol):
    """Violent-candle threshold, per instrument.

    The FX default is 1.2%. Ordinary BTC candles exceed that routinely, so on
    a forex build the flash-spike guard would refuse crypto entries as a
    matter of course — the bot would look like it simply never traded crypto,
    with the reason buried in a skip line.
    """
    base = float(getattr(cfg, "FLASH_SPIKE_PCT", 0.012))
    if forex.is_crypto(symbol) and base <= 0.02:
        return 0.05
    return base


def recovery_verdict(live_position, got_answer):
    """What a restart may conclude about a position it used to hold.

    The distinction that matters is between `not live_position` and "the
    broker told us there is no position". They are not the same fact, and
    treating them as one is how a transient hiccup at exactly the wrong moment
    gets read as "closed" — abandoning a position that is still open and from
    then on unmanaged.

    `got_answer` is deliberately "did any attempt succeed", not "did any
    attempt fail". With the latter, failing twice and then getting a clean
    definitive answer on the third try still counted as unreachable, because
    the flag stayed set from the earlier failures.
    """
    if live_position:
        return ADOPT
    if not got_answer:
        return KEEP_TRACKED
    return CONFIRMED_CLOSED


def _risk_from_snapshot(entry_price, initial_stop):
    """abs(entry - stop) from a persisted snapshot, or None if either value is
    missing/unusable. The snapshot is external state (Redis/disk) that can be
    partially written or corrupted, so this must never raise into a caller
    that isn't itself wrapped (restart recovery runs before any try/except)."""
    try:
        return abs(float(entry_price) - float(initial_stop))
    except (TypeError, ValueError):
        return None


def _position_still_open(broker, pos, focus_symbol, user_id):
    """True when `pos` is still open at the broker despite being absent from
    this tick's read.

    The single-position sync reads only the FOCUSED instrument. Auto-Pilot
    rotates focus between ticks, so a position on the previous instrument
    stops appearing the moment focus moves — and the loop read that absence as
    "the broker closed it". Live proof: USDCAD 54303026 was declared closed at
    netPnl 0.00 six seconds after focus moved to EURUSD, while the position was
    open at the broker the whole time. The invented close booked a losing
    trade, pushed the day's count from 3 to 4, and cleared the snapshot the
    still-open position needs to survive the next restart.

    Asking about the position's OWN symbol is the question that was missing.
    Only called once focus has moved, so it costs one extra broker read per
    rotation, not per tick.

    A failed read means "unknown", and unknown must never be reported as
    still-open: the branch this guards is how a client finds out their trade
    hit its stop, and silence there is worse than a spurious close.
    """
    sym = pos.get("symbol")
    if not sym or _nrm(sym) == _nrm(focus_symbol):
        return False
    try:
        live = broker.get_open_position(sym)
    except Exception as e:
        print(f"[UserLoop:{user_id}] re-check of {sym} failed ({e}) — "
              f"treating it as closed")
        return False
    if not live:
        return False
    # Same instrument is not the same trade: one can close and another open
    # on the pair between ticks. The broker's own id settles it.
    pid, live_pid = pos.get("positionId"), live.get("positionId")
    if pid and live_pid and pid != live_pid:
        return False
    print(f"[UserLoop:{user_id}] {sym} is still open at the broker — focus "
          f"moved to {focus_symbol}, this is not a close")
    return True


def _price_open_position(pos, symbol, price):
    """Attach floating (unrealised) P&L to an open position, in pips and USD.

    bot.py — the single-account loop — has always done this, but the per-user
    loop that actually runs in production never did, and every reader of that
    number defaulted it to zero: Telegram's /status printed `PnL: +$0.00` on a
    position that was $22 down, and the web terminal read `pnlUsd`/`pnlPips`
    that were simply absent. A trade showing exactly $0.00 the whole time it is
    open reads as a broken bot, and it hides the one number the client most
    wants while a position is live.

    Returns the position (a copy, so the broker's dict is never mutated) or
    None. Never raises: this decorates the dashboard and must not be able to
    take the trading loop down.
    """
    if not pos:
        return pos
    try:
        entry = float(pos.get("entryPrice"))
        px = float(price)
    except (TypeError, ValueError):
        return pos
    if not entry or not px:
        return pos
    sym = pos.get("symbol") or symbol
    side = pos.get("side")
    if side not in ("BUY", "SELL"):
        return pos
    out = dict(pos)
    try:
        d = 1 if side == "BUY" else -1
        out["pnlPips"] = round(forex.to_pips((px - entry) * d, sym, px), 1)
        units = pos.get("units") or pos.get("quantity") or 0
        if units:
            out["pnlUsd"] = round(
                forex.pnl_usd(side, entry, px, units, sym), 2)
    except Exception as e:
        print(f"[UserLoop] floating P&L for {sym} failed: {e}")
    return out


# Tick cadence. This was hardcoded to 300 while config computed
# LOOP_INTERVAL_MS (60s in scalp mode) and used it only for DISPLAY —
# telegram.py and logger.py told the client "Interval: 1m" while the loop ran
# every five minutes. On a 1m strategy that decides entries up to five bars
# late, and it biases WHICH setups get seen: a level touch that lasts one bar
# is usually missed, while price stalling at a level across several bars is
# nearly always caught — and stalling at a level is the failed-rejection case.
# Sampling every fifth bar systematically over-represents the worse half.
_LOOP_INTERVAL = max(30, int(getattr(cfg_mod, "LOOP_INTERVAL_MS", 300_000) / 1000))
# Re-pick the focus symbol on a TIME cadence, not a tick count. Tick-based
# meant shortening the interval silently multiplied broker calls; at 300s x 3
# forex re-scanned every 15 minutes, which on 1m bars is most of the day blind.
_SCAN_INTERVAL_S = int(os.getenv("SCAN_INTERVAL_S") or 180)
_HEARTBEAT_TICKS = 30  # heartbeat every 30 ticks (~2.5 hours swing)
_AI_ERROR_THROTTLE = 30  # alert AI failure at most once per 30 ticks
_SKIP_WARN_THROTTLE = 36  # "don't trade now" warnings — only every ~3h (was 30m)
# Per (symbol, reason) cooldown for refusal alerts. Distinct reasons are never
# suppressed by each other — only the identical one repeating tick after tick.
_SKIP_ALERT_COOLDOWN_S = 3 * 3600
_LOSS_COOLDOWN_MIN = 15   # pause after a loss — avoid revenge trades in the same move
_CLOSE_COOLDOWN_MIN = 10  # pause after ANY close — prevent open/close churn


_DEDUPE_WINDOW_S = 900  # 15 min — two paths racing on one close land seconds apart


def _mode_of(user_id):
    """"demo", "live", "simulation", or None when it cannot be known.

    None rather than a guess: a trade filed under the wrong account mode is
    worse than one filed under none, because the report looks complete while
    being wrong.

    This used to be `"demo" if paper else "live"`, which read the WRONG AXIS.
    `paper` distinguishes simulated fills from broker-executed ones; it says
    nothing about whether the broker account is real money. Account 47765456
    runs paper=false against a cTrader DEMO account, so every trade it closed
    was journalled "live" — and the history screen prints this field verbatim,
    which would show a client demo trades labelled LIVE.

    Deliberately does NOT call the broker: this runs inside the journal writer
    on every close, and a network call there could fail a write that must not
    fail. The stored env is the right axis, which was the actual defect; the
    Mini App badge asks the broker itself (see apex/account_mode.py).
    """
    try:
        from apex import account_mode
        u = user_store.load(user_id) or {}
        mode, _src = account_mode.resolve(u, allow_broker=False)
        return {account_mode.LIVE: "live",
                account_mode.DEMO: "demo",
                account_mode.SIMULATION: "simulation"}.get(mode)
    except Exception as e:
        print(f"[UserLoop:{user_id}] could not read account mode: {e}")
        return None


def _already_journaled(journal, row):
    """True if this exact close is already in the journal.

    Two independent paths can journal the same broker-side close: the restart
    recovery (which fires when the persisted snapshot says open but the broker
    says closed) and the in-loop detection (prev_pos set, open_pos now None).
    Around a redeploy both run, seconds apart, and the trade was written twice
    — observed live as two BROKER_CLOSE events 14s apart with identical P&L.

    The cost is not just a duplicated row: loss_streak counts each close twice,
    so the "3 consecutive losses" rule cuts risk to a quarter after what were
    really two losses, and the duplicate becomes a second training label for a
    trade that only happened once.

    positionId is the exact key when the broker gave us one, and two DIFFERENT
    ids settle it the other way: those are genuinely different trades.

    Otherwise: same symbol, same entry price, inside a short window. P&L used
    to be part of that key, and that was backwards. The duplicate worth
    catching is the one whose P&L DISAGREES — the second path estimates from a
    balance delta and books $0.00 — so requiring the numbers to match deduped
    only the harmless case and let the wrong one through. Observed live: the
    same EURUSD close journalled twice one second apart, +$2.89 from the
    broker's own fill and $0.00 from the estimate, both kept.

    Two genuinely distinct trades on one pair matching to five decimals on
    entry within fifteen minutes does not happen; that was already the
    argument, and P&L was never carrying it.
    """
    pid = row.get("positionId")
    for old in reversed(journal[-40:]):
        old_pid = old.get("positionId")
        if pid and old_pid:
            if old_pid == pid:
                return True
            continue          # different positions — not a duplicate
        if (old.get("symbol") == row.get("symbol")
                and old.get("entry") is not None
                and old.get("entry") == row.get("entry")):
            try:
                t_old = datetime.strptime(old["time"], "%Y-%m-%d %H:%M:%S")
                t_new = datetime.strptime(row["time"], "%Y-%m-%d %H:%M:%S")
                if abs((t_new - t_old).total_seconds()) <= _DEDUPE_WINDOW_S:
                    return True
            except (KeyError, TypeError, ValueError):
                # No usable timestamps — treat an otherwise exact match as a
                # duplicate rather than risk double-counting a loss.
                return True
    return False


# What was true when we DECIDED to enter. These keys live only in this
# process (and in the persisted open-position snapshot) — the broker knows
# nothing about them, so every live position read hands back a dict without
# them. See _reattach_entry_meta.
_ENTRY_META_KEYS = (
    "entryConfidence", "entryRegime", "entryAtr", "entrySlPips",
    "entryTpPips", "entrySide", "entryProbability", "entryEvR",
    "entrySpreadPips", "openedAt",
    # §14 reproducibility: which strategy, at which version, opened this.
    # Carried on the position so it is still known at CLOSE time, hours later
    # and possibly after a restart or an Auto-Pilot rotation to another mode.
    "entryStrategyId", "entryStrategyVersion",
    # Whether "this trade can no longer lose" has already been announced.
    # Without this the flag dies with the position dict on the next broker
    # re-read and the message fires again on every tick once the stop is
    # past entry — which is the exact repetition it exists to stop.
    "breakevenAnnounced",
)


def _strategy_label(key):
    """Display name for a strategy, from the registry.

    Reading this out of ai.STRATEGY_MODES defaulted to mean_reversion
    for anything without an ai.py engine, so /status reported the wrong
    method for every strategy added after V1 -- while the trade alerts,
    which come from the module itself, named the right one. Two answers
    to "what is it trading" in the same conversation.
    """
    try:
        from apex import telegram as _tg
        return _tg.friendly_strategy(key)[0]
    except Exception:
        pass
    try:
        return ai.STRATEGY_MODES[key]["label"]
    except Exception:
        return str(key)


def _entry_meta(pos):
    """Extract the decision snapshot from a position dict."""
    return {k: pos[k] for k in _ENTRY_META_KEYS
            if pos and pos.get(k) is not None}


def _reattach_entry_meta(pos, meta):
    """Put the decision snapshot back onto a freshly broker-read position.

    In LIVE mode every tick replaces the tracked position with
    `broker.get_open_position(symbol)`. That dict is the broker's truth about
    price/size/stop — and it carries none of the entry* fields we recorded
    when the trade was opened. So the snapshot written at entry survived
    exactly one tick, and by the time the position closed it was gone:
    _log_trade wrote `confidence: None`, ev.labelled_count() didn't count the
    row, and evCalibration sat at 1/30 no matter how many trades closed.

    entrySpreadPips is in the same set, which is why the spread half of
    realised cost read $0 on every live close.

    The broker's own values always win — this only fills in what it cannot
    know.
    """
    if not pos or not meta:
        return pos
    for k, v in meta.items():
        if pos.get(k) is None:
            pos[k] = v
    return pos


def _profit_too_small_to_take(pos, price, symbol, initial_risk, user_id=""):
    """True when a strategy's discretionary exit would cut a winner short.

    This is the single biggest money-loser found in the live account. A week
    of real trades, converted to pips:

        wins   +0.6, +1.7                    (mean 1.15 pips)
        losses -0.7, -2.4, -9.3, -10.8       (mean 5.8 pips)

    SL was 15 pips and TP was 30 — 2:1 on paper. The realised ratio was 1:5
    AGAINST, because losers ran to the full stop while winners were closed by
    mean_reversion's "price overshot past mean" rule the moment price touched
    the Bollinger midline, typically 1 pip in. At 1:5 you need an 83% win rate
    to break even. The account did 33%.

    Worse, that rule fires on band position alone and never looks at P&L: one
    live trade was SOLD at 0.70581 and "took profit" at 0.70583 — price had
    moved AGAINST the position and it was still booked as a profitable exit.

    So: a discretionary profit-take must capture at least MIN_EXIT_R of the
    risk the trade put up, and must clear its own round-trip cost. Below that
    it is not profit, it is churn that pays the spread.

    The rule is deliberately ASYMMETRIC — it only ever blocks exits that are
    in profit. A strategy closing an UNDERWATER trade is saying its thesis
    broke, and holding that to a full stop would turn a small loss into a big
    one. Those exits always pass.

    MIN_EXIT_R defaults to 1.0, which pairs with the breakeven trail: below 1R
    the stop has not moved to breakeven yet, so there is nothing to protect and
    no reason to take crumbs; at or above 1R the downside is already covered
    and a discretionary exit is free.
    """
    try:
        entry = float(pos.get("entryPrice"))
        side = pos.get("side")
        if not entry or side not in ("BUY", "SELL"):
            return False
        px = float(price)
    except (TypeError, ValueError):
        return False

    move = (px - entry) if side == "BUY" else (entry - px)
    if move <= 0:
        return False        # losing or flat — thesis broke, let it out

    min_r = float(os.getenv("MIN_EXIT_R") or getattr(cfg_mod, "MIN_EXIT_R", 1.0))
    if min_r <= 0:
        return False        # feature off

    # Round-trip cost floor: the exit must at minimum pay for itself. Uses the
    # spread measured at entry (the only spread we know for this trade) and
    # doubles it for the return leg.
    cost_move = 0.0
    try:
        sp = float(pos.get("entrySpreadPips") or 0.0)
        if sp > 0:
            cost_move = forex.from_pips(sp * 2, symbol, px)
    except Exception:
        cost_move = 0.0

    floor = cost_move
    if initial_risk:
        try:
            floor = max(floor, float(initial_risk) * min_r)
        except (TypeError, ValueError):
            pass

    # Compare in pips, not raw price. 15 pips of AUDUSD is 0.0015 one way and
    # 0.0014999999999999 the other depending on which subtraction produced it,
    # and a trade sitting exactly on the threshold must not be decided by the
    # last bit of a float. A twentieth of a pip is far below any real spread.
    move_pips = forex.to_pips(move, symbol, px)
    floor_pips = forex.to_pips(floor, symbol, px)
    if move_pips >= floor_pips - 0.05:
        return False

    if user_id:
        print(f"[UserLoop:{user_id}] held {symbol}: strategy wanted out at "
              f"{move_pips:.1f} pips, needs {floor_pips:.1f} "
              f"({min_r}R + cost) — not cutting the winner short")
    return True


def _ride_instead_of_close(broker, cfg, pos, symbol, price, initial_risk,
                           ind=None, user_id=""):
    """Hand a strongly-running winner to the trailing stop instead of closing it.

    _profit_too_small_to_take stops the bot cutting winners short. It does not
    make the bot let winners RUN — nothing did. A live XAUUSD trade closed at
    +$26.88 on a $9 risk (2.99R) with the reason "price overshot past mean",
    while gold kept going. The exit was not premature by the 1R rule, but it
    was still the strategy capping a trend trade at its own midline.

    Mean reversion's exit says "price reached the mean, my thesis is done". In
    a trending instrument that thesis is finished but the MOVE is not. So once
    a trade is running well AND the trend still agrees with it, don't take the
    money off the table — pull the stop up behind price and let the market
    decide when it is over.

    Returns True only when the stop has actually been tightened, i.e. when the
    profit is genuinely protected. Every failure path returns False so the
    caller closes normally: a position we could not protect must never be held
    open on the strength of an intention.
    """
    if not getattr(cfg, "TRAILING_STOP", False):
        return False        # nothing to hand the trade to
    try:
        ride_r = float(os.getenv("RIDE_AT_R") or getattr(cfg_mod, "RIDE_AT_R", 2.0))
        lock = float(os.getenv("RIDE_LOCK") or getattr(cfg_mod, "RIDE_LOCK", 0.6))
    except (TypeError, ValueError):
        return False
    if ride_r <= 0 or not (0 < lock < 1):
        return False

    try:
        entry = float(pos.get("entryPrice"))
        side = pos.get("side")
        px = float(price)
        pid = pos.get("positionId")
        cur_sl = float(pos.get("stopLoss") or pos.get("sl") or 0)
        risk = abs(float(initial_risk or 0))
    except (TypeError, ValueError):
        return False
    if not (pid and entry and cur_sl and risk > 0 and side in ("BUY", "SELL")):
        return False
    if not hasattr(broker, "amend_sltp"):
        return False

    profit = (px - entry) if side == "BUY" else (entry - px)
    if profit < ride_r * risk:
        return False        # not running hard enough to be worth the give-back

    # The trend must still be behind the trade. Riding a reversal is how a 3R
    # winner becomes a scratch — if the move is over, take the money.
    try:
        ema50 = float((ind or {}).get("ema50") or 0)
    except (TypeError, ValueError):
        ema50 = 0
    if ema50:
        aligned = px > ema50 if side == "BUY" else px < ema50
        if not aligned:
            return False

    # Lock most of the open profit. The give-back is bounded and known:
    # (1 - lock) x profit, versus unlimited upside if the move continues.
    keep = entry + profit * lock if side == "BUY" else entry - profit * lock
    improved = (keep - cur_sl) if side == "BUY" else (cur_sl - keep)
    if improved <= 0:
        return False        # trail is already tighter — leave it alone

    try:
        if not broker.amend_sltp(pid, sl=round(keep, 6), instrument=symbol):
            return False    # could not protect it → fall through and close
    except Exception as e:
        print(f"[UserLoop:{user_id}] ride amend failed on {symbol}: {e}")
        return False

    pos["stopLoss"] = round(keep, 6)
    if user_id:
        print(f"[UserLoop:{user_id}] riding {symbol}: {profit / risk:.1f}R and "
              f"trend still aligned — stop moved to {keep:.5f}, locking "
              f"{lock:.0%} of the move instead of closing")
    return True


def _institutional_observations(symbol, ind, regime, spread_pips, now=None):
    """Map what this bot can actually see onto the Institutional State features.

    Five of the spec's nine features have a free source the bot already
    reaches; four do not:

        price_momentum      RSI / EMA / MACD          ✓ (critical)
        volatility          regime vol_ratio          ✓
        liquidity_quality   spread + trading session  ✓
        macro_risk          economic calendar         ✓
        sentiment           fear & greed              ✓
        futures_positioning licensed futures feed     ✗
        cot_bias            CFTC weekly (free, TODO)  ✗
        rate_differential   yield curves              ✗
        central_bank_bias   policy statements         ✗

    The four without a source are simply not emitted. That is the point: they
    show up in `missing`, they pull `data_quality` down to what it honestly is,
    and nothing pretends they are neutral. Adding a COT adapter later means
    appending one observation here — no other code changes.
    """
    out = []

    def add(feature, value, source, conf=1.0, ttl=3600):
        o = institutional.observe(feature, value, source,
                                  confidence=conf, ttl_s=ttl, now=now)
        if o["value"] is not None:
            out.append(o)

    ind = ind or {}

    # ── price_momentum: agreement between RSI, the EMA stack and MACD ──
    try:
        score, n = 0.0, 0
        rsi = float(ind.get("rsi") or 0) or None
        if rsi:
            score += max(-1.0, min(1.0, (rsi - 50.0) / 25.0)); n += 1
        e50, e200 = ind.get("ema50"), ind.get("ema200")
        if e50 and e200:
            score += 1.0 if float(e50) > float(e200) else -1.0; n += 1
        macd, sig = ind.get("macd"), ind.get("macdSignal")
        if macd is not None and sig is not None:
            score += 1.0 if float(macd) > float(sig) else -1.0; n += 1
        if n:
            add("price_momentum", score / n, "indicators", ttl=1800)
    except (TypeError, ValueError):
        pass

    # ── volatility: signed away from "normal", not a raw magnitude ──
    try:
        vr = float((regime or {}).get("vol_ratio") or 0)
        if vr > 0:
            add("volatility", (vr - 1.0), "regime", ttl=1800)
    except (TypeError, ValueError):
        pass

    # ── liquidity_quality: tight spread in a live session is good liquidity ──
    try:
        sp = float(spread_pips or 0)
        if sp > 0:
            tight = max(-1.0, min(1.0, (1.5 - sp) / 1.5))
            sess = market.session()
            in_session = bool(sess) and "closed" not in str(sess).lower()
            add("liquidity_quality", tight if in_session else min(tight, 0.0),
                "spread+session", ttl=900)
    except (TypeError, ValueError, AttributeError):
        pass

    # ── macro_risk: negative near a high-impact release, for either leg ──
    # Only emitted when the calendar actually holds events. Without the
    # has_data() check this published +0.2 ("nothing due") whenever the feed
    # was down — observed live as a 403 from the calendar provider, which would
    # have been recorded as the confident fact that no releases were pending,
    # and would have RAISED data_quality for a source that knew nothing.
    try:
        legs = _currency_legs(symbol)
        if legs and news.has_data():
            hit = news.high_impact_window(legs)
            add("macro_risk", -1.0 if hit else 0.2, "calendar", ttl=1800)
    except Exception:
        pass

    # ── cot_bias: CFTC speculative positioning, the one free institutional
    # source. Weekly and days old by construction, so it carries a reduced
    # confidence rather than being treated as a current reading.
    try:
        legs = _currency_legs(symbol)
        cb = cot.pair_bias(symbol, legs=tuple(legs) if legs else None)
        if cb is not None:
            _age = cot.age_days(symbol, legs=tuple(legs) if legs else None)
            # A reading loses weight as it ages toward the next release.
            _conf = 0.8 if (_age or 0) <= 7 else 0.5
            add("cot_bias", cb, "cftc_cot", conf=_conf, ttl=8 * 86400)
    except Exception:
        pass

    # ── sentiment: fear & greed, rescaled from 0..100 to -1..+1 ──
    try:
        fg = sentiment.fear_greed()
        val = (fg or {}).get("value")
        if val is not None:
            add("sentiment", (float(val) - 50.0) / 50.0, "fear_greed",
                conf=0.6, ttl=6 * 3600)
    except Exception:
        pass

    return out


def _log_trade(user_id, record, pos=None):
    """Persist a closed trade to the per-user tax journal (date, entry, exit,
    fees/spread cost, gross & net PnL) — exportable for tax reporting.

    `pos` is the position being closed. Its `entry*` keys are the DECISION
    snapshot, and they are what turns a closed trade into a labelled training
    example rather than just an accounting row: without the confidence, regime
    and spread that were true AT ENTRY, there is no way to measure afterwards
    how often a given kind of setup actually reached TP before SL, and
    ev.calibrate() has nothing to learn from.

    Callers that no longer hold the position (broker-side reconciliation) may
    omit it; those rows are still written for accounting, just unlabelled and
    skipped by the calibrator.
    """
    # Never let one instrument's entry data be filed under another's. A
    # mismatch here means the caller's `symbol` and its position disagree —
    # the journal row would carry the wrong entry price (and the P&L computed
    # upstream is already suspect), so drop the position-derived fields and say
    # so loudly rather than writing a plausible-looking lie into the record the
    # calibrator and the tax export both read.
    if pos and record.get("symbol") and pos.get("symbol"):
        if _nrm(pos["symbol"]) != _nrm(record["symbol"]):
            print(f"[UserLoop:{user_id}] REFUSED mismatched trade log: record is "
                  f"{record['symbol']} but position is {pos['symbol']} — "
                  f"entry fields dropped")
            pos = None
    src = {**(pos or {}), **record}   # record wins on any overlapping key
    row = {
        "time":      record.get("time"),
        "symbol":    record.get("symbol"),
        "entry":     record.get("entryPrice"),
        "exit":      record.get("price"),
        "grossPnl":  record.get("grossPnl"),
        "costUsd":   record.get("costUsd"),
        "netPnl":    record.get("netPnl"),
        "balance":   record.get("balance"),
        "openedAt":  record.get("openedAt"),
        # Broker's own id for the closed position — the exact dedupe key.
        "positionId": src.get("positionId"),
        # ── decision snapshot (for ev.calibrate) ──
        "confidence":  src.get("entryConfidence"),
        "regime":      src.get("entryRegime"),
        "spreadPips":  src.get("entrySpreadPips"),
        "atr":         src.get("entryAtr"),
        "slPips":      src.get("entrySlPips"),
        "tpPips":      src.get("entryTpPips"),
        "probability": src.get("entryProbability"),
        "evR":         src.get("entryEvR"),
        "side":        src.get("entrySide"),
        # ── §14 reproducibility ──
        # Which strategy, at which version, opened this trade. Without both,
        # comparing strategies on real results is guesswork: the journal knows
        # the outcome but not what produced it, and a strategy whose logic
        # changed last week is indistinguishable from the one that traded.
        "strategyId":      src.get("entryStrategyId"),
        "strategyVersion": src.get("entryStrategyVersion"),
        # Demo and live results mixed together make a report useless exactly
        # when it matters. Recorded per trade because the account can switch:
        # reading the CURRENT mode at report time would relabel every past
        # demo trade as live the moment a client goes live.
        #
        # Read from THIS user's record, not the process-global config. Each
        # client runs their own loop with their own mode, so the global flag
        # would stamp every client's trades with whatever the process default
        # happened to be.
        "mode":            _mode_of(user_id),
    }
    try:
        if _already_journaled(user_store.load_trades(user_id), row):
            print(f"[UserLoop:{user_id}] duplicate close ignored: "
                  f"{row.get('symbol')} netPnl={row.get('netPnl')}")
            return False
        user_store.append_trade(user_id, row)
        return True
    except Exception as e:
        print(f"[UserLoop:{user_id}] trade-log failed: {e}")
        return False


def _persist_open_position(user_id, cfg, pos):
    """Restart-recovery snapshot of the currently open position (or None when
    flat) — see _loop's startup recovery. Positions don't only open/close
    inside the loop's own tick cycle: force_trade/force_close (manual /buy,
    /sell, /close, and the MCP open_trade/force_close tools) open and close
    real positions directly against the broker too, so this is a standalone
    function both the loop and those two call, instead of a loop-only
    closure — a manual trade needs the exact same restart protection as an
    autonomous one."""
    # The Mini App reads positions through a short cache. This is the one place
    # every open and close passes through — loop, manual /buy//close, and the
    # MCP tools alike — so it is where the cache has to be dropped. Without it a
    # client watches a trade close and still sees it listed for seconds
    # afterwards, which is precisely the staleness a terminal must not have.
    try:
        from apex import miniapp_cache
        miniapp_cache.invalidate(user_id)
    except Exception:
        pass
    if getattr(cfg, "PAPER_TRADING", False):
        return
    try:
        user_store.update(user_id, {"open_position_snapshot": pos})
    except Exception as e:
        print(f"[UserLoop:{user_id}] open-position snapshot persist failed: {e}")


def _make_broker(user):
    """Create the per-user broker with isolated config — cTrader exclusively."""
    import types
    from apex import config as _appcfg
    paper = user.get("paper", False)
    ct_token = user.get("ctrader_access_token", "")
    ct_account = user.get("ctrader_account_id", "")
    fake_cfg = types.SimpleNamespace(
        CTRADER_ACCESS_TOKEN  = ct_token,
        CTRADER_REFRESH_TOKEN = user.get("ctrader_refresh_token", ""),
        CTRADER_ACCOUNT_ID    = ct_account,
        CTRADER_ENV           = user.get("ctrader_env", "demo"),
        SYMBOL           = user.get("symbol") or _appcfg.SYMBOL,
        TIMEFRAME        = user.get("timeframe", "5m"),
        CANDLES          = 240,  # M5 history for indicators (H1 gate removed → 720 was overkill)
        PAPER_TRADING    = paper,
        PAPER_BALANCE    = float(user.get("paper_balance", 1000)),
        STOP_LOSS_PIPS   = float(user.get("sl_pips", 20)),
        TAKE_PROFIT_PIPS = float(user.get("tp_pips", 40)),
        # 0 = off (use TAKE_PROFIT_PIPS/ATR as normal). >0 = target this % of
        # the account balance as profit on a full winning trade — TP widens
        # or narrows automatically as the balance (and position size) moves,
        # instead of sitting at a fixed pip count that stops meaning anything
        # once the account has grown or shrunk. See /tptarget.
        TP_TARGET_PCT    = float(user.get("tp_target_pct", 0) or 0),
        RISK_PER_TRADE   = float(user.get("risk", 0.025)),  # 2.5% default (was 1%) — bigger profit per trade, still bounded by the caps below
        # Crypto CFDs are leveraged far lower than FX (retail ~2-5x vs 30x), so
        # the margin cap must assume less leverage or it sizes positions the
        # account can't actually margin.
        LEVERAGE         = float(user.get("leverage", 5 if _appcfg.PRODUCT == "crypto" else 30)),
        MARGIN_CAP       = 0.5,
        # Hard-coded 3.0 here overrode the product config, so the strict scalp
        # ceiling (1.2p) never reached a live account — every entry was admitted
        # up to 3 pips. On a 15-pip stop that is a 24.7% cost-to-stop toll and
        # pushes the break-even win rate from 37.1% to 41.6%.
        MAX_SPREAD_PIPS  = float(user.get(
            "max_spread_pips", getattr(_appcfg, "MAX_SPREAD_PIPS", 3.0))),
        PRODUCT          = _appcfg.PRODUCT,  # so the loop's crypto branches fire
        # Asset-class-aware spread/volatility guards (crypto uses a %-of-price
        # spread limit + higher flash-spike bar; forex keeps the pip limit).
        # Pulled from the global product config so PRODUCT=crypto takes effect.
        MAX_SPREAD_PCT   = getattr(_appcfg, "MAX_SPREAD_PCT", 0),
        FLASH_SPIKE_PCT  = getattr(_appcfg, "FLASH_SPIKE_PCT", 0.012),
        MIN_CONFIDENCE   = int(user.get("min_confidence", 70)),
        STRATEGY         = (user.get("strategy") or "auto").lower(),
        AI_CONFIRM       = bool(user.get("ai_confirm", True)),  # /aiconfirm off = pure rule engine
        ATR_STOPS        = bool(user.get("atr_stops", True)),  # dynamic RR 1:2 by default
        # ── Strategy Builder knobs (all per-user, all enforced in the loop) ──
        HTF_CONFIRM      = bool(user.get("htf", True)),           # multi-timeframe gate — ON by default
        EXIT_MODE        = (user.get("exit_mode") or "fixed").lower(),
        TRAILING_STOP    = bool(user.get("trailing", True)),      # move SL behind price — ON by default
        BREAKEVEN_AT_R   = float(user.get("breakeven_r", 1.0)),   # move SL to entry at +1R
        NEWS_FILTER      = bool(user.get("news_filter", _appcfg.PRODUCT != "crypto")),
        SESSION_FILTER   = list(user.get("session_filter") or []),  # [] = all sessions
        MAX_TRADES_DAY   = int(user.get("max_trades_day", 10)),
        # Caps scaled with RISK_PER_TRADE above (2.5x risk) so the bot still
        # tolerates roughly the same number of consecutive losses per day/from
        # peak before standing aside — not a full linear scale-up, which would
        # make the caps meaningless (matches the product's existing Medium→High
        # risk-tier progression in builder.py).
        MAX_DD_PCT       = float(user.get("max_dd_pct", 25)),
        MAX_DAILY_LOSS_PCT = float(user.get("max_daily_loss_pct", 4)),
        # EV gate. The loop reads its config off THIS object, not the global
        # module, so keys missing here are silently unreachable: without them
        # `getattr(cfg, "EV_GATE_MODE", "shadow")` returned "shadow" forever and
        # EV_GATE_MODE=enforce in the environment did nothing on any account.
        EV_GATE_MODE       = getattr(_appcfg, "EV_GATE_MODE", "shadow"),
        EV_MIN_PROBABILITY = float(user.get(
            "ev_min_probability", getattr(_appcfg, "EV_MIN_PROBABILITY", 0.55))),
        EV_MIN_SAMPLES     = int(getattr(_appcfg, "EV_MIN_SAMPLES", 30)),
        AI_VISION          = bool(getattr(_appcfg, "AI_VISION", False)),
        STRUCTURAL_STOPS   = bool(user.get(
            "structural_stops", getattr(_appcfg, "STRUCTURAL_STOPS", False))),
        STRUCTURAL_MIN_RR  = float(getattr(_appcfg, "STRUCTURAL_MIN_RR", 1.3)),
        # Sentinel. Same warning as the EV block above: absent here means the
        # env var is unreachable from inside the loop.
        SENTINEL_MODE      = getattr(_appcfg, "SENTINEL_MODE", "shadow"),
        SENTINEL_MIN_CONFIDENCE = getattr(_appcfg, "SENTINEL_MIN_CONFIDENCE", None),
        SENTINEL_TTL_S     = int(getattr(_appcfg, "SENTINEL_TTL_S", 0) or 0),
        INSTITUTIONAL_GATE = getattr(_appcfg, "INSTITUTIONAL_GATE", "shadow"),
    )
    broker = _CtraderBroker(fake_cfg)
    # Refine the LEVERAGE guess with the broker's real, per-instrument value
    # (regulated brokers cap crypto/indices far lower than FX majors — see
    # CtraderBroker.leverage_for) — but only when the client didn't set one
    # explicitly and we're actually margining real money against it.
    if not paper and ct_token and ct_account and "leverage" not in user:
        try:
            fake_cfg.LEVERAGE = broker.leverage_for(fake_cfg.SYMBOL)
        except Exception as e:
            print(f"[UserLoop] leverage_for failed, keeping default {fake_cfg.LEVERAGE}: {e}")
    return broker, fake_cfg


def _broker_label(user, cfg):
    if user.get("ctrader_access_token") and user.get("ctrader_account_id"):
        return f"cTrader ({getattr(cfg, 'CTRADER_ENV', 'demo')})"
    if getattr(cfg, 'PAPER_TRADING', False):
        return "Yahoo (paper data)"
    return "cTrader (not linked)"


def _looks_like_auth_error(msg: str) -> bool:
    """Broker errors that a token refresh + reconnect can heal (expired token,
    dropped/unroutable connection) vs. plain data hiccups."""
    m = (msg or "").lower()
    return any(k in m for k in (
        "auth", "token", "route", "not_authenticated", "expired",
        "invalid_request", "access", "unauthor"))


def _refresh_ctrader_token(user_id, cfg) -> bool:
    """Self-heal a cTrader connection: swap the expired access token for a fresh
    one using the stored refresh token, persist it, and drop the pooled
    connection so the next tick re-authenticates. Returns True on success.
    (When cTrader itself is down the refresh call also fails — harmless, we just
    keep retrying.)"""
    try:
        from apex.brokers import ctrader as _ct
        refresh = (getattr(cfg, "CTRADER_REFRESH_TOKEN", "")
                   or user_store.load(user_id).get("ctrader_refresh_token", ""))
        if not refresh:
            return False
        tok = _ct.refresh_access_token(refresh)
        access = tok.get("accessToken") or tok.get("access_token")
        new_refresh = tok.get("refreshToken") or tok.get("refresh_token") or refresh
        if not access:
            return False
        user_store.update(user_id, {"ctrader_access_token": access,
                                    "ctrader_refresh_token": new_refresh})
        cfg.CTRADER_ACCESS_TOKEN = access
        cfg.CTRADER_REFRESH_TOKEN = new_refresh
        try:
            _ct._drop_conn(getattr(cfg, "CTRADER_ENV", "demo"),
                           cfg.CTRADER_ACCOUNT_ID)
        except Exception:
            pass
        print(f"[UserLoop:{user_id}] cTrader token refreshed + reconnected")
        return True
    except Exception as e:
        print(f"[UserLoop:{user_id}] token refresh failed (cTrader may be down): {e}")
        return False


def drop_broker_connection(user) -> bool:
    """Close this account's pooled cTrader socket. True when there was one.

    Lives here rather than in the caller because the import graph is an
    enforced invariant: nothing outside the trading core may reach a broker
    module, so the session watcher asks the core to do it instead of importing
    one itself (tests/test_failure_matrix.py, item 15).

    Safe to call at any time — the pool recreates and re-authenticates on the
    next request, which is exactly how the weekend reopen path repairs itself.
    """
    ctid = (user or {}).get("ctrader_account_id")
    if not ctid:
        return False
    from apex.brokers import ctrader as _ct
    _ct._drop_conn(user.get("ctrader_env", "demo"), ctid)
    return True


def _manage_trailing(broker, cfg, pos, symbol, price, initial_risk=None):
    """Trailing stop + break-even (Strategy Builder exit modes). Moves the SL
    only in the favourable direction — never loosens it, never closes the trade.
    Real-broker only (needs a live positionId + amend_sltp). Returns the new SL
    if it moved, else None. Fail-soft everywhere.

    initial_risk is the trade's ORIGINAL entry-to-stop distance and must stay
    constant for its lifetime. It has to be supplied by the caller because the
    broker only ever reports the CURRENT stop: deriving R from
    abs(entry - cur_sl) — as this did — silently stops measuring risk the
    moment the stop ratchets past entry, because from then on that distance is
    locked profit. The first ratchet past breakeven collapsed R toward zero and
    pinned the trail a few pips behind price, where ordinary spread-sized noise
    closed the trade:

        BUY entry 1.1000, stop 1.0975 (25p risk), price walking up
          1.1030 -> R 25.0p -> stop 1.1005   trail 25p, as intended
          1.1040 -> R  5.0p -> stop 1.1035   trail 5p, inside the noise
          1.1045 -> R 35.0p -> stop 1.1035   trail 10p, and now loose again

    Winners were cut at noise distance while losers still ran the full stop.

    None keeps the old derivation. That is the fallback for a position whose
    opening this process never saw (adopted mid-life after a restart with no
    snapshot, or opened before this change shipped) — those keep today's
    behaviour rather than trailing off a risk figure we cannot know."""
    try:
        if not pos or not price or not hasattr(broker, "amend_sltp"):
            return None
        trailing = bool(getattr(cfg, "TRAILING_STOP", False))
        be_r = float(getattr(cfg, "BREAKEVEN_AT_R", 0) or 0)
        if not (trailing or be_r > 0):
            return None
        pid = pos.get("positionId")
        entry = pos.get("entryPrice")
        cur_sl = pos.get("stopLoss") or pos.get("sl")
        side = pos.get("side")
        if not (pid and entry and cur_sl and side in ("BUY", "SELL")):
            return None
        risk = (abs(float(initial_risk)) if initial_risk
                else abs(float(entry) - float(cur_sl)))
        if risk <= 0:
            return None
        profit = (price - entry) if side == "BUY" else (entry - price)
        if profit <= 0:
            return None
        new_sl = float(cur_sl)
        # Break-even: once profit >= R×risk, lock the stop at entry.
        if be_r > 0 and profit >= be_r * risk:
            new_sl = max(new_sl, entry) if side == "BUY" else min(new_sl, entry)
        # Trailing: keep the stop one risk-unit (1R) behind price, tighten-only.
        if trailing:
            trail = (price - risk) if side == "BUY" else (price + risk)
            new_sl = max(new_sl, trail) if side == "BUY" else min(new_sl, trail)
        improved = (new_sl - cur_sl) if side == "BUY" else (cur_sl - new_sl)
        if improved > risk * 0.05:  # only amend on a meaningful move
            if broker.amend_sltp(pid, sl=new_sl, instrument=symbol):
                return new_sl
    except Exception as e:
        print(f"[Trailing] manage failed: {e}")
    return None


def _loop(user_id, alert_fn, gen=None):
    user = user_store.load(user_id)

    # Self-heal cross-product pollution AT THE SOURCE. When crypto & forex shared
    # one Redis namespace, a user record could keep the OTHER product's symbols
    # (a forex account trading SOLUSD, etc.). Scrub them out of every stored field
    # — symbol, watchlist, autopilot_universe — and PERSIST, so the terminal, the
    # status card and the scanner all reflect a clean, single-product account
    # without the user running any command.
    _block = getattr(cfg_mod, "CROSS_PRODUCT_BLOCK", set())

    def _foreign(sym):
        return bool(sym) and (sym.upper().replace("_", "").replace("/", "").replace("-", "")
                              in _block)

    _patch = {}
    if _foreign(user.get("symbol")):
        _patch["symbol"] = cfg_mod.SYMBOL
        user["symbol"] = cfg_mod.SYMBOL
    for _fld in ("watchlist", "autopilot_universe"):
        _orig = user.get(_fld) or []
        _clean = [s for s in _orig if s and not _foreign(s)]
        if _clean != _orig:
            _patch[_fld] = _clean
            user[_fld] = _clean
    if _patch:
        try:
            user_store.update(user_id, _patch)
            print(f"[UserLoop:{user_id}] scrubbed cross-product symbols: {list(_patch)}")
        except Exception as e:
            print(f"[UserLoop:{user_id}] cross-product scrub persist failed: {e}")

    broker, cfg = _make_broker(user)

    symbol = cfg.SYMBOL
    # Multi-symbol scanner (premium spec): the client can watch ANY basket of
    # instruments their broker offers; the bot enters only the strongest
    # setup per cycle, one open position at a time.
    # Auto-Pilot: the bot picks the instruments itself from a curated liquid
    # universe (validated per broker at enable time). Otherwise the client's
    # own /symbol or /watch basket is used.
    autopilot = bool(user.get("autopilot"))
    if autopilot and user.get("autopilot_universe"):
        # Raised from 8 now that one universe carries FX, metals and crypto.
        # It is a cap on WORK, not a preference: the broker connection is a
        # single socket with a lock held across each round-trip, so every extra
        # symbol lengthens the tick. Twelve keeps a scan comfortably inside the
        # interval; going much past it makes the loop slower than the signals
        # it is looking for.
        watchlist = [w for w in user["autopilot_universe"] if w][:12]
    else:
        watchlist = [w for w in (user.get("watchlist") or []) if w][:6]
    if getattr(cfg, "PRODUCT", "forex") == "crypto":
        watchlist = [w for w in watchlist if forex.is_crypto(w)]
        if not forex.is_crypto(symbol):
            symbol = watchlist[0] if watchlist else "BTCUSD"
    else:
        watchlist = [w for w in watchlist if forex.is_tradeable(w)]
        if not forex.is_tradeable(symbol):
            symbol = watchlist[0] if watchlist else "EUR_USD"
    paper_balance = cfg.PAPER_BALANCE
    # REAL mode: the stored seed goes stale the moment a trade closes — read
    # the broker's actual balance BEFORE the first status can be asked for,
    # and persist it so any future restart seeds correctly too.
    if not cfg.PAPER_TRADING:
        try:
            paper_balance = broker.get_balance()
            # Money moved while the loop was DOWN. If we were flat when it went
            # down, no trade can account for it, so it is a deposit or a
            # withdrawal and the drawdown peak has to follow it. (A position
            # that closed during the outage is the other case, and the restart
            # recovery below journals that as a real trade instead.)
            _prev_seed = float(cfg.PAPER_BALANCE or 0)
            _flat_when_down = not (user.get("open_position_snapshot") or {}).get("symbol")
            if _prev_seed and _flat_when_down and abs(paper_balance - _prev_seed) >= 0.01:
                strategies.rescale_peak(_prev_seed, paper_balance, user_id=user_id)
            user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
        except Exception as e:
            print(f"[UserLoop:{user_id}] initial balance read failed: {e}")
    open_pos = None  # tracked locally for paper mode
    _crypto_build = getattr(cfg, "PRODUCT", "forex") == "crypto"
    tick = 0
    data_fails = 0   # consecutive get_candles failures — alert the user at 3
    last_refresh_at = 0.0  # throttle cTrader token-refresh/reconnect attempts
    bar_seen = {}    # nrm(symbol) -> [newest_bar_time, ticks_unchanged]
    stale_alerted = 0.0  # throttle "feed frozen" alerts
    # Risk state is PERSISTED: a restart (redeploy, settings change, watchdog)
    # used to wipe the post-loss cooldown and the loss-streak risk ladder at
    # exactly the moment they mattered most — right after losses.
    last_loss_at = float(user.get("last_loss_at") or 0)   # entry cooldown anchor (any losing close)
    last_close_at = float(user.get("last_close_at") or 0) # re-entry lock after ANY close — kills open/close churn
    loss_streak = int(user.get("loss_streak") or 0)       # adaptive risk ladder: 2 losses → half risk, 3+ → quarter
    # The ladder is a within-session brake, but nothing ever cleared it: a
    # streak survived indefinitely, so losses from days ago still quartered
    # today's position size and the only escape was a winning trade. Everything
    # else that counts losses (dailyTrades, dailyPnL, consecutiveLosses) resets
    # on a new trading day; this now does too. Longer-horizon protection is
    # already covered by max_dd_pct and max_daily_loss_pct.
    def _clear_stale_streak():
        """Drop a loss streak carried over from a previous trading day.

        MUST be called every tick, not once at startup. It used to run only
        here in the setup, which meant the check was evaluated exactly once
        per process: a loop that stayed up across midnight kept a streak from
        the day before FOREVER, and the only escape was a winning trade or a
        redeploy. Observed live — a streak of 2 entered on 19 Aug was still
        halving position size on 20 Aug on a loop that had never restarted,
        while strategy_session had rolled over to the new day as designed.
        Two counters for the same thing, disagreeing, because only one of them
        was ever re-read.
        """
        nonlocal loss_streak
        if not (loss_streak and last_loss_at):
            return False
        day = datetime.fromtimestamp(last_loss_at).strftime("%Y-%m-%d")
        if day == datetime.now().strftime("%Y-%m-%d"):
            return False
        print(f"[UserLoop:{user_id}] loss streak of {loss_streak} was from "
              f"{day} — cleared for the new trading day")
        loss_streak = 0
        return True

    # Cleared at startup too — but the persist has to wait until
    # _persist_risk_state exists a few lines below, or the record keeps saying 2
    # while the running loop believes 0. That gap is not cosmetic: the value is
    # what every restart re-reads, and what the operator sees when they look.
    _cleared_at_start = _clear_stale_streak()

    def _persist_risk_state():
        try:
            user_store.update(user_id, {"last_loss_at": last_loss_at,
                                        "last_close_at": last_close_at,
                                        "loss_streak": loss_streak})
        except Exception as e:
            print(f"[UserLoop:{user_id}] risk-state persist failed: {e}")

    if _cleared_at_start:
        _persist_risk_state()

    def _persist_open_snapshot(pos):
        _persist_open_position(user_id, cfg, pos)

    def _with_initial_stop(pos, sym):
        """Re-persist a broker-read position without losing its original stop.

        The broker only ever reports the CURRENT stop, so any snapshot rebuilt
        from a broker read would drop the original one and the next restart
        would fall back to noise-tight trailing. Reconstruct it from the risk
        this process pinned at entry."""
        out = {**pos, "symbol": sym}
        r = entry_risk_by_sym.get(_nrm(sym))
        if r and pos.get("entryPrice") and not out.get("initialStop"):
            e = float(pos["entryPrice"])
            out["initialStop"] = e - r if pos.get("side") == "BUY" else e + r
        return out
    # nrm(symbol) -> the trade's ORIGINAL entry-to-stop distance. Keyed by
    # symbol because the focus can move between ticks (maxpos=1 adopts a
    # position found on another pair), and a trail sized off the wrong pair's
    # risk is worse than no trail at all. See _manage_trailing's initial_risk.
    entry_risk_by_sym = {}
    # nrm(symbol) -> the trade's decision snapshot (confidence, regime, ATR,
    # SL/TP, EV probability, spread at entry). Kept out-of-band for the same
    # reason as entry_risk_by_sym: the live position dict is re-read from the
    # broker every tick and comes back stripped of everything the broker
    # doesn't store. Without this the calibrator never gets a labelled trade.
    entry_meta_by_sym = {}
    prev_open_syms = set()  # multi-position: detect broker-side closes tick-to-tick
    pos_details = {}    # nrm(symbol) -> {symbol, side, entry, units} for P&L on close
    spread_blocked = {}  # nrm(symbol) -> retry_ts: Auto-Pilot avoids symbols whose
                         # spread is blown out (weekend crypto) instead of camping on them
    rate_limit_until = 0.0  # while > now, do only the minimal 1-symbol fetch
    last_ai_error_tick = -_AI_ERROR_THROTTLE  # allow first error immediately
    last_warn_tick = -_SKIP_WARN_THROTTLE     # smart-alert skip warnings (throttled)
    last_mkt_tick = -_SKIP_WARN_THROTTLE      # market-pulse heads-up (throttled)
    was_weekend_closed = market.is_weekend_close_window()  # fire the Telegram
                         # notice only on the Fri→closed and Sun→open EDGE,
                         # not every tick for the whole weekend
    weekend_failed = set()   # symbols the weekend flatten could not close, as
                             # last reported. Re-alert when this CHANGES — a
                             # position still open going into the gap is worth
                             # a second message, but not one every tick.
    was_stopped = False  # fire the "Trading paused" alert once per stop, not
                         # every tick for the rest of the day it stays true

    # Confidence → P(win) map, measured from this account's own closed trades.
    # Rebuilt periodically rather than every tick: it only moves when a trade
    # closes, and re-reading the journal on each tick is pointless I/O.
    # Sentinel: this loop's persistent, expiring view of every symbol it
    # watches. Per-loop rather than global — two users on the same pair have
    # different accounts, risk and strategy, so they do not share an opinion.
    _signals = sentinel.SignalStore()
    _sentinel_mode = str(getattr(cfg, "SENTINEL_MODE", "shadow")).lower()
    _inst_mode = str(getattr(cfg, "INSTITUTIONAL_GATE", "shadow")).lower()
    # nrm(symbol) -> the features and verdict of the last ACTUAL AI call.
    # Deliberately not the last published state: the state is republished every
    # tick with the current price, so comparing against it would reset the
    # "price moved" test on every pass and let price drift arbitrarily far
    # without ever triggering a refresh.
    _last_ai = {}

    ev_calibration = None
    ev_cal_tick = -10 ** 9

    def _refresh_ev_calibration():
        """(Re)build the calibration table. Returns it, or None when there is
        not yet enough labelled history to say anything honest."""
        try:
            return ev_engine.calibrate(
                user_store.load_trades(user_id),
                min_total=getattr(cfg, "EV_MIN_SAMPLES", 30))
        except Exception as e:
            print(f"[UserLoop:{user_id}] EV calibration failed: {e}")
            return None

    acct_env = (user.get("ctrader_env") or "demo").lower()
    mode_label = ("📝 Simulation" if cfg.PAPER_TRADING
                  else ("🧪 Demo" if acct_env in ("demo", "practice")
                        else "🔴 LIVE"))
    dash = {
        "broker": _broker_label(user, cfg),
        "mode": mode_label,
        "strategy": _strategy_label(cfg.STRATEGY),
        "balance": paper_balance,
        "startBalance": paper_balance,
        "symbol": symbol,
        "watchlist": watchlist,
        "autopilot": autopilot,
        "trades": [],
        "lastTick": None,
        "currentPrice": None,
    }
    # Seed the trade history from the persistent journal: the in-memory list
    # was wiped on every loop restart (redeploy, settings change), so /status
    # showed "0 trades" and the bot looked like it never traded.
    try:
        _j = user_store.load_trades(user_id) or []
        dash["trades"] = [{**t, "action": "CLOSE", "price": t.get("exit"),
                           "entryPrice": t.get("entry"),
                           "win": (t.get("netPnl") or 0) > 0}
                          for t in reversed(_j[-15:])]
    except Exception as e:
        print(f"[UserLoop:{user_id}] journal seed failed: {e}")

    # Startup position recovery. open_pos is wiped to None on every restart
    # with nothing to reconcile against. If the position was STILL open at
    # the broker, the next tick's own get_open_position()/watchlist scan
    # finds it — but if it closed at the broker during the restart gap
    # itself (old process dead, new one not ticking yet), nobody was ever
    # alive to see the transition and it used to vanish: no BROKER_CLOSE, no
    # journal entry, no Telegram alert — just a balance drop nobody could
    # explain. Compare the broker's current truth against the last position
    # this process persisted before it went down.
    if not cfg.PAPER_TRADING:
        _snap = user.get("open_position_snapshot")
        if _snap and _snap.get("symbol"):
            _live, _got_answer = None, False
            # This is the very first broker call a fresh process makes — the
            # connection may not be warmed up yet. Retry before concluding
            # anything: an exception here is NOT the same fact as "the
            # broker confirmed you're flat," and treating them as equal was
            # itself a bug — a transient hiccup at exactly this moment would
            # get read as "position closed" and abandon tracking of a
            # position that's actually still open and unmanaged from then on.
            #
            # _got_answer (NOT "did any attempt fail") is what must gate the
            # "confirmed gone" branch below — simulating this caught a real
            # bug: with a "did any attempt fail" flag, failing once or twice
            # and then getting a clean, definitive "flat" answer on the final
            # retry still fell into the "unreachable, keep tracked" branch,
            # because that flag stayed set from the earlier failures even
            # though the broker DID answer by the end. That left the loop
            # believing a position was still open when the broker had just
            # said, authoritatively, that it wasn't — which then misfires
            # the tick loop's own BROKER_CLOSE detector with a bogus estimate
            # on the very next tick.
            for _attempt in range(3):
                try:
                    _live = broker.get_open_position(_snap["symbol"])
                    _got_answer = True
                    break
                except Exception as e:
                    print(f"[UserLoop:{user_id}] startup position check failed "
                          f"(attempt {_attempt + 1}/3): {e}")
                    if _attempt < 2:
                        time.sleep(2)
            _verdict = recovery_verdict(_live, _got_answer)
            if _verdict == ADOPT:
                symbol = _snap["symbol"]
                open_pos = _live
                # The persisted snapshot is the only surviving record of WHY
                # this trade was taken — the broker read that just replaced it
                # carries none of it. A redeploy mid-trade must not cost us the
                # label.
                entry_meta_by_sym[_nrm(symbol)] = _entry_meta(_snap)
                _reattach_entry_meta(open_pos, entry_meta_by_sym[_nrm(symbol)])
                dash["symbol"] = symbol
                dash["openPosition"] = open_pos
                # Still open — re-persist it (don't clear!). If we wiped the
                # snapshot here, a SECOND restart while this same position is
                # still open would find nothing to compare against and we'd
                # be back to the exact bug this is fixing.
                # Carry the ORIGINAL stop across the restart, not the live one:
                # if this position has already trailed, its current stop is no
                # longer its risk, and re-deriving R from it would resume the
                # noise-tight trailing this fix removes.
                _init_stop = _snap.get("initialStop")
                _risk = _risk_from_snapshot(open_pos.get("entryPrice"), _init_stop)
                if _risk is not None:
                    entry_risk_by_sym[_nrm(symbol)] = _risk
                _persist_open_snapshot({**open_pos, "symbol": symbol,
                                        "initialStop": _init_stop})
                print(f"[UserLoop:{user_id}] restart recovery: adopted still-open {symbol} position"
                      f"{'' if _init_stop else ' (no initial stop on record — trailing falls back to the live stop)'}")
            elif _verdict == KEEP_TRACKED:
                # Never got a definitive answer from the broker — don't guess
                # "closed." Keep tracking it from the snapshot; the very next
                # tick's own position-sync (which is allowed to keep retrying)
                # will resolve the real state either way.
                symbol = _snap["symbol"]
                open_pos = dict(_snap)
                entry_meta_by_sym[_nrm(symbol)] = _entry_meta(_snap)
                dash["symbol"] = symbol
                dash["openPosition"] = open_pos
                if _snap.get("initialStop") and _snap.get("entryPrice"):
                    entry_risk_by_sym[_nrm(symbol)] = abs(
                        float(_snap["entryPrice"]) - float(_snap["initialStop"]))
                _persist_open_snapshot(open_pos)
                print(f"[UserLoop:{user_id}] restart recovery: broker unreachable at startup — "
                      f"keeping {symbol} tracked pending the next tick")
            else:
                # Gone — it closed at the broker while nothing was watching.
                # Ask the broker for the actual closed-deal record first (same
                # number cTrader's own History tab shows); only fall back to
                # pricing against the next quote if that lookup can't find it.
                _deal = None
                _pos_id = _snap.get("positionId")
                if _pos_id:
                    try:
                        _deal = broker.get_closed_deal_pnl(_pos_id)
                    except Exception as e:
                        print(f"[UserLoop:{user_id}] closed-deal lookup failed: {e}")
                if _deal is not None:
                    net = _deal["netPnl"]
                    gross_pnl = _deal["grossPnl"]
                    cost_usd = _deal["commissionUsd"]
                    exit_price = None
                    reasoning = "closed at the broker during a restart — exact P&L from cTrader's deal history"
                else:
                    try:
                        _c = broker.get_candles(_snap["symbol"], cfg.TIMEFRAME, 2)
                        exit_price = _c[-1]["close"] if _c else None
                    except Exception:
                        exit_price = None
                    units_ = _snap.get("units") or _snap.get("quantity", 0)
                    net = None
                    if exit_price and _snap.get("entryPrice") and units_:
                        if _plausible_exit_price(_snap["entryPrice"], exit_price):
                            net = round(forex.pnl_usd(_snap.get("side", "BUY"), _snap["entryPrice"],
                                                      exit_price, units_, _snap["symbol"]), 2)
                        else:
                            print(f"[UserLoop:{user_id}] BROKER_CLOSE fallback rejected implausible "
                                  f"exit_price={exit_price} vs entryPrice={_snap['entryPrice']} "
                                  f"for {_snap['symbol']}")
                            exit_price = None
                    gross_pnl = net
                    cost_usd = 0.0
                    reasoning = ("closed at the broker during a restart — exact fill "
                                 "unknown, priced against the next available quote"
                                 if net is not None else
                                 "closed at the broker during a restart — exact P&L "
                                 "couldn't be verified safely, check cTrader history")
                result = {"action": "BROKER_CLOSE", "symbol": _snap["symbol"],
                          "side": _snap.get("side", ""), "price": exit_price,
                          "entryPrice": _snap.get("entryPrice"), "netPnl": net,
                          "grossPnl": gross_pnl, "costUsd": cost_usd,
                          "balance": round(paper_balance, 2),
                          "openedAt": _snap.get("openedAt"),
                          "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                          "reasoning": reasoning}
                # _snap is the persisted open-position snapshot, which carries
                # the entry decision fields — so a trade closed during a
                # restart still lands in the journal labelled.
                # Gate every side effect on the journal actually accepting this
                # close. The in-loop detection below can reach the same close a
                # few seconds later; counting it twice pushes loss_streak to 3
                # after two real losses and cuts risk to a quarter for no
                # reason, and double-counts the day's P&L.
                _fresh = _log_trade(user_id, result, _snap)
                if _fresh:
                    dash["trades"].insert(0, result)
                    dash["trades"] = dash["trades"][:50]
                    if net is not None and net < 0:
                        last_loss_at = time.time()
                        loss_streak += 1
                    elif net is not None and net > 0:
                        loss_streak = 0
                    last_close_at = time.time()
                    _persist_risk_state()
                    if net is not None:
                        strategies.record_trade(net > 0, net, dash.get("startBalance") or paper_balance,
                                                user_id=user_id, symbol=_snap["symbol"])
                    if alert_fn:
                        alert_fn(user_id, result)
                print(f"[UserLoop:{user_id}] restart recovery: journaled a close missed during the outage on {_snap['symbol']}")
                _persist_open_snapshot(None)

    with _lock:
        if user_id in _loops:
            _loops[user_id]["dash"] = dash

    health = {"lats": [], "spreads": [], "degraded": False, "last_alert": 0.0}

    def _health_check(lat=None, spread=None):
        """Broker Health Monitor (premium spec #8): when latency blows past the
        broker's own recent norm, suspend entries and say so. The spread-based
        check is skipped for crypto — the Auto-Pilot scans a basket whose per-
        coin spreads differ 10x (SOL 600p vs BTC 5p), so a shared spread median
        is meaningless and would flip-flop degraded/recovered every scan (spam).
        The per-entry %-spread guard already blocks wide-spread entries."""
        if lat is not None:
            health["lats"] = (health["lats"] + [lat])[-30:]
        if spread is not None and spread > 0:
            health["spreads"] = (health["spreads"] + [spread])[-30:]
        bad = None
        lats, sps = health["lats"], health["spreads"]
        if len(lats) >= 6:
            med = sorted(lats)[len(lats) // 2]
            if lats[-1] > max(8.0, med * 5):
                bad = f"data latency {lats[-1]:.1f}s (normal ~{med:.1f}s)"
        if not bad and not _crypto_build and len(sps) >= 8 and spread is not None:
            med = sorted(sps)[len(sps) // 2]
            if spread > max(med * 4, med + 2):
                bad = f"spread {spread:.1f}p vs normal ~{med:.1f}p"
        was = health["degraded"]
        health["degraded"] = bool(bad)
        dash["brokerHealth"] = "degraded: " + bad if bad else "ok"
        # Throttle the alert to at most once per 30 min so a flapping condition
        # can't spam the client.
        now = time.time()
        if alert_fn and now - health["last_alert"] > 1800:
            if bad and not was:
                health["last_alert"] = now
                alert_fn(user_id, {"action": "BROKER_HEALTH", "status": "degraded",
                                   "reason": bad, "symbol": symbol})
            elif was and not bad:
                health["last_alert"] = now
                alert_fn(user_id, {"action": "BROKER_HEALTH", "status": "recovered",
                                   "symbol": symbol})
        return health["degraded"]

    def _recent_spread():
        """Median of recently observed spreads, or None.

        The AI runs before the entry block fetches bid/ask, so the live spread
        does not exist yet at that point — reading it there would be a stale
        value from some earlier tick, or an unbound name on the first one. The
        health monitor already keeps a rolling window of real observations,
        which is both available and more representative than one quote.
        """
        sps = sorted(health.get("spreads") or [])
        if not sps:
            return None
        return sps[len(sps) // 2]

    def _focus(sym):
        """Move the Auto-Pilot focus, and persist it.

        The rotation only ever wrote dash["symbol"], which is in-memory. Every
        Telegram command reads the STORED user["symbol"] instead, so the two
        drifted apart the moment Auto-Pilot moved: the dashboard and heartbeat
        showed XAUUSD while /status, /chart and — worst — a bare /buy still
        used whatever pair the record was last left on. A manual buy would open
        a position on an instrument the bot had not looked at in hours.

        Written only on an actual change, so this costs one store write per
        rotation rather than one per tick.
        """
        nonlocal symbol
        symbol = sym
        dash["symbol"] = sym
        if _nrm(user_store.load(user_id).get("symbol")) != _nrm(sym):
            try:
                user_store.update(user_id, {"symbol": sym})
            except Exception as e:
                print(f"[UserLoop:{user_id}] focus persist failed: {e}")

    _skip_alerted = {}   # (symbol, reason) -> when it was last sent

    def _skip(reason, alert=True):
        """Journal every rejected entry (premium spec #12) — clients see the
        discipline, not just the trades: 'refused 14 weak setups today'.

        This wrote to the dashboard and nowhere else, so of the 25 places that
        refuse an entry only six ever reached Telegram, and the HTF gate — the
        one doing most of the refusing — was not among them. A client watching
        their phone saw the bot go quiet for a day with no explanation.

        Those six also shared ONE `last_warn_tick`, so a "market too quiet"
        notice at 08:00 silenced a spread warning at 08:05 and an EV veto at
        08:10 for the next three hours. Throttling is per (symbol, reason)
        instead: each distinct refusal gets through once, and only the identical
        one repeating on the next tick is suppressed. The HTF gate fired eight
        times on one symbol with one reason today — that is one message, not
        eight, and not zero.

        `alert=False` is for the two sites that send their own richer message
        (flash-crash, news) and would otherwise double up.

        The cooldown is held in REDIS, not in this dict. Holding it in memory
        looked equivalent and was not: every restart emptied it, and the next
        tick re-sent everything it had already sent. Three deploys inside six
        minutes produced three identical "Holding off on XAUUSD" messages —
        the throttle was working perfectly and being reset out from under it.
        Deploys are not the only restarts either; the watchdog restarts loops
        too, and during a deploy two instances run at once and would each
        notify. A shared key with a TTL fixes all three at once, and is the
        same primitive the order ledger uses. The dict stays as the fallback
        for when there is no Redis configured.
        """
        today = datetime.now().strftime("%Y-%m-%d")
        if dash.get("skipsDay") != today:
            # Day rolled over. Send yesterday's recap BEFORE the counters are
            # cleared — a summary is only worth sending while the day it
            # describes still exists.
            _prev = dash.get("skipsDay")
            dash["skipsDay"], dash["skipsToday"] = today, 0
            _skip_alerted.clear()
            if _prev:
                try:
                    from apex import telegram as _tg
                    _tg.send_daily_summary(user_id)
                except Exception as e:
                    print(f"[UserLoop:{user_id}] daily summary failed: {e}")
        dash["skipsToday"] = dash.get("skipsToday", 0) + 1
        lst = dash.setdefault("skips", [])
        lst.insert(0, {"time": datetime.now().strftime("%H:%M"), "reason": str(reason)[:120]})
        del lst[30:]

        # Every refusal goes to stdout too. The dashboard keeps the last 30 and
        # Telegram deliberately shows each distinct reason once per three
        # hours — both are the right behaviour for a person, and both make the
        # logs useless for debugging: searching Render for why the bot went
        # quiet returned nothing at all, because no refusal was ever written
        # there. This line is NOT throttled; the log is where the full,
        # unsummarised sequence belongs.
        print(f"[UserLoop:{user_id}] SKIP {symbol}: {reason} "
              f"(#{dash['skipsToday']} today)")

        if not (alert and alert_fn):
            return
        try:
            key = f"{_nrm(symbol)}|{str(reason)[:60]}"
            shared = user_store.claim(f"skipalert:{user_id}:{key}",
                                      ttl_s=_SKIP_ALERT_COOLDOWN_S)
            if shared is False:
                return                      # already announced, still cooling
            if shared is None:              # no shared store — in-memory only
                now_s = time.time()
                if now_s - _skip_alerted.get(key, 0) < _SKIP_ALERT_COOLDOWN_S:
                    return
                _skip_alerted[key] = now_s
                if len(_skip_alerted) > 200:
                    for k in sorted(_skip_alerted, key=_skip_alerted.get)[:100]:
                        _skip_alerted.pop(k, None)
            alert_fn(user_id, {"action": "SKIP_WARN", "symbol": symbol,
                               "reason": str(reason)[:200],
                               "countToday": dash.get("skipsToday", 1)})
        except Exception as e:
            print(f"[UserLoop:{user_id}] skip alert failed: {e}")

    while True:
        with _lock:
            entry = _loops.get(user_id, {})
            if not entry.get("running") or (gen is not None and entry.get("gen") != gen):
                break  # stopped, or replaced by a newer loop (restart race)

        # Ownership. The generation check above only sees threads in THIS
        # process; the lease is what sees the other container.
        #
        # Renewal does NOT happen here. This tick is five minutes long and can
        # block far longer inside a broker read, so renewing from the top of
        # the tick left the lease expired for most of its life — and the next
        # renewal then read the missing key as a takeover and shut the loop
        # down on a single uncontended container. A dedicated thread renews on
        # wall-clock time; this only reacts to a takeover it has confirmed.
        if ownership.was_lost(user_id):
            # Another instance genuinely holds the lease — not "the key
            # expired", which the renewer re-acquires instead. Stand down
            # rather than trade alongside the new owner, which has already
            # read the broker's real positions for itself.
            print(f"[UserLoop:{user_id}] lease taken over — standing down")
            try:
                if alert_fn:
                    alert_fn(user_id, {"action": "OWNERSHIP_LOST",
                                       "reason": "another instance took over"})
            except Exception:
                pass
            # This path leaves the loop WITHOUT going through stop(), so it has
            # to clean up after itself. Leaving the renewer registered and the
            # lost-flag set made the next watchdog restart alert and break on
            # its first tick, forever.
            try:
                ownership.stop_renewer(user_id)
            except Exception:
                pass
            break
        try:
            if not forex.is_market_open():
                time.sleep(60)
                continue

            # The day can roll over under a loop that never restarts, so the
            # streak has to be re-checked here rather than only at startup.
            if _clear_stale_streak():
                _persist_risk_state()

            # ── MULTI-POSITION: how many concurrent trades, and total-risk cap.
            # Live-only (paper stays single). Total exposure is bounded by
            # sizing each trade at max_total_risk / maxpos, so N positions never
            # risk more than max_total_risk of the account combined.
            maxpos = int(user_store.load(user_id).get("maxpos", 1)) if not cfg.PAPER_TRADING else 1
            maxpos = max(1, min(maxpos, 8))
            max_total_risk = float(user_store.load(user_id).get("max_total_risk", 0.05))
            per_trade_risk = min(cfg.RISK_PER_TRADE, max_total_risk / maxpos)

            rate_ok = time.time() >= rate_limit_until
            all_positions = None
            open_syms, open_exposure = set(), []
            if not cfg.PAPER_TRADING and rate_ok:
                try:
                    all_positions = broker.get_all_positions()
                    open_syms = {_nrm(p["symbol"]) for p in all_positions}
                    open_exposure = [forex.usd_exposure(p["symbol"], p["side"]) for p in all_positions]
                    # Remember each position's details so we can compute realized
                    # P&L when it later closes at the broker (multi-position).
                    for p in all_positions:
                        pos_details[_nrm(p["symbol"])] = {
                            "symbol": p["symbol"], "side": p["side"],
                            "entry": p.get("entryPrice"), "units": p.get("units", 0),
                            "positionId": p.get("positionId")}
                except Exception as e:
                    all_positions = None  # unknown → don't open blind this tick
                    print(f"[UserLoop:{user_id}] positions read: {e}")
            # Report + JOURNAL positions that closed at the broker since last tick.
            if all_positions is not None:
                # Focused symbol's close is reported by the single-position path
                # below; only announce the OTHER (self-managed) ones here.
                closed_now = prev_open_syms - open_syms - {_nrm(symbol)}
                for cs in closed_now:
                    det = pos_details.get(cs, {})
                    # Only journal positions WE opened (have details for). Without
                    # this, a position opened by another bot sharing the account
                    # is journaled here with mismatched data — e.g. a gold entry
                    # reported as BTCUSD — corrupting P&L and the tax journal.
                    if not det or not det.get("entry"):
                        continue
                    # Ask the broker for this position's actual closed-deal
                    # P&L first — matches cTrader's History tab exactly, and
                    # unlike the candle-close estimate below, includes the
                    # real fill/commission/swap regardless of how many other
                    # positions also closed in this same polling window.
                    _deal = None
                    if det.get("positionId"):
                        try:
                            _deal = broker.get_closed_deal_pnl(det["positionId"])
                        except Exception as e:
                            print(f"[UserLoop:{user_id}] closed-deal lookup failed: {e}")
                    est_pnl = None
                    xp = None
                    gross_pnl = None
                    cost_usd = 0.0
                    if _deal is not None:
                        est_pnl = _deal["netPnl"]
                        gross_pnl = _deal["grossPnl"]
                        cost_usd = _deal["commissionUsd"]
                    else:
                        try:
                            if det.get("entry") and det.get("units"):
                                xc = broker.get_candles(det["symbol"], cfg.TIMEFRAME, 2)
                                xp = xc[-1]["close"] if xc else None
                                if xp and _plausible_exit_price(det["entry"], xp):
                                    est_pnl = round(forex.pnl_usd(det["side"], det["entry"], xp,
                                                                  det["units"], det["symbol"]), 2)
                                    gross_pnl = est_pnl
                                elif xp:
                                    print(f"[UserLoop:{user_id}] BROKER_CLOSE_MULTI fallback rejected "
                                          f"implausible exit_price={xp} vs entry={det['entry']} "
                                          f"for {det['symbol']}")
                                    xp = None
                        except Exception:
                            est_pnl = None
                    now2 = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    rec = {"action": "CLOSE", "symbol": det.get("symbol", cs),
                           "entryPrice": det.get("entry"), "price": xp,
                           "grossPnl": gross_pnl, "costUsd": cost_usd, "netPnl": est_pnl,
                           "balance": round(paper_balance, 2), "time": now2}
                    # These are the SL/TP hits — the single most informative
                    # label the calibrator can get, and the one path that was
                    # journalling them unlabelled because the position object
                    # is long gone by the time the broker reports it closed.
                    # The out-of-band snapshot is still here.
                    _meta = entry_meta_by_sym.get(cs)
                    _log_trade(user_id, rec,
                               {**_meta, "symbol": det.get("symbol", cs)} if _meta else None)
                    dash["trades"].insert(0, {**rec, "reasoning": "closed at broker (target/stop)"})
                    dash["trades"] = dash["trades"][:50]
                    if est_pnl is not None and est_pnl < 0:
                        loss_streak += 1
                        last_loss_at = time.time()
                    elif est_pnl is not None and est_pnl > 0:
                        loss_streak = 0
                    last_close_at = time.time()
                    _persist_risk_state()
                    if est_pnl is not None:
                        strategies.record_trade(est_pnl > 0, est_pnl,
                                                dash.get("startBalance") or paper_balance,
                                                user_id=user_id, symbol=det.get("symbol", cs))
                    pos_details.pop(cs, None)
                    if alert_fn:
                        alert_fn(user_id, {"action": "BROKER_CLOSE_MULTI", "symbol": det.get("symbol", cs),
                                           "netPnl": est_pnl, "balance": round(paper_balance, 2)})
                prev_open_syms = set(open_syms)
                # Drop pinned risk for anything no longer open, so a later
                # trade on the same pair never trails off a dead position's R.
                # Done here, against the broker's own list, rather than at each
                # close site — SL/TP, manual /close, weekend flatten and the
                # protective stop all converge on this one truth.
                for _gone in [k for k in entry_risk_by_sym if k not in open_syms]:
                    entry_risk_by_sym.pop(_gone, None)
                # Same for the decision snapshot — but only AFTER the close has
                # been journalled above, which is why this sits at the end of
                # the reconciliation block and not beside the broker read.
                for _gone in [k for k in entry_meta_by_sym if k not in open_syms]:
                    entry_meta_by_sym.pop(_gone, None)
            open_count = len(open_syms)
            dash["openCount"] = open_count
            dash["maxpos"] = maxpos

            # ── Basket/Auto-Pilot scan: shop every watched symbol (that isn't
            # already open) and focus on the strongest candidate. Only scan if
            # we have a free slot. The winner still passes the FULL pipeline.
            # Free-slot signal differs by mode: live reads broker positions,
            # paper tracks a single local position (all_positions is always None
            # in paper, which used to freeze the scanner and pin the focus).
            slot_free = ((open_pos is None) if cfg.PAPER_TRADING
                         else ((all_positions is not None) and (open_count < maxpos)))
            # Scan cadence: forex every 3 ticks (~15 min); crypto every 2 (~10
            # min) because setups rotate faster across the coin basket and only
            # the focus symbol is entered per tick, so scanning too rarely misses
            # most setups. Requests are spaced 0.35s to respect cTrader's limit.
            # Also rescan immediately when the focus is spread-blocked so the bot
            # doesn't camp on a dead symbol.
            _scan_every = max(1, round(_SCAN_INTERVAL_S / max(1, _LOOP_INTERVAL)))
            due_to_scan = (tick % _scan_every == 0) or (
                spread_blocked.get(_nrm(symbol), 0) > time.time())
            if watchlist and slot_free and due_to_scan and rate_ok:
                best = None
                for ws in watchlist:
                    if _nrm(ws) in open_syms:
                        continue  # already holding this one
                    if spread_blocked.get(_nrm(ws), 0) > time.time():
                        continue  # spread blown out recently — try others first
                    try:
                        time.sleep(0.35)  # space out trendbar requests — cTrader rate-limits bursts
                        c2 = broker.get_candles(ws, cfg.TIMEFRAME, 160)
                        if not c2 or len(c2) < 130:
                            continue
                        ind2 = indicators.analyze(c2)
                        st2 = strategies.analyze(c2)
                        m2 = cfg.STRATEGY
                        if m2 == "auto":
                            reg2 = strategies.detect_regime(c2)
                            if reg2["regime"] == "quiet":
                                continue
                            m2 = {"trending": "trend", "ranging": "mean_reversion",
                                  "volatile": "breakout"}.get(reg2["regime"], "mean_reversion")
                        s2 = ai.signal_for_mode(m2, ind2, st2, None)
                        if (s2.get("action") in ("BUY", "SELL")
                                and s2.get("confidence", 0) >= cfg.MIN_CONFIDENCE
                                and (not best or s2["confidence"] > best[1])):
                            best = (ws, s2["confidence"])
                    except Exception as e:
                        print(f"[UserLoop:{user_id}] scan {ws}: {e}")
                if best:
                    _focus(best[0])
                elif (spread_blocked.get(_nrm(symbol), 0) > time.time()
                      or _nrm(symbol) in open_syms):
                    # Nothing signalled this scan AND the current focus is
                    # untradeable (spread-blocked or already open) — camp on ANY
                    # tradeable coin instead of freezing on the dead one and
                    # re-tripping its spread guard forever.
                    for ws in watchlist:
                        if _nrm(ws) in open_syms:
                            continue
                        if spread_blocked.get(_nrm(ws), 0) > time.time():
                            continue
                        _focus(ws)
                        break

            # Data fetch is the loop's lifeline — if it fails silently the user
            # just sees "Last tick: None" forever. Count failures and tell them.
            try:
                _t0 = time.time()
                candles = broker.get_candles(symbol, cfg.TIMEFRAME, cfg.CANDLES)
                _health_check(lat=time.time() - _t0)
                data_err = None if candles else "broker returned no candles"
            except Exception as e:
                candles, data_err = None, str(e)
            # Observe the spread every tick, not only when an entry is being
            # attempted. The only other caller of _health_check(spread=...)
            # sits inside the entry block, past every gate — so on a tick the
            # HTF gate refuses, no spread is ever recorded. `health` is rebuilt
            # per process, so after each restart liquidity_quality was missing
            # from the institutional read until the first entry attempt, which
            # can be hours. That is 0.6 of 6.9 weight lost for no reason,
            # dragging the composite toward UNUSABLE while the quote sat one
            # call away. Fail-soft: a bad quote just leaves the window as it is.
            try:
                _b, _a = broker.get_bid_ask(symbol)
                _sp = forex.spread_pips(_b, _a, symbol)
                if _sp and _sp > 0:
                    _health_check(spread=_sp)
            except Exception:
                pass

            if not candles:
                data_fails += 1
                print(f"[UserLoop:{user_id}] data error ({data_fails}): {data_err}")
                rate_limited = "rate" in str(data_err).lower() or "BLOCKED_PAYLOAD" in str(data_err)
                if rate_limited:
                    rate_limit_until = time.time() + 120  # pause scanner/positions 2 min
                # Self-heal: on a cTrader auth/route error, refresh the token +
                # reconnect ONCE (throttled to every 3 min) before nagging the
                # client to /ctrader. If cTrader is fully down this no-ops and we
                # just keep retrying until their API recovers.
                elif (not cfg.PAPER_TRADING and cfg.CTRADER_ACCESS_TOKEN
                      and _looks_like_auth_error(data_err)
                      and data_fails >= 2 and time.time() - last_refresh_at > 180):
                    last_refresh_at = time.time()
                    if _refresh_ctrader_token(user_id, cfg):
                        data_fails = 0
                        time.sleep(5)
                        continue
                if data_fails == 3 and alert_fn and not rate_limited:
                    alert_fn(user_id, {
                        "action": "DATA_ERROR",
                        "reason": data_err,
                        "symbol": symbol,
                        "broker": dash.get("broker", "your broker"),
                    })
                # Rate-limit → back off longer so the limit resets; transient
                # rate limits shouldn't spam the user with data-error alerts.
                time.sleep(90 if rate_limited else 30)
                continue
            data_fails = 0

            tick += 1
            price = candles[-1]["close"]
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            dash["currentPrice"] = price
            dash["lastTick"] = now_str
            dash["lastTickTs"] = time.time()  # epoch — status shows "Xm ago", timezone-proof

            # ── Frozen-feed detection ──────────────────────────────────────
            # If the newest candle's timestamp stops advancing, the broker isn't
            # quoting this symbol (many brokers freeze crypto-CFD feeds on
            # weekends / off-hours). A frozen feed never produces a signal, so
            # the bot would sit silent forever. Detect it, mark the symbol so
            # Auto-Pilot rotates to a live one, and tell the user once.
            _bt = candles[-1]["time"]
            # Diagnostic: shows whether the newest candle advances (fresh feed)
            # or repeats (frozen feed) — visible in the host logs.
            print(f"[UserLoop:{user_id}] tick {tick} {symbol} px={price} "
                  f"newest_bar={datetime.utcfromtimestamp(_bt).strftime('%m-%d %H:%M')}UTC "
                  f"bars={len(candles)}")
            _bs = bar_seen.get(_nrm(symbol))
            if _bs and _bs[0] == _bt:
                _bs[1] += 1
            else:
                bar_seen[_nrm(symbol)] = [_bt, 0]
            if bar_seen[_nrm(symbol)][1] >= 3:  # ~15+ min with no new candle
                spread_blocked[_nrm(symbol)] = time.time() + 900  # rotate away 15 min
                live_syms = [w for w in watchlist
                             if bar_seen.get(_nrm(w), [0, 0])[1] < 3
                             and spread_blocked.get(_nrm(w), 0) <= time.time()]
                # A long-lived cTrader connection can keep answering (heartbeats)
                # while its trendbar stream goes stale. If EVERY watched symbol
                # is frozen, the connection itself is stale — drop it so the next
                # tick reconnects fresh (throttled), then tell the user once.
                if not live_syms and not cfg.PAPER_TRADING and time.time() - last_refresh_at > 300:
                    last_refresh_at = time.time()
                    try:
                        from apex.brokers import ctrader as _ct
                        _ct._drop_conn(getattr(cfg, "CTRADER_ENV", "demo"),
                                       cfg.CTRADER_ACCOUNT_ID)
                        for k in bar_seen:  # reset so we re-measure after reconnect
                            bar_seen[k][1] = 0
                        print(f"[UserLoop:{user_id}] feed stale on all symbols — dropped cTrader connection to reconnect")
                    except Exception as e:
                        print(f"[UserLoop:{user_id}] stale-feed reconnect failed: {e}")
                if not live_syms and alert_fn and time.time() - stale_alerted > 3600:
                    stale_alerted = time.time()
                    alert_fn(user_id, {
                        "action": "DATA_ERROR",
                        "reason": ("the broker's price feed stopped sending new candles — "
                                   "reconnecting to the broker now. If it persists the broker "
                                   "may be having a data issue; the bot resumes when prices move."),
                        "symbol": symbol,
                        "broker": dash.get("broker", "your broker"),
                    })

            # Live: sync position from broker; paper: use local tracking.
            # If the position read FAILS we must not assume flat — entering
            # blind is how positions stack. Skip the tick and alert instead.
            if not cfg.PAPER_TRADING:
                prev_pos = open_pos
                try:
                    # Focus this tick on the SCANNED symbol; its position (if any)
                    # is managed here. Other open positions ride their broker
                    # SL/TP. In single-position mode (maxpos 1) fall back to
                    # whatever symbol currently holds the one position.
                    open_pos = broker.get_open_position(symbol)
                    # The broker's dict has no idea why we took this trade.
                    # Put the decision snapshot back before anything reads it,
                    # or it is lost for good the moment the position closes.
                    _reattach_entry_meta(open_pos, entry_meta_by_sym.get(_nrm(symbol)))
                    if maxpos == 1 and watchlist and not open_pos:
                        for ws in watchlist:
                            if ws == symbol:
                                continue
                            p_ = broker.get_open_position(ws)
                            if p_:
                                symbol = ws
                                dash["symbol"] = symbol
                                open_pos = _reattach_entry_meta(
                                    p_, entry_meta_by_sym.get(_nrm(ws)))
                                candles = broker.get_candles(symbol, cfg.TIMEFRAME, cfg.CANDLES) or candles
                                # `price` must move with the symbol switch — it's
                                # compared against THIS position's stop/entry a few
                                # lines down (protective-stop check). Left stale
                                # from the old symbol, a mismatched price always
                                # reads as "breached", forcing a close whose P&L is
                                # computed from a price that belongs to a different
                                # pair entirely (this produced a six-figure phantom
                                # netPnl that also corrupted the daily-loss tracker).
                                if candles:
                                    price = candles[-1]["close"]
                                break
                except Exception as e:
                    data_fails += 1
                    print(f"[UserLoop:{user_id}] position read error ({data_fails}): {e}")
                    if data_fails == 3 and alert_fn:
                        alert_fn(user_id, {
                            "action": "DATA_ERROR",
                            "reason": f"can't read open positions: {e}",
                            "symbol": symbol,
                            "broker": dash.get("broker", "your broker"),
                        })
                    time.sleep(30)
                    continue
                data_fails = 0
                if open_pos and not prev_pos:
                    # Newly recognized position this tick (manual open, or the
                    # watchlist fallback above finding it on another symbol) —
                    # keep the restart-recovery snapshot current so a redeploy
                    # right after this tick can still find it.
                    if _nrm(symbol) not in entry_risk_by_sym:
                        # force_trade (/buy, /sell, MCP open_trade) records the
                        # original stop in the snapshot from a different call
                        # path, so adopt it instead of falling back to the live
                        # stop — a manual entry deserves the same exit quality.
                        _s = (user_store.load(user_id) or {}).get("open_position_snapshot") or {}
                        if _nrm(_s.get("symbol")) == _nrm(symbol):
                            _risk = _risk_from_snapshot(_s.get("entryPrice"), _s.get("initialStop"))
                            if _risk is not None:
                                entry_risk_by_sym[_nrm(symbol)] = _risk
                    _persist_open_snapshot(_with_initial_stop(open_pos, symbol))

                # Trailing-stop / break-even management for the open position
                # (Strategy Builder exit modes). Fail-soft; real-broker only.
                if open_pos and not cfg.PAPER_TRADING:
                    moved = _manage_trailing(
                        broker, cfg, open_pos, symbol, price,
                        initial_risk=entry_risk_by_sym.get(_nrm(symbol)))
                    if moved is not None:
                        open_pos["stopLoss"] = open_pos["sl"] = moved
                        # A trailing stop moves many times per trade — nine
                        # times on one position yesterday, nine near-identical
                        # messages. Exactly ONE of those moves is worth
                        # telling the client about: the one that takes the
                        # stop past the entry, after which the trade cannot
                        # lose. Announce that once; the rest are diagnostic.
                        try:
                            _entry_px = float(open_pos.get("entryPrice") or 0)
                        except (TypeError, ValueError):
                            _entry_px = 0.0
                        _side = open_pos.get("side")
                        _safe = bool(_entry_px) and (
                            (_side == "BUY" and moved >= _entry_px)
                            or (_side == "SELL" and moved <= _entry_px))
                        _already = open_pos.get("breakevenAnnounced")
                        if _safe and not _already:
                            open_pos["breakevenAnnounced"] = True
                            _meta = entry_meta_by_sym.setdefault(_nrm(symbol), {})
                            _meta["breakevenAnnounced"] = True
                            _act = "STOP_BREAKEVEN"
                        else:
                            _act = "STOP_MOVED"
                        if alert_fn:
                            alert_fn(user_id, {"action": _act, "symbol": symbol,
                                               "sl": moved, "side": _side})
                prev_balance = paper_balance
                try:
                    paper_balance = broker.get_balance()
                    dash["balStale"] = False
                    if abs(paper_balance - prev_balance) >= 0.01:
                        user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
                except Exception as e:
                    # Keep trading on the last known balance, but never show a
                    # stale number as fresh — the client compares it to cTrader.
                    dash["balStale"] = True
                    print(f"[UserLoop:{user_id}] balance read error: {e}")
                if not open_pos and dash.get("manualHold"):
                    dash["manualHold"] = False
                # A balance jump with NO position close = deposit/withdrawal.
                # Shift the baseline so profit % keeps measuring TRADING only.
                if (abs(paper_balance - prev_balance) >= 0.01
                        and not (prev_pos and not open_pos)):
                    _cash_delta = paper_balance - prev_balance
                    dash["startBalance"] = dash.get("startBalance", prev_balance) + _cash_delta
                    # The drawdown breaker reads strategy_session["peakBalance"],
                    # which this used to leave untouched — so a withdrawal made
                    # the account look like it had crashed and halted the bot
                    # with no way to clear it.
                    strategies.rescale_peak(prev_balance, paper_balance, user_id=user_id)
                # cTrader executed the SL/TP server-side: the position we were
                # managing vanished between ticks. Tell the client — silence
                # here made broker-side exits invisible in Telegram.
                if (prev_pos and not open_pos
                        and _position_still_open(broker, prev_pos, symbol, user_id)):
                    # Focus rotated off a live position. Not a close — keep
                    # managing it and leave the journal, the risk ladder and
                    # the persisted snapshot alone.
                    prev_pos = None
                if prev_pos and not open_pos:
                    last_close_at = time.time()  # re-entry lock (churn guard)
                    # Ask the broker for THIS position's actual closed-deal
                    # P&L (matches cTrader's own History tab exactly) instead
                    # of estimating from the account balance delta — the
                    # delta silently mixes in any OTHER position that also
                    # closed in the same polling window (multi-position mode)
                    # and never included swap.
                    _deal = None
                    _pos_id = prev_pos.get("positionId")
                    if _pos_id and not cfg.PAPER_TRADING:
                        try:
                            _deal = broker.get_closed_deal_pnl(_pos_id)
                        except Exception as e:
                            print(f"[UserLoop:{user_id}] closed-deal lookup failed: {e}")
                    if _deal is not None:
                        pnl_est = _deal["netPnl"]
                        gross_pnl = _deal["grossPnl"]
                        cost_usd = _deal["commissionUsd"]
                    else:
                        pnl_est = round(paper_balance - prev_balance, 2) if not dash.get("balStale") else None
                        gross_pnl = pnl_est
                        cost_usd = 0.0
                    # The closed position's OWN symbol and price — never the
                    # loop's current focus. Auto-Pilot rotates between ticks, so
                    # by the time a broker-side close is noticed the focus can
                    # already be on a different instrument, and this recorded
                    # the close under it. Live proof from last night:
                    #
                    #   symbol AUDUSD · entry 0.81169 (USDCHF) · exit 0.70484
                    #
                    # A +$24.99 USDCHF win filed as an AUDUSD trade with one
                    # pair's entry and another's exit. _log_trade's symbol guard
                    # caught the contradiction and dropped the entry fields, so
                    # it never poisoned the calibrator — but the label was lost
                    # too, which is why a clean win left the sample count where
                    # it was. `price` belongs to the focus instrument, so it is
                    # only a valid exit when the two agree; the P&L itself comes
                    # from the broker's own closed-deal record either way.
                    _closed_sym = prev_pos.get("symbol") or symbol
                    _exit_px = price if _nrm(_closed_sym) == _nrm(symbol) else None
                    if _exit_px is None:
                        print(f"[UserLoop:{user_id}] {_closed_sym} closed at the broker "
                              f"while focus moved to {symbol} — logging without an "
                              f"exit price rather than {symbol}'s")
                    result = {"action": "BROKER_CLOSE", "symbol": _closed_sym,
                              "side": prev_pos.get("side", ""), "price": _exit_px,
                              "entryPrice": prev_pos.get("entryPrice"),
                              "netPnl": pnl_est, "balance": round(paper_balance, 2),
                              "grossPnl": gross_pnl, "costUsd": cost_usd,
                              "openedAt": prev_pos.get("openedAt"), "time": now_str}
                    # Journal FIRST, then apply the side effects only if it was
                    # a new close. The restart recovery can already have booked
                    # this same close moments earlier; the risk ladder and the
                    # daily P&L must each see it exactly once.
                    _fresh = _log_trade(user_id, result, prev_pos)
                    if _fresh:
                        if pnl_est is not None and pnl_est < 0:
                            last_loss_at = time.time()
                            loss_streak += 1
                        elif pnl_est is not None and pnl_est > 0:
                            loss_streak = 0
                        _persist_risk_state()
                        if pnl_est is not None:
                            strategies.record_trade(pnl_est > 0, pnl_est,
                                                    dash.get("startBalance") or paper_balance,
                                                    user_id=user_id, symbol=_closed_sym)
                        dash["trades"].insert(0, result)
                        dash["trades"] = dash["trades"][:50]
                        if alert_fn:
                            alert_fn(user_id, result)
                    # Clear the snapshot either way — the position is gone.
                    _persist_open_snapshot(None)

                # Client-side protective stop: if the broker somehow holds the
                # position without a stop — or price already crossed it — close
                # at market. A naked position must never survive a tick.
                if open_pos:
                    side_ = open_pos.get("side")
                    stop_ = open_pos.get("stopLoss")
                    if not stop_ and open_pos.get("entryPrice"):
                        pip_g = forex.pip_size(symbol, price)
                        stop_ = (open_pos["entryPrice"] - cfg.STOP_LOSS_PIPS * pip_g
                                 if side_ == "BUY"
                                 else open_pos["entryPrice"] + cfg.STOP_LOSS_PIPS * pip_g)
                    breached = stop_ and ((side_ == "BUY" and price <= stop_) or
                                          (side_ == "SELL" and price >= stop_))
                    if breached:
                        exit_price = price
                        _close_res = None
                        try:
                            _close_res = broker.close_position(symbol)
                            exit_price = (_close_res or {}).get("fillPrice") or price
                            if alert_fn:
                                alert_fn(user_id, {"action": "CLOSE", "symbol": symbol,
                                                   "price": exit_price,
                                                   "reasoning": "🛡 Protective stop — price crossed the stop level; closed at market"})
                        except Exception as e:
                            print(f"[UserLoop:{user_id}] protective close failed: {e}")
                        units_ = open_pos.get("units") or open_pos.get("quantity", 1000)
                        gross = forex.pnl_usd(side_, open_pos["entryPrice"], exit_price, units_, symbol)
                        pv = forex.pip_value_per_unit(symbol, exit_price)
                        # Spread estimate + real broker commission (when the
                        # broker reports one) — cost was silently always $0
                        # before, since a live open_pos read straight from the
                        # broker never carries an "entrySpreadPips" estimate.
                        cost_usd = (open_pos.get("entrySpreadPips", 0.0) * pv * units_
                                   + (_close_res or {}).get("commissionUsd", 0.0))
                        net = gross - cost_usd
                        if cfg.PAPER_TRADING:
                            paper_balance += net
                        else:
                            # LIVE: this branch used to leave paper_balance (the
                            # displayed "balance") completely untouched on a
                            # real close — it's only bumped by `net` in paper
                            # mode above, so the Telegram message reported the
                            # PRE-close balance while claiming a P&L for the
                            # trade that supposedly just happened to it. A
                            # fresh broker read is the authoritative number.
                            try:
                                paper_balance = broker.get_balance()
                            except Exception:
                                paper_balance += net
                        last_loss_at = time.time()
                        last_close_at = time.time()
                        loss_streak += 1
                        _persist_risk_state()
                        strategies.record_trade(net > 0, net,
                                                dash.get("startBalance") or paper_balance,
                                                user_id=user_id, symbol=symbol)
                        result = {"action": "CLOSE", "symbol": symbol, "price": exit_price,
                                  "entryPrice": open_pos.get("entryPrice"),
                                  "side": open_pos.get("entrySide") or open_pos.get("side"),
                                  "initialStop": open_pos.get("initialStop"),
                                  "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
                                  "netPnl": round(net, 2), "balance": round(paper_balance, 2),
                                  "openedAt": open_pos.get("openedAt"), "time": now_str,
                                  "reasoning": "protective stop — closed at market"}
                        _log_trade(user_id, result, open_pos)
                        if cfg.PAPER_TRADING:
                            user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
                        dash["trades"].insert(0, result)
                        dash["trades"] = dash["trades"][:50]
                        open_pos = None
                        dash["openPosition"] = None
                        _persist_open_snapshot(None)
            else:
                if open_pos and open_pos.get("symbol") and open_pos["symbol"] != symbol:
                    symbol = open_pos["symbol"]
                    dash["symbol"] = symbol
                # Reconcile with manual trades (force_trade/force_close write to
                # the shared dash via chat/commands). Adopt a manually-opened
                # position the loop doesn't know about, and clear one closed by
                # hand — otherwise the loop's local state clobbers it next tick.
                dash_pos = dash.get("openPosition")
                if dash_pos and not open_pos:
                    # The adopted position may belong to a DIFFERENT pair than
                    # the one being scanned — a manual /buy on another symbol,
                    # or a stale entry left in the dash by an earlier tick.
                    # Adopting it without moving the loop's focus leaves
                    # `symbol` and `open_pos` describing two different
                    # instruments, and every close built from that pair reports
                    # THIS symbol with the OTHER one's entry price. That is what
                    # put rows like "USDJPY entry 0.81256 exit 158.377" in the
                    # journal: the exit is right, the entry belongs to AUDUSD.
                    # It corrupts realised P&L and the daily-loss tracker too,
                    # because pnl_usd() then prices one pair's move with the
                    # other pair's pip size.
                    #
                    # The symbol reconciliation above runs BEFORE this adoption,
                    # so it never sees the mismatch. Switch focus here instead,
                    # exactly as the single-position sync does, and re-read the
                    # price so stop/target comparisons run against the right
                    # instrument (a stale price always reads as "breached").
                    _dp_sym = dash_pos.get("symbol")
                    if _dp_sym and _nrm(_dp_sym) != _nrm(symbol):
                        _c = None
                        try:
                            _c = broker.get_candles(_dp_sym, cfg.TIMEFRAME, cfg.CANDLES)
                        except Exception as e:
                            print(f"[UserLoop:{user_id}] adopt {_dp_sym}: "
                                  f"candle re-read failed: {e}")
                        if _c:
                            symbol = _dp_sym
                            dash["symbol"] = symbol
                            candles = _c
                            price = candles[-1]["close"]
                            open_pos = dash_pos
                        else:
                            # No fresh price for that pair — skip the adoption
                            # this tick rather than manage a position using
                            # another instrument's price. The next tick retries.
                            print(f"[UserLoop:{user_id}] deferred adopting {_dp_sym} "
                                  f"position — no fresh candles while scanning {symbol}")
                    else:
                        open_pos = dash_pos
                elif open_pos and dash_pos is None and dash.get("_manualClose"):
                    open_pos = None
                    dash["_manualClose"] = False
                # Sync balance if a manual close adjusted it
                dash_bal = dash.get("balance")
                if dash_bal and dash_bal != paper_balance and dash.get("_manualBal"):
                    paper_balance = dash_bal
                    dash["_manualBal"] = False

            dash["balance"] = paper_balance
            # Price the position before publishing it: /status and the web
            # terminal both show floating P&L, and both read it off this dict.
            dash["openPosition"] = _price_open_position(open_pos, symbol, price)
            _float = float((dash["openPosition"] or {}).get("pnlUsd") or 0.0)
            dash["floatingPnl"] = round(_float, 2)
            dash["equityLive"] = round(float(paper_balance or 0) + _float, 2)
            # openCount is read off the broker at the top of the tick; a close
            # that happens later in the SAME tick clears openPosition but
            # leaves the count at 1, and /status falls through to "1 position
            # open — managed by their broker stops" for a position that no
            # longer exists. Only correct it when a single slot is in play:
            # with maxpos > 1 an unfocused position is a real state, not a
            # leftover.
            if dash["openPosition"] is None and dash.get("openCount", 0) <= 1:
                dash["openCount"] = 0

            # ── Paper SL/TP enforcement ──
            # In LIVE mode the broker holds the stop/target server-side, so a hit
            # closes the position and get_open_position() reflects it next tick.
            # In PAPER mode nothing closes the trade unless we check the price
            # ourselves — without this, stops are decorative and a losing paper
            # trade runs forever (only an AI "CLOSE" would ever exit it).
            if cfg.PAPER_TRADING and open_pos:
                hi = candles[-1].get("high", price)
                lo = candles[-1].get("low", price)
                sl = open_pos.get("stopLoss")
                tp = open_pos.get("takeProfit")
                pside = open_pos.get("side")
                hit = None
                if pside == "BUY":
                    if sl and lo <= sl:      hit = "STOP_LOSS"
                    elif tp and hi >= tp:    hit = "TAKE_PROFIT"
                else:  # SELL
                    if sl and hi >= sl:      hit = "STOP_LOSS"
                    elif tp and lo <= tp:    hit = "TAKE_PROFIT"
                if hit:
                    # Fill at the SL/TP level (realistic), not the candle close.
                    exit_price = sl if hit == "STOP_LOSS" else tp
                    units_ = open_pos.get("units", 1000)
                    gross = forex.pnl_usd(pside, open_pos["entryPrice"],
                                          exit_price, units_, symbol)
                    pv = forex.pip_value_per_unit(symbol, exit_price)
                    cost_usd = open_pos.get("entrySpreadPips", 0.0) * pv * units_
                    net = gross - cost_usd
                    paper_balance += net
                    if net < 0:
                        last_loss_at = time.time()
                        loss_streak += 1
                    else:
                        loss_streak = 0
                    result = {"action": "CLOSE", "symbol": symbol,
                              "price": exit_price, "entryPrice": open_pos.get("entryPrice"),
                              "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
                              "netPnl": round(net, 2), "balance": round(paper_balance, 2),
                              "reason": hit, "openedAt": open_pos.get("openedAt"),
                              "time": now_str}
                    _log_trade(user_id, result, open_pos)
                    # Persist so the simulated balance survives a restart.
                    user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
                    last_close_at = time.time()
                    _persist_risk_state()
                    strategies.record_trade(net > 0, net,
                                            dash.get("startBalance") or paper_balance,
                                            user_id=user_id, symbol=symbol)
                    open_pos = None
                    dash["openPosition"] = None
                    dash["balance"] = paper_balance
                    dash["trades"].insert(0, result)
                    dash["trades"] = dash["trades"][:50]
                    if alert_fn:
                        alert_fn(user_id, result)
                    time.sleep(_LOOP_INTERVAL)
                    continue

            ind = indicators.analyze(candles, symbol)
            strat_data = strategies.analyze(candles)

            # Market regime → in AUTO mode it picks the engine, halves risk in
            # violent markets and stands aside in dead ones (premium spec #1).
            regime = strategies.detect_regime(candles, symbol)
            dash["regime"] = regime

            # Refresh the probability calibration roughly every 60 ticks (and
            # once on the first pass), so newly closed trades feed back into
            # the gate without re-reading the journal every few seconds.
            if tick - ev_cal_tick >= 60:
                ev_cal_tick = tick
                ev_calibration = _refresh_ev_calibration()
                # Report the real labelled count even before the threshold is
                # reached — otherwise the operator sees a flat 0 the whole time
                # the bot is collecting and cannot tell progress from a fault.
                _need = getattr(cfg, "EV_MIN_SAMPLES", 30)
                try:
                    _have = ev_engine.labelled_count(user_store.load_trades(user_id))
                except Exception:
                    _have = 0
                dash["evCalibration"] = (
                    {"ready": True, "samples": ev_calibration["samples"],
                     "overall": ev_calibration["overall"], "needed": _need,
                     "mode": getattr(cfg, "EV_GATE_MODE", "shadow")}
                    if ev_calibration else
                    {"ready": False, "samples": _have, "needed": _need,
                     "overall": None,
                     "mode": getattr(cfg, "EV_GATE_MODE", "shadow"),
                     "note": f"collecting labelled trades ({_have}/{_need})"})
            active_mode = cfg.STRATEGY
            regime_block = False
            if active_mode == "auto":
                picked = {"trending": "trend", "ranging": "mean_reversion",
                          "volatile": "breakout"}.get(regime["regime"])
                regime_block = regime["regime"] == "quiet"
                # Neutral default: crypto trends more than it ranges, so a
                # warming-up/unknown regime should default to trend-following,
                # not fading (the forex default).
                #
                # Decided per SYMBOL, not per build. The bot now holds both
                # asset classes on one account, so "what kind of thing is
                # this" is a question about the instrument in front of it —
                # a build-level flag would fade BTC because the process
                # happens to be the forex one.
                _default_mode = ("trend" if (_crypto_build or forex.is_crypto(symbol))
                                 else "mean_reversion")
                active_mode = picked or _default_mode
                dash["strategy"] = f"Auto → {_strategy_label(active_mode)}"

            # ── The strategy module for this tick (blueprint §3/§14) ──
            # The decision now goes through the registry rather than straight
            # into ai.signal_for_mode. The module is a thin adapter over that
            # same engine — equivalence is asserted across 644 comparisons in
            # tests/test_strategy_equivalence.py — so this changes WHERE the
            # decision is made, not WHAT it decides. What it buys is §14:
            # every signal now carries the strategy_id and strategy_version
            # that produced it, so a trade can be traced back to an exact
            # version of an exact strategy.
            #
            # NOT named `market`: that is the apex.market module, used a few
            # lines below for the Market Pulse read.
            _strategy, _frame = None, None
            try:
                _strategy = strategy_api.get(active_mode)
                if _strategy is not None:
                    _frame = strategy_api.Market(
                        candles, symbol=symbol, indicators=ind,
                        strat=strat_data, open_position=open_pos, price=price,
                        balance=paper_balance, timeframe=cfg.TIMEFRAME)
            except Exception as e:
                # Market() validates its inputs and can raise. A registry
                # problem must never stop a live account from trading — fall
                # through to the engine call this replaced.
                print(f"[UserLoop:{user_id}] strategy module unavailable for "
                      f"{active_mode} ({e}) — using the engine directly")
                _strategy, _frame = None, None
            _provenance = strategy_api.provenance_for(active_mode) or {}

            def _rule_signal():
                """This tick's rule verdict, through the module when there is one."""
                if _strategy is not None and _frame is not None:
                    try:
                        return _strategy.signal(_frame)
                    except Exception as e:
                        print(f"[UserLoop:{user_id}] strategy module "
                              f"{active_mode} signal() failed ({e})")
                        # ai.signal_for_mode() answers an UNKNOWN mode with
                        # mean_reversion. For a registry-only strategy that
                        # turns "my strategy broke" into "silently trade a
                        # different strategy", which is worse than not
                        # trading: the client picked one method and would get
                        # another, journalled under the name they chose.
                        if active_mode not in ai.STRATEGY_MODES:
                            return {"action": "HOLD", "confidence": 0,
                                    "criteriaScore": 0, "riskLevel": "LOW",
                                    "reasoning": f"{active_mode} module failed "
                                                 f"({str(e)[:80]}) — holding "
                                                 f"rather than trading a "
                                                 f"different strategy",
                                    "keyFactors": []}
                        print(f"[UserLoop:{user_id}] using the engine directly")
                return ai.signal_for_mode(active_mode, ind, strat_data, open_pos)

            # Market Pulse: store a plain-language read for /market, and ping the
            # user (throttled) when the market gets notable (elevated volatility).
            mp = market.pulse(ind, strat_data, symbol)
            if mp:
                dash["market"] = mp
                if mp.get("notable"):
                    last_mkt_tick = tick

            # Weekend gap protection: this CFD feed goes quiet Fri evening to
            # Sun evening (crypto included — it's 24/5 here, not 24/7). A
            # position ridden into the gap can reopen Sunday far past its own
            # stop-loss, so force-close before the close and stand aside
            # (the unconditional `continue` below also blocks new entries)
            # until the market is back.
            in_weekend_window = market.is_weekend_close_window()
            if not in_weekend_window and was_weekend_closed:
                was_weekend_closed = False
                weekend_failed = set()
                if alert_fn:
                    alert_fn(user_id, {"action": "WEEKEND_REOPEN", "symbol": symbol})

            if in_weekend_window:
                # Flatten EVERY open position, then report what ACTUALLY
                # happened. This block used to announce "any open position was
                # closed" before attempting anything, close only the FOCUSED
                # symbol, and swallow a broker failure with a bare `pass` while
                # still journalling the trade as closed. The result on a live
                # account: the client is told they are flat for the weekend
                # while the position sits open at the broker, carrying exactly
                # the Sunday-gap risk this feature exists to remove.
                _wk_targets = []
                if cfg.PAPER_TRADING:
                    if open_pos:
                        _wk_targets = [{**open_pos,
                                        "symbol": open_pos.get("symbol") or symbol}]
                else:
                    try:
                        _wk_targets = list(broker.get_all_positions() or [])
                    except Exception as e:
                        print(f"[UserLoop:{user_id}] weekend: position list failed "
                              f"({e}) — falling back to the tracked position")
                        if open_pos:
                            _wk_targets = [{**open_pos,
                                            "symbol": open_pos.get("symbol") or symbol}]
                _wk_failed, _wk_closed = set(), 0
                for _wp in _wk_targets:
                    _wsym = _wp.get("symbol") or symbol
                    _close_res = None
                    if not cfg.PAPER_TRADING:
                        try:
                            _close_res = broker.close_position(_wsym)
                        except Exception as e:
                            # Do NOT book a close that did not happen. The
                            # position is still live and still exposed, and
                            # saying otherwise is the whole bug.
                            print(f"[UserLoop:{user_id}] weekend flatten of "
                                  f"{_wsym} FAILED: {e}")
                            _wk_failed.add(_wsym)
                            continue
                        if (_close_res or {}).get("status") == "FLAT":
                            continue   # already gone — nothing to journal
                    _wk_closed += 1
                    open_pos = _wp
                    # `price` belongs to the focused instrument; for any other
                    # position it is the wrong number to value a fill with.
                    exit_price = ((_close_res or {}).get("fillPrice")
                                  or (price if _nrm(_wsym) == _nrm(symbol)
                                      else _wp.get("entryPrice")))
                    units_ = open_pos.get("units") or open_pos.get("quantity", 1000)
                    gross = forex.pnl_usd(open_pos["side"], open_pos["entryPrice"],
                                          exit_price, units_, _wsym)
                    pv = forex.pip_value_per_unit(_wsym, exit_price)
                    cost_usd = (open_pos.get("entrySpreadPips", 0.0) * pv * units_
                               + (_close_res or {}).get("commissionUsd", 0.0))
                    net = gross - cost_usd
                    if cfg.PAPER_TRADING:
                        paper_balance += net
                    else:
                        # LIVE: read the real post-close balance instead of
                        # leaving it at whatever it was before this close —
                        # see the identical fix on the protective-stop close.
                        try:
                            paper_balance = broker.get_balance()
                        except Exception:
                            paper_balance += net
                    if net < 0:
                        last_loss_at = time.time()
                        loss_streak += 1
                    else:
                        loss_streak = 0
                    result = {"action": "CLOSE", "symbol": _wsym, "price": exit_price,
                              "entryPrice": open_pos.get("entryPrice"),
                              "side": open_pos.get("entrySide") or open_pos.get("side"),
                              "initialStop": open_pos.get("initialStop"),
                              "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
                              "netPnl": round(net, 2), "balance": round(paper_balance, 2),
                              "openedAt": open_pos.get("openedAt"), "time": now_str,
                              "reasoning": "Closed before the weekend — avoiding gap risk over Sat/Sun."}
                    _log_trade(user_id, result, open_pos)
                    if cfg.PAPER_TRADING:
                        user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
                    last_close_at = time.time()
                    _persist_risk_state()
                    strategies.record_trade(net > 0, net,
                                            dash.get("startBalance") or paper_balance,
                                            user_id=user_id, symbol=_wsym)
                    open_pos = None
                    dash["openPosition"] = None
                    _persist_open_snapshot(None)
                    dash["balance"] = paper_balance
                    dash["trades"].insert(0, result)
                    dash["trades"] = dash["trades"][:50]
                    if alert_fn:
                        alert_fn(user_id, result)
                # Now — and only now — say what happened. Re-announce when the
                # set of positions we could NOT close changes: still being
                # exposed to the gap is worth a second message, and so is
                # finally getting flat. Neither is worth one every tick.
                if alert_fn and (not was_weekend_closed
                                 or _wk_failed != weekend_failed):
                    alert_fn(user_id, {"action": "WEEKEND_CLOSE", "symbol": symbol,
                                       "closed": _wk_closed,
                                       "failed": sorted(_wk_failed)})
                was_weekend_closed = True
                weekend_failed = _wk_failed
                time.sleep(_LOOP_INTERVAL)
                continue

            # Check risk limits (per-user, from the Strategy Builder)
            # user_id makes the circuit breakers PER-USER. Without it every
            # client shared one global session: user A's peak balance made
            # user B's smaller account read as a huge drawdown (false stop),
            # and the loss-streak/daily counters never tracked anyone.
            stop_check = strategies.should_stop(
                paper_balance, dash["startBalance"],
                max_daily_loss_pct=getattr(cfg, "MAX_DAILY_LOSS_PCT", 3.0),
                max_dd_pct=getattr(cfg, "MAX_DD_PCT", 20.0),
                user_id=user_id, symbol=symbol)
            # Publish the verdict for the UI. strategies.should_stop() advances
            # the peak-balance and daily-reset state as a side effect, so the
            # Telegram screens must NEVER call it themselves just to draw a
            # badge — they read this instead. Observability only: nothing
            # downstream branches on it.
            dash["riskGuard"] = {"halted": bool(stop_check["stop"]),
                                 "reasons": list(stop_check["reasons"]),
                                 "ts": time.time()}
            if stop_check["stop"]:
                print(f"[UserLoop:{user_id}] Strategy stop: {stop_check['reasons']}")
                # Alert once on the edge into the stop, not every tick for the
                # rest of the day it stays true — this used to spam "Trading
                # paused" every 5 minutes non-stop once a daily limit hit.
                if alert_fn and not was_stopped:
                    alert_fn(user_id, {"action": "STOP", "reasons": stop_check["reasons"]})
                was_stopped = True
                time.sleep(_LOOP_INTERVAL)
                continue
            was_stopped = False

            # Heartbeat — let user know bot is alive even during quiet markets
            if tick % _HEARTBEAT_TICKS == 0 and alert_fn:
                pos_info = (f" | Position: {open_pos['side']} @ {open_pos['entryPrice']}"
                            if open_pos else " | No open position")
                alert_fn(user_id, {
                    "action": "HEARTBEAT",
                    "symbol": symbol,
                    "price": price,
                    "balance": paper_balance,
                    "tick": tick,
                    "posInfo": pos_info,
                })

            # Calendar push. NEWS_WARN, further down, only speaks when a setup
            # was actually refused — so on a day the bot finds no trade, a
            # release the client cares about passes in silence. This reaches
            # out on the release itself: a heads-up while it is still ahead,
            # and the all-clear once it passes.
            #
            # The tick is five minutes, which is the natural rate limit; the
            # module claims each event so a message cannot repeat across
            # containers or restarts. It scans the currencies this client
            # actually trades, and never raises — a notification path must not
            # be able to break the loop that carries it.
            if alert_fn:
                _news_ccy = set()
                for _w in (list(watchlist) + [symbol]):
                    _news_ccy.update(_currency_legs(_w))
                for _msg in news_alerts.due(
                        user_id, _news_ccy,
                        user=user_store.load(user_id),
                        guard_on=bool(getattr(cfg, "NEWS_FILTER", True))):
                    alert_fn(user_id, _msg)

            # AI signal with rule-based fallback. The client chooses via
            # /aiconfirm: ON = every rule entry is double-checked by the AI
            # (can block weak setups, costs a few seconds per candidate);
            # OFF = pure rule engine — instant, zero API cost.
            _sig_t0 = time.time()
            _ai_reused = False
            try:
                if getattr(cfg, "AI_CONFIRM", True):
                    # get_signal already returns early on CLOSE/HOLD without
                    # touching the model, so the only call worth avoiding is a
                    # repeat on a candidate that has not changed — the rule
                    # engine saying BUY on the same bar, at the same price,
                    # tick after tick while some other gate holds the entry.
                    _rule_pre = _rule_signal()
                    _rule_act = _rule_pre.get("action", "HOLD")
                    _now_feat = {
                        "price": price, "atr": (ind or {}).get("atr"),
                        "spread_pips": _recent_spread(),
                        "regime": (regime or {}).get("regime"),
                        "bar_time": candles[-1].get("time") if candles else None,
                        "expires_at": time.time() + max(
                            60, sentinel.default_ttl(cfg.TIMEFRAME)),
                    }
                    _prev_ai = _last_ai.get(_nrm(symbol))
                    _need, _why = (True, "no_prior")
                    if _prev_ai and _prev_ai.get("rule_action") == _rule_act:
                        _need, _why = sentinel.should_refresh(
                            _prev_ai.get("features"), _now_feat)
                    if _rule_act not in ("BUY", "SELL"):
                        signal = _rule_pre          # no AI call would happen
                    elif not _need:
                        signal = dict(_prev_ai["signal"])
                        _ai_reused = True
                        print(f"[UserLoop:{user_id}] AI read reused for {symbol} "
                              f"({_rule_act}, nothing changed) — no API call")
                    else:
                        signal = ai.get_signal(ind, paper_balance, open_pos, strat_data,
                                           mode=active_mode,
                                           symbol=symbol,
                                           timeframe=cfg.TIMEFRAME,
                                           sl_pips=cfg.STOP_LOSS_PIPS,
                                           tp_pips=cfg.TAKE_PROFIT_PIPS,
                                           risk_pct=cfg.RISK_PER_TRADE,
                                           min_confidence=cfg.MIN_CONFIDENCE,
                                           candles=candles,
                                           regime=regime,
                                           spread_pips=_recent_spread())
                        _last_ai[_nrm(symbol)] = {
                            "features": _now_feat, "signal": dict(signal),
                            "rule_action": _rule_act}
                else:
                    signal = _rule_signal()
            except Exception as e:
                print(f"[UserLoop:{user_id}] AI error: {e}")
                if tick - last_ai_error_tick >= _AI_ERROR_THROTTLE and alert_fn:
                    alert_fn(user_id, {
                        "action": "AI_ERROR",
                        "reason": str(e),
                        "symbol": symbol,
                    })
                    last_ai_error_tick = tick
                signal = _rule_signal()

            # §14: whichever branch produced this verdict — the module, a
            # reused AI read, or the AI-enhanced path through ai.get_signal —
            # it carries the strategy that produced it. Stamped here rather
            # than in each branch so a new branch cannot forget to.
            if _provenance:
                signal = {**signal, **_provenance}

            action = signal.get("action", "HOLD")
            confidence = signal.get("confidence", 0)

            # ── Publish the Sentinel's view of this symbol ──
            # Until now the AI's opinion existed only for the duration of the
            # call above. Storing it — with an expiry — is what makes "what
            # does the bot currently think about EURUSD" a question with an
            # answer, and what stops a stale read being acted on later.
            if _sentinel_mode != "off":
                try:
                    _ttl = (getattr(cfg, "SENTINEL_TTL_S", 0)
                            or sentinel.default_ttl(cfg.TIMEFRAME))
                    _bar = candles[-1].get("time") if candles else None
                    # Institutional read: one composite number per symbol,
                    # carrying the coverage that produced it. Attached to the
                    # Sentinel state so the AI's verdict and the data behind it
                    # travel together and expire together.
                    _inst = institutional.build(symbol,
                        _institutional_observations(
                            symbol, ind, regime, _recent_spread()))
                    dash["institutional"] = institutional.describe(_inst)
                    _state = sentinel.build_state(
                        symbol=symbol, action=action, confidence=confidence,
                        regime=(regime or {}).get("regime"),
                        reasoning=signal.get("reasoning", ""),
                        ttl_s=_ttl,
                        price=price, atr=(ind or {}).get("atr"),
                        spread_pips=_recent_spread(), bar_time=_bar,
                        institutional_proxy=_inst.get("institutional_proxy"),
                        data_quality=_inst.get("data_quality"),
                        institutional_usable=_inst.get("usable"))
                    # Alert on a CHANGE of mind, never on the state itself.
                    # This loop ticks every few minutes; a message per tick
                    # would be a notification every 5 minutes forever, and the
                    # useful signal — "the AI just flipped on EURUSD" — would
                    # be buried in it. Compare against the previous published
                    # action for this symbol, before overwriting it.
                    _prev = _signals.get(symbol)
                    _prev_act = (_prev or {}).get("action")
                    _signals.publish(_state)
                    dash["sentinel"] = sentinel.describe(_state)
                    if (alert_fn and _prev_act and _prev_act != action
                            and "HOLD" not in (_prev_act, action)):
                        # HOLD↔BUY/SELL churns constantly as indicators wobble
                        # around their thresholds. Only a genuine reversal —
                        # BUY→SELL or SELL→BUY — is worth interrupting someone.
                        alert_fn(user_id, {
                            "action": "SENTINEL_FLIP", "symbol": symbol,
                            "from": _prev_act, "to": action,
                            "conf": _state.get("confidence"),
                            "regime": _state.get("regime"),
                            "reasoning": signal.get("reasoning", ""),
                        })
                except Exception as e:
                    print(f"[UserLoop:{user_id}] sentinel publish failed: {e}")

            # ── Refused setups: follow what we did NOT take ──
            # A filter is invisible from outside. Recording the blocked entry
            # as a phantom and following it on the same prices turns "the AI
            # blocked 14 trades" into "those 14 would have lost 9R" — the only
            # way to tell a filter that saves money from one that is removing
            # the profitable setups.
            if signal.get("blockedAction") and not open_pos:
                try:
                    _psl, _ptp = _phantom_levels(
                        price, signal["blockedAction"], ind, symbol)
                    _ph = shadow.open_shadow(
                        user_id, symbol, signal["blockedAction"], price,
                        _psl, _ptp,
                        blocked_by=signal.get("blockedBy", "filter"),
                        reasoning=signal.get("blockedReasoning", ""),
                        confidence=signal.get("blockedConfidence"))
                    if _ph and alert_fn:
                        alert_fn(user_id, {"action": "SHADOW_OPEN", **_ph})
                except Exception as e:
                    print(f"[UserLoop:{user_id}] shadow open failed: {e}")

            # Advance any phantom on this symbol against the latest bar.
            try:
                _bar = candles[-1] if candles else {}
                for _evt in shadow.update(user_id, symbol, _bar.get("high"),
                                          _bar.get("low"), price):
                    if not alert_fn:
                        continue
                    _p = _evt["phantom"]
                    if _evt["kind"] == "milestone":
                        alert_fn(user_id, {"action": "SHADOW_MOVE",
                                           "symbol": _p["symbol"], "r": _evt["r"]})
                    else:
                        alert_fn(user_id, {"action": "SHADOW_RESULT", **_p,
                                           "scoreboard": shadow.scoreboard(user_id)})
            except Exception as e:
                print(f"[UserLoop:{user_id}] shadow update failed: {e}")

            # NOTE on MIN_CONFIDENCE: this gate is weaker than it looks. The
            # rule engine only emits BUY/SELL at |score| >= 3, which maps to
            # confidence 76 (ai.py: 52 + 8*score); the AI paths adjust that to
            # 84 when they agree and 71 when neutral. So the LOWEST confidence
            # any firing signal can carry is 71 — at the default threshold of
            # 68 this comparison never rejects anything. It only starts
            # filtering above 71, and only bites the pure rule path above 76.
            # Real entry quality control lives in the EV gate below, which
            # scores on a measured probability instead of an indicator count.
            entry_ok = action in ("BUY", "SELL") and not open_pos and confidence >= cfg.MIN_CONFIDENCE
            # Signal TTL: if analysis took too long the market moved on. The AI
            # confirmation itself takes 2-8s when it runs (only on BUY/SELL
            # candidates) — a 5s TTL made a successful-but-slow AI confirm
            # cancel its own entry. 12s tolerates a slow confirm and still
            # rejects genuinely stale signals (retry cascades take 30s+).
            _sig_age = time.time() - _sig_t0
            if entry_ok and _sig_age > 12.0:
                entry_ok = False
                _skip(f"signal TTL expired ({_sig_age:.1f}s > 12s)")
            # ── Multi-position gates (live) ──
            if entry_ok and not cfg.PAPER_TRADING:
                if all_positions is None:
                    entry_ok = False  # couldn't read positions — don't stack blind
                elif open_count >= maxpos:
                    entry_ok = False
                    _skip(f"at max positions ({open_count}/{maxpos})")
                elif _nrm(symbol) in open_syms:
                    entry_ok = False  # already holding this symbol
                else:
                    # Correlation guard: cap how many positions share the same
                    # USD direction, so 5 trades aren't secretly one USD bet.
                    new_exp = forex.usd_exposure(symbol, action)
                    if new_exp != 0:
                        same_dir = sum(1 for e in open_exposure if e == new_exp)
                        if same_dir >= 2:
                            entry_ok = False
                            _skip(f"correlation guard — already {same_dir} {'USD-long' if new_exp>0 else 'USD-short'} positions")
            # Daily trade cap. The Strategy Builder shows every client a
            # "Max trades/day" figure and bakes one into each risk preset
            # (Low 6 / Medium 10 / High 15), but nothing read the setting —
            # someone who picked Low risk was told 6 and got unlimited.
            #
            # Enforced HERE rather than in strategies.should_stop(): a trade
            # count is a reason to stop OPENING, not to halt the account. The
            # breaker there fires a STOP alert and stands the whole loop down,
            # which would also abandon management of an open position.
            # 0 = unlimited, so the cap can be switched off deliberately
            # instead of by accident.
            if entry_ok:
                _max_td = int(getattr(cfg, "MAX_TRADES_DAY", 0) or 0)
                if _max_td > 0:
                    _done = strategies.get_session(user_id).get("dailyTrades", 0)
                    if _done >= _max_td:
                        entry_ok = False
                        _skip(f"daily trade cap reached ({_done}/{_max_td})")
            # Quiet regime (AUTO): no edge, no trade.
            if entry_ok and regime_block:
                entry_ok = False
                _skip(regime.get("label", "market too quiet"))
            if entry_ok and getattr(cfg, "HTF_CONFIRM", False):
                htf_c = None
                try:
                    htf_c = broker.get_candles(symbol, "1h", 60)
                except Exception:
                    pass
                if htf_c and len(htf_c) >= 55:
                    htf_dir = strategies.htf_trend(htf_c)
                    if (action == "BUY" and htf_dir == "BEARISH") or \
                       (action == "SELL" and htf_dir == "BULLISH"):
                        entry_ok = False
                        _skip(f"HTF gate: {action} blocked by H1 {htf_dir} trend")
            # Post-loss cooldown: the worst trade after a stop-out is the next
            # one taken 5 minutes later in the same falling knife.
            if entry_ok and last_loss_at and time.time() - last_loss_at < _LOSS_COOLDOWN_MIN * 60:
                left = int((_LOSS_COOLDOWN_MIN * 60 - (time.time() - last_loss_at)) / 60) + 1
                entry_ok = False
                _skip(f"post-loss cooldown ({left}m left)")
            if entry_ok and last_close_at and last_loss_at and last_close_at == last_loss_at and \
               time.time() - last_close_at < _CLOSE_COOLDOWN_MIN * 60:
                left = int((_CLOSE_COOLDOWN_MIN * 60 - (time.time() - last_close_at)) / 60) + 1
                entry_ok = False
                _skip(f"post-loss-close cooldown ({left}m left)")
            if entry_ok:
                # ── Cost control: the spread is forex's hidden fee. Skip a too-wide
                #    spread and refuse trades whose target can't clear a round-trip
                #    spread plus a safety margin (break-even guard). ──
                bid, ask = 0.0, 0.0
                try:
                    bid, ask = broker.get_bid_ask(symbol)
                    spread = forex.spread_pips(bid, ask, symbol)
                except Exception:
                    spread = 0.0
                _health_check(spread=spread)
                # Cost-aware edge (premium spec #5): round-trip commission in
                # pips joins the spread — the target must clear REAL costs.
                comm_pips = 0.0
                try:
                    comm_rt = float(os.getenv("COMMISSION_PER_LOT_RT", "7"))
                    pv_lot = forex.pip_value_per_unit(symbol, price) * 100_000
                    comm_pips = comm_rt / pv_lot if pv_lot > 0 else 0.0
                except Exception:
                    comm_pips = 0.0
                if health["degraded"]:
                    entry_ok = False
                    _skip(f"broker health: {dash.get('brokerHealth', 'degraded')}")
                # Spread guard — crypto uses a %-of-price limit (pip-count limits
                # are meaningless across crypto's varied pip sizes); forex keeps
                # the pip limit.
                max_spread = getattr(cfg, "MAX_SPREAD_PIPS", 3.0)
                max_spread_pct = getattr(cfg, "MAX_SPREAD_PCT", 0)
                spread_pct = ((ask - bid) / price * 100) if price > 0 else 0.0
                if not entry_ok:
                    pass
                elif max_spread_pct > 0 and spread_pct > max_spread_pct:
                    print(f"[UserLoop:{user_id}] skip entry — spread {spread_pct:.2f}% > {max_spread_pct:g}% limit")
                    entry_ok = False
                    # Let Auto-Pilot rotate to a tradeable symbol instead of
                    # camping on this one until its spread normalises. Alert only
                    # on the FIRST detection per block window — repeating the
                    # same 'holding off' every cycle reads as a stuck bot.
                    was_blocked = spread_blocked.get(_nrm(symbol), 0) > time.time()
                    if not was_blocked:  # arm ONCE — don't renew the 30-min TTL every tick
                        spread_blocked[_nrm(symbol)] = time.time() + 1800
                    _skip(f"spread too wide ({spread_pct:.2f}% > {max_spread_pct:g}%)")
                elif max_spread_pct <= 0 and spread > max_spread:
                    print(f"[UserLoop:{user_id}] skip entry — spread {spread:.1f}p > {max_spread}p limit")
                    entry_ok = False
                    was_blocked = spread_blocked.get(_nrm(symbol), 0) > time.time()
                    if not was_blocked:
                        spread_blocked[_nrm(symbol)] = time.time() + 1800
                    _skip(f"spread too wide ({spread:.1f}p > {max_spread:g}p)")
                # Break-even guard (pip-based) only applies to the forex pip model;
                # crypto's %-spread guard above already ensures the edge clears costs.
                elif max_spread_pct <= 0 and cfg.TAKE_PROFIT_PIPS <= (spread + comm_pips) * 1.5:
                    print(f"[UserLoop:{user_id}] skip entry — TP {cfg.TAKE_PROFIT_PIPS:g}p doesn't clear costs {spread + comm_pips:.1f}p")
                    entry_ok = False
                    _skip(f"edge too thin: TP {cfg.TAKE_PROFIT_PIPS:g}p vs real costs {spread + comm_pips:.1f}p (spread+commission)")

            # Flash-crash circuit breaker: skip entry when the latest candle's
            # range is extreme (>1.2% for FX majors; crypto is far more volatile,
            # so the threshold is raised via FLASH_SPIKE_PCT).
            if entry_ok and _flash_spike(candles, flash_spike_pct_for(cfg, symbol)):
                entry_ok = False
                _skip("flash-crash guard: extreme candle range", alert=False)
                if alert_fn and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                    last_warn_tick = tick
                    alert_fn(user_id, {"action": "FLASH_WARN", "symbol": symbol})

            # Session filter (Strategy Builder): only trade the sessions the user
            # picked. [] = all sessions. Crypto ignores this (runs 24/5 on the CFD
            # feed). Forex reacts to session opens, so honouring it is real.
            if entry_ok and not _crypto_build:
                want_sess = getattr(cfg, "SESSION_FILTER", []) or []
                if want_sess:
                    try:
                        now_sess = (market.session() or {}).get("label", "")
                    except Exception:
                        now_sess = ""
                    if now_sess and not any(w.lower() in now_sess.lower() for w in want_sess):
                        entry_ok = False
                        _skip(f"session filter: {now_sess} not in {', '.join(want_sess)}")

            # News guard: stand aside around high-impact releases for either
            # currency in the pair. Fail-open (no event / feed down → trades).
            # Gated by the user's news_filter toggle (Strategy Builder).
            if entry_ok and getattr(cfg, "NEWS_FILTER", True):
                # The calendar matches on ISO currency codes ("USD", "EUR"), so
                # the symbol has to be split into its two legs. split("_") only
                # does that for an underscore symbol like EUR_USD — every
                # Auto-Pilot symbol is written EURUSD, where it returns
                # ["EURUSD"], matches no currency, and the guard silently passed
                # every high-impact release. A 15-pip stop on 1m bars is exactly
                # what NFP/CPI/FOMC destroys, so this guard was doing nothing
                # precisely where it mattered most.
                ev = news.high_impact_window(_currency_legs(symbol))
                if ev:
                    entry_ok = False
                    _skip(f"news guard: {ev.get('title', 'high-impact event') if isinstance(ev, dict) else ev}",
                          alert=False)
                    if alert_fn and tick - last_warn_tick >= _SKIP_WARN_THROTTLE:
                        last_warn_tick = tick
                        alert_fn(user_id, {"action": "NEWS_WARN", "symbol": symbol, "event": ev})

            # Automation level: how much this client lets the bot do alone.
            # Re-read it each time so a change takes effect without a restart
            # (entry_ok is rare, so the extra load is cheap).
            #
            # Both non-full levels REFUSE the entry — they can only ever stop
            # an order that would otherwise have gone out, never cause one.
            #   approval → propose it and wait for a tap  (the old copilot)
            #   signals  → post the setup and place nothing at all
            if entry_ok:
                _auto = automation.mode(user_store.load(user_id))
                if _auto == "approval":
                    _suggest_trade(user_id, signal, symbol, price, alert_fn)
                    entry_ok = False
                elif _auto == "signals":
                    _signal_only(user_id, signal, symbol, price, alert_fn)
                    entry_ok = False

            # A shadow gate needs candidates, and every candidate was being
            # thrown away before it got one. The Sentinel and institutional
            # checks live inside `if entry_ok:` below — deliberately, since in
            # enforce mode they must be the last word before an order goes
            # out. The side effect is that in SHADOW mode they only ever saw
            # setups that had already cleared every other gate. The HTF gate
            # refuses most candidates long before that (eight in a row on one
            # symbol today), so the shadow sample was a single verdict.
            #
            # Evaluate the verdict on refused candidates too, for the record
            # only: entry_ok is already False, nothing downstream reads this,
            # and no Telegram message is sent — these fire on ordinary refused
            # ticks and would be pure noise. The log is the right home for a
            # sample you intend to count later.
            if (not entry_ok and _sentinel_mode != "off"
                    and action in ("BUY", "SELL")):
                try:
                    _sig_sh = _signals.get(symbol)
                    _sok_sh, _sreason_sh = sentinel.decide(
                        _sig_sh, action,
                        min_confidence=getattr(
                            cfg, "SENTINEL_MIN_CONFIDENCE", None),
                        min_ev_r=None, risk_ok=True)
                    dash["sentinelGate"] = (f"{_sreason_sh} "
                                            f"(moot — entry already refused)")
                    print(f"[UserLoop:{user_id}] Sentinel shadow on a refused "
                          f"candidate: would "
                          f"{'ALLOW' if _sok_sh else 'BLOCK'} {action} "
                          f"{symbol} — {_sreason_sh} "
                          f"({sentinel.describe(_sig_sh)})")
                except Exception as e:
                    # Observability must never be able to break a live loop.
                    print(f"[UserLoop:{user_id}] sentinel shadow error: {e}")

            ev_verdict = None
            if entry_ok:
                pip = forex.pip_size(symbol, price)
                _crypto = _crypto_build
                stop_pips_eff = cfg.STOP_LOSS_PIPS
                # Dynamic ATR stops (premium spec #10): SL = 1.5×ATR, TP = 3×ATR
                # — distances that breathe with the instrument's volatility.
                # ── Structural stops: let the setup define the trade ──
                # The fibonacci swing on M1 is a median ~17 pips wide, so a flat
                # 15/30 stop-and-target is 0.9x and 1.8x the ENTIRE swing the
                # signal came from, while the setup's own objective — price
                # returning to the swing extreme — sits a median 6 pips away.
                # The trade is asked to do something the signal never predicted.
                # Here the stop goes a buffer beyond the swing origin and the
                # target to the swing extreme, so RR is whatever the structure
                # actually offers rather than a number picked in advance.
                _structural = False
                if getattr(cfg, "STRUCTURAL_STOPS", False):
                    _fib = (ind or {}).get("fibonacci") or {}
                    _tgt = _fib.get("target")
                    _rng = _fib.get("swingRange") or 0
                    if _tgt and _rng > 0:
                        # Stop beyond the swing origin the level retraced from,
                        # plus room for spread and noise — a stop sitting exactly
                        # on structure gets taken by the wick that confirms it.
                        _buf = max(4.0 * spread * pip, 0.15 * _rng)
                        if action == "BUY":
                            _sl = min(_fib.get("swingLow", price), price) - _buf
                            _sl_d, _tp_d = price - _sl, _tgt - price
                        else:
                            _sl = max(_fib.get("swingHigh", price), price) + _buf
                            _sl_d, _tp_d = _sl - price, price - _tgt
                        _min_rr = float(getattr(cfg, "STRUCTURAL_MIN_RR", 1.3))
                        if _sl_d > 0 and _tp_d > 0 and (_tp_d / _sl_d) >= _min_rr:
                            sl_dist, tp_dist = _sl_d, _tp_d
                            stop_pips_eff = forex.to_pips(sl_dist, symbol, price)
                            _structural = True
                        else:
                            # No room between the level and its objective. Skip
                            # rather than fall back to a target the structure
                            # does not support.
                            entry_ok = False
                            _skip(f"structural RR too low "
                                  f"({(_tp_d / _sl_d) if _sl_d > 0 else 0:.2f} "
                                  f"< {_min_rr})")

                # Structure already set the levels; ATR and the fixed-pip
                # fallbacks below only run when it did not.
                atr_v = 0.0
                if not _structural and getattr(cfg, "ATR_STOPS", False):
                    try:
                        atr_v = float(ind.get("atr") or 0)
                    except (TypeError, ValueError):
                        atr_v = 0.0
                if _structural:
                    pass
                elif atr_v > 0:
                    # Wider stop + far target so trades breathe and profits run.
                    sl_dist, tp_dist = 2.5 * atr_v, 5.0 * atr_v
                    # FLOOR: on a 5-min candle the ATR of a calm FX pair is only
                    # ~2 pips, so 1.5×ATR is a sub-noise stop that the spread
                    # alone triggers instantly — the churn that bled the account.
                    # Never let the stop sit inside spread+noise: at least 4×
                    # the current spread and a sane per-class pip floor.
                    # Crypto's magnitude pip makes 10×pip a 0.01-0.1% sub-noise
                    # floor; use a %-of-price floor (~0.4%) so the stop clears
                    # crypto tick noise. Forex keeps the 10-pip floor.
                    floor_abs = (0.004 * price) if _crypto else (20.0 * pip)
                    min_stop = max(4.0 * spread * pip, floor_abs)
                    if sl_dist < min_stop:
                        sl_dist = min_stop
                        tp_dist = 2.0 * sl_dist  # keep RR ≥ 1:2
                    stop_pips_eff = forex.to_pips(sl_dist, symbol, price)
                elif _crypto:
                    # No ATR available on crypto → %-of-price stop, not the
                    # sub-noise fixed-pip default (20 pips = 0.02% on SOL).
                    sl_dist = 0.012 * price   # ~1.2% stop
                    tp_dist = 0.024 * price   # ~2.4% target (RR 1:2)
                    stop_pips_eff = forex.to_pips(sl_dist, symbol, price)
                else:
                    sl_dist = cfg.STOP_LOSS_PIPS * pip
                    tp_dist = cfg.TAKE_PROFIT_PIPS * pip
                    if tp_dist < sl_dist:
                        # RR guard: a target smaller than the stop bleeds the
                        # account through costs no matter the win rate.
                        tp_dist = 2.0 * sl_dist
                        try:
                            signal.setdefault("keyFactors", []).append("TP auto-raised to 2×SL (RR guard)")
                        except Exception:
                            pass
                # Round to broker-grade precision — raw float math produced
                # 0.7017249999999999-style prices in orders and alerts.
                sl_price = round(price - sl_dist if action == "BUY" else price + sl_dist, 6)
                tp_price = round(price + tp_dist if action == "BUY" else price - tp_dist, 6)

                # ── EV gate (V2 decision core) ──
                # Placed HERE, after the stop and target are decided, so it
                # scores the trade the bot is actually about to send. Run
                # earlier it had to invent its own SL/TP, and its internal
                # model produces a ~4-pip stop where this loop places 15 —
                # which quadruples the cost in R and made the gate demand a
                # 52% win rate for a trade that breaks even at 38%.
                #
                # Shadow by default: it records the verdict it WOULD have
                # reached without changing behaviour, so the filter can be
                # judged on real data before it may block a live trade.
                _ev_mode = getattr(cfg, "EV_GATE_MODE", "shadow")
                if _ev_mode != "off":
                    try:
                        _atr_pips = 0.0
                        try:
                            _atr_raw = float(ind.get("atr") or 0)
                            if _atr_raw > 0:
                                _atr_pips = forex.to_pips(_atr_raw, symbol, price)
                        except (TypeError, ValueError):
                            _atr_pips = 0.0
                        _dd_pct = 0.0
                        try:
                            _peak = float(strategies.get_session(user_id).get("peakBalance") or 0)
                            if _peak > 0:
                                _dd_pct = (paper_balance - _peak) / _peak * 100.0
                        except Exception:
                            _dd_pct = 0.0
                        ev_verdict = ev_engine.evaluate(
                            confidence=confidence,
                            calibration=ev_calibration,
                            atr_pips=_atr_pips,
                            spread_pips=spread,
                            regime=(regime or {}).get("regime"),
                            equity=paper_balance,
                            drawdown_pct=_dd_pct,
                            sl_pips=stop_pips_eff,
                            tp_pips=forex.to_pips(tp_dist, symbol, price),
                            min_probability=getattr(cfg, "EV_MIN_PROBABILITY", None),
                        )
                        if not ev_verdict["approved"]:
                            if _ev_mode == "enforce":
                                entry_ok = False
                                _skip(f"EV gate: {ev_verdict['reason']} "
                                      f"(p={ev_verdict['probability']}, "
                                      f"EV={ev_verdict['ev_r']}R)")
                            else:
                                print(f"[UserLoop:{user_id}] EV shadow: WOULD BLOCK "
                                      f"{action} {symbol} — {ev_verdict['reason']} "
                                      f"(conf={confidence}, p={ev_verdict['probability']}, "
                                      f"need>{ev_verdict['min_probability']}, "
                                      f"EV={ev_verdict['ev_r']}R, "
                                      f"cost={ev_verdict['cost_r']}R, "
                                      f"BE={ev_verdict['breakeven_p']})")
                        else:
                            print(f"[UserLoop:{user_id}] EV {_ev_mode}: allow {action} "
                                  f"{symbol} p={ev_verdict['probability']} "
                                  f"EV={ev_verdict['ev_r']}R")
                    except Exception as e:
                        # A gate that crashes must never take the bot down with
                        # it; in enforce mode a broken gate means stand aside,
                        # not trade blind.
                        print(f"[UserLoop:{user_id}] EV gate error: {e}")
                        if _ev_mode == "enforce":
                            entry_ok = False
                            _skip("EV gate unavailable")

                # ── Sentinel decision gate ──
                # The last word before the order goes out: is there a FRESH AI
                # read for this symbol, and does it agree with what we are
                # about to send? Without the freshness half, a verdict computed
                # against a chart that has since moved on is indistinguishable
                # from one computed a second ago.
                if _sentinel_mode != "off":
                    try:
                        _sig = _signals.get(symbol)
                        _sok, _sreason = sentinel.decide(
                            _sig, action,
                            min_confidence=getattr(
                                cfg, "SENTINEL_MIN_CONFIDENCE", None),
                            min_ev_r=None,   # the EV gate above owns this
                            risk_ok=True)    # and the risk engine owns this
                        dash["sentinelGate"] = _sreason
                        if not _sok:
                            if _sentinel_mode == "enforce":
                                entry_ok = False
                                _skip(f"Sentinel: {_sreason} "
                                      f"({sentinel.describe(_sig)})")
                            else:
                                print(f"[UserLoop:{user_id}] Sentinel shadow: "
                                      f"WOULD BLOCK {action} {symbol} — "
                                      f"{_sreason} ({sentinel.describe(_sig)})")
                            # A refusal is rare (it needs an entry candidate)
                            # and always tells you something, so unlike the
                            # state itself it is worth a message every time.
                            if alert_fn:
                                alert_fn(user_id, {
                                    "action": "SENTINEL_BLOCK", "symbol": symbol,
                                    "wanted": action, "reason": _sreason,
                                    "mode": _sentinel_mode,
                                    "state": sentinel.describe(_sig),
                                })
                    except Exception as e:
                        # A broken gate must never stop a live account.
                        print(f"[UserLoop:{user_id}] sentinel gate error: {e}")

                # ── Institutional contradiction check ──
                # Separate from the Sentinel gate and separately switchable,
                # because it answers a different question: not "is the AI's
                # read fresh and in agreement" but "does the wider picture —
                # positioning, rates, macro, liquidity — point the other way".
                # It only ever fires on a CONTRADICTION from a state that is
                # itself usable. Thin coverage is already handled inside
                # institutional.build(); refusing on low data quality here
                # would stop trading whenever a feed hiccups, which is a
                # denial of service dressed up as caution.
                if _inst_mode != "off":
                    try:
                        _ib = institutional.action_bias(_inst)
                        if (_inst.get("usable") and _ib in ("BUY", "SELL")
                                and _ib != action):
                            _imsg = (f"institutional read is {_ib} "
                                     f"({institutional.describe(_inst)})")
                            if _inst_mode == "enforce":
                                entry_ok = False
                                _skip(f"Institutional: {_imsg}")
                            else:
                                print(f"[UserLoop:{user_id}] Institutional shadow: "
                                      f"WOULD BLOCK {action} {symbol} — {_imsg}")
                            if alert_fn:
                                alert_fn(user_id, {
                                    "action": "SENTINEL_BLOCK", "symbol": symbol,
                                    "wanted": action, "reason": "AI_DISAGREES",
                                    "mode": _inst_mode,
                                    "state": institutional.describe(_inst),
                                })
                    except Exception as e:
                        print(f"[UserLoop:{user_id}] institutional gate error: {e}")

                risk_mult = strategies.druckenmiller_multiplier(
                    confidence, signal.get("criteriaScore", 0),
                    strat_data.get("livermore"), strat_data.get("turtle"))
                if loss_streak >= 3:
                    risk_mult *= 0.25
                elif loss_streak == 2:
                    risk_mult *= 0.5
                if regime.get("regime") == "volatile":
                    risk_mult *= 0.5
                # Size off the account's starting balance (adjusted only for
                # real deposits/withdrawals — see where startBalance shifts
                # above), not the live balance. Sizing from the live balance
                # made the same setup produce a different position every
                # time as ordinary trading P&L nudged it up or down; a client
                # comparing two AUDUSD trades a day apart shouldn't see two
                # different lot sizes for the exact same risk. Loss-streak and
                # volatile-regime reductions (risk_mult below) still shrink it
                # when conditions call for it — that's a safety cut, not drift.
                sizing_balance = dash.get("startBalance") or paper_balance
                _lev = leverage_for_symbol(broker, cfg, symbol)
                units = forex.calc_units(sizing_balance, per_trade_risk,
                                         stop_pips_eff, symbol, price,
                                         leverage=_lev, mult=risk_mult)
                floor = forex.safe_min_units(symbol, paper_balance, price,
                                             _lev, cfg.MARGIN_CAP)
                if floor == 0:
                    _skip("account too small for minimum lot on this instrument")
                    entry_ok = False
                if not entry_ok:
                    pass  # margin too small — skip to CLOSE handling below
                else:
                    units = forex.round_units(max(units, floor), symbol)

                    # Balance-relative TP: instead of a fixed pip count that
                    # means less and less as the account grows (or more and
                    # more as it shrinks), size the TP distance so a full win
                    # nets TP_TARGET_PCT of the current balance for THIS
                    # trade's actual position size. Clamped to 2x-20x the SL
                    # distance so it can't collapse below the RR guard or
                    # stretch out to a target the trade will realistically
                    # never reach.
                    tgt_pct = getattr(cfg, "TP_TARGET_PCT", 0)
                    if tgt_pct > 0 and units > 0:
                        pv = forex.pip_value_per_unit(symbol, price)
                        pip_sz = forex.pip_size(symbol, price)
                        if pv > 0 and pip_sz > 0:
                            target_usd = sizing_balance * (tgt_pct / 100.0)
                            needed_pips = target_usd / (units * pv)
                            tp_dist_dyn = needed_pips * pip_sz
                            tp_dist = max(2.0 * sl_dist, min(tp_dist_dyn, 20.0 * sl_dist))
                            tp_price = round(price + tp_dist if action == "BUY" else price - tp_dist, 6)

                    # Spread re-check: verify spread is still acceptable
                    # right before execution — it may have widened since analysis.
                    _skip_exec = False
                    try:
                        _rb, _ra = broker.get_bid_ask(symbol)
                        _rs = forex.spread_pips(_rb, _ra, symbol)
                        _rs_pct = ((_ra - _rb) / price * 100) if price > 0 else 0.0
                        _msp = getattr(cfg, "MAX_SPREAD_PCT", 0)
                        _msp_pip = getattr(cfg, "MAX_SPREAD_PIPS", 3.0)
                        if _msp > 0 and _rs_pct > _msp:
                            _skip_exec = True
                            _skip(f"spread widened before exec ({_rs_pct:.2f}% > {_msp:g}%)")
                        elif _msp <= 0 and _rs > _msp_pip:
                            _skip_exec = True
                            _skip(f"spread widened before exec ({_rs:.1f}p > {_msp_pip:g}p)")
                        else:
                            # Anchor to the side we actually fill on, not the
                            # mid. A cTrader long fills at the ASK and its
                            # SL/TP trigger on the BID, so a stop placed
                            # sl_dist below the mid is really sl_dist + half a
                            # spread away, and the target is half a spread
                            # nearer than intended. That silently turns a 30/15
                            # trade into ~29/16 — RR 2.00 becomes 1.82 and the
                            # break-even win rate moves 33.3% → 35.4%. Same
                            # trade, same win rate, strictly better expectancy.
                            price = round(_ra if action == "BUY" else _rb, 6)
                            sl_price = round(price - sl_dist if action == "BUY" else price + sl_dist, 6)
                            tp_price = round(price + tp_dist if action == "BUY" else price - tp_dist, 6)
                    except Exception:
                        pass
                    if _skip_exec:
                        entry_ok = False
                    else:
                        try:
                            from apex import control as _ctl
                            _ctl.event("order", f"{action} {symbol} units={units} @~{price} "
                                       f"SL={sl_price} TP={tp_price}", user_id=user_id)
                        except Exception:
                            pass
                        order_ok = True
                        _order_res = None
                        # Ownership, revalidated at the last possible moment.
                        # The lease is renewed on a timer, so between that
                        # renewal and this order another container may have
                        # taken over — the deploy overlap is measured in
                        # seconds and so is this gap. On a real-money account
                        # an unreadable lease counts as NOT owned: a second
                        # container managing the same positions is worse than
                        # a missed entry.
                        # The automatic path uses the SAME gate as manual, AI
                        # and control-plane orders. One definition of a safe
                        # order, entered from four places.
                        _decision, _rid = gates.authorize_order(
                            user_id, symbol=symbol, side=action, units=units,
                            sl=sl_price, tp=tp_price, origin="signal",
                            dash=dash)
                        gates.audit(user_id, f"{action} {symbol}", _decision,
                                    origin="signal", rid=_rid)
                        if not _decision:
                            order_ok = False
                            print(f"[UserLoop:{user_id}] BLOCKED {action} {symbol}: "
                                  f"{_decision.reason} — {_decision.detail}")
                            _skip(f"{_decision.reason}")
                            if alert_fn:
                                alert_fn(user_id, {
                                    "action": ("DUPLICATE_BLOCKED"
                                               if "DUPLICATE" in _decision.reason
                                               else "OWNERSHIP_BLOCKED"),
                                    "symbol": symbol, "side": action,
                                    "units": units, "reason": _decision.reason})
                        else:
                            try:
                                _order_res = broker.place_order(action, units, symbol, sl=sl_price, tp=tp_price)
                                ledger.record(_rid, _order_res)
                            except Exception as oe:
                                order_ok = False
                                # The claim stands. A submit that raised may
                                # still have reached the broker, and retrying
                                # in the next few seconds is exactly how one
                                # intent becomes two positions. The next tick
                                # reads the real position list and settles it.
                                print(f"[UserLoop:{user_id}] place_order error: {oe}")

                        if _order_res and _order_res.get("status") == "UNPROTECTED":
                            # Open at the broker with no stop attached, and the
                            # safety close did not go through. Nothing here can
                            # fix it remotely — the client has to be told, now,
                            # and told exactly what to do.
                            order_ok = False
                            print(f"[UserLoop:{user_id}] {symbol} is OPEN AND "
                                  f"UNPROTECTED — alerting the client")
                            if alert_fn:
                                alert_fn(user_id, {"action": "UNPROTECTED",
                                                   "symbol": symbol,
                                                   "price": _order_res.get("fillPrice")})
                        elif _order_res and _order_res.get("status") == "SAFETY_CLOSED":
                            # A real position opened and was immediately closed
                            # at the broker because the stop-loss couldn't be
                            # attached — this used to vanish as a swallowed
                            # exception (no P&L logged, entry retried next
                            # cycle on the same broken symbol every ~5min).
                            # Price and log it like any other closed trade.
                            order_ok = False
                            entry_fill = _order_res.get("fillPrice") or price
                            exit_fill = _order_res.get("exitFillPrice") or entry_fill
                            gross = forex.pnl_usd(action, entry_fill, exit_fill, units, symbol)
                            pv = forex.pip_value_per_unit(symbol, exit_fill)
                            cost_usd = spread * pv * units + _order_res.get("commissionUsd", 0.0)
                            net = gross - cost_usd
                            if cfg.PAPER_TRADING:
                                paper_balance += net
                            else:
                                # SAFETY_CLOSED only ever happens on a real
                                # broker order — read the real post-close
                                # balance instead of leaving it stale.
                                try:
                                    paper_balance = broker.get_balance()
                                except Exception:
                                    paper_balance += net
                            if net < 0:
                                last_loss_at = time.time()
                                loss_streak += 1
                            elif net > 0:
                                loss_streak = 0
                            result = {"action": "CLOSE", "symbol": symbol, "price": exit_fill,
                                      "entryPrice": entry_fill, "grossPnl": round(gross, 2),
                                      "costUsd": round(cost_usd, 2), "netPnl": round(net, 2),
                                      "balance": round(paper_balance, 2), "time": now_str,
                                      "reasoning": "broker rejected the stop-loss attach — "
                                                   "position closed immediately for safety"}
                            _log_trade(user_id, result, open_pos)
                            if cfg.PAPER_TRADING:
                                user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
                            last_close_at = time.time()
                            _persist_risk_state()
                            strategies.record_trade(net > 0, net,
                                                    dash.get("startBalance") or paper_balance,
                                                    user_id=user_id, symbol=symbol)
                            dash["trades"].insert(0, result)
                            dash["trades"] = dash["trades"][:50]
                            if alert_fn:
                                alert_fn(user_id, result)
                            # Stand aside on this symbol so Auto-Pilot rotates
                            # away instead of retrying the same broker-side
                            # rejection every cycle.
                            spread_blocked[_nrm(symbol)] = time.time() + 900

                        if order_ok:
                            if cfg.PAPER_TRADING:
                                open_pos = {"side": action, "entryPrice": price,
                                            "symbol": symbol, "units": units,
                                            "quantity": units, "stopLoss": sl_price, "takeProfit": tp_price,
                                            "entrySpreadPips": spread, "openedAt": now_str}
                            else:
                                try:
                                    open_pos = broker.get_open_position(symbol)
                                except Exception:
                                    open_pos = None
                                open_pos = open_pos or {"side": action, "entryPrice": price,
                                                        "symbol": symbol, "units": units,
                                                        "quantity": units, "stopLoss": sl_price,
                                                        "takeProfit": tp_price, "openedAt": now_str}

                            # Decision snapshot — what was true when we decided
                            # to enter. _log_trade copies these onto the closed
                            # trade so ev.calibrate() has labelled examples to
                            # learn from; without it every closed trade is an
                            # unlabelled accounting row and the probability
                            # model can never be built.
                            #
                            # entrySpreadPips also feeds the realised-cost
                            # calculation on close. A live position read back
                            # from the broker never carries it, so before this
                            # the cost of every live trade was booked as 0.
                            try:
                                open_pos.setdefault("entrySpreadPips", spread)
                                open_pos.update({
                                    "entryConfidence": confidence,
                                    "entryRegime": (regime or {}).get("regime"),
                                    "entryAtr": atr_v or None,
                                    "entrySlPips": round(float(stop_pips_eff), 2),
                                    "entryTpPips": round(
                                        forex.to_pips(tp_dist, symbol, price), 2),
                                    "entrySide": action,
                                    "entryProbability": (ev_verdict or {}).get("probability"),
                                    "entryEvR": (ev_verdict or {}).get("ev_r"),
                                    # §14: read off the signal rather than
                                    # active_mode, so what is recorded is what
                                    # actually decided — including the case
                                    # where the verdict came from a reused AI
                                    # read taken under an earlier mode.
                                    "entryStrategyId": signal.get("strategy_id"),
                                    "entryStrategyVersion": signal.get("strategy_version"),
                                })
                                # Keep a copy OUTSIDE the position dict. The
                                # next tick throws this dict away and replaces
                                # it with a fresh broker read; without the copy
                                # the snapshot lives for one tick and every
                                # closed trade is journalled unlabelled.
                                entry_meta_by_sym[_nrm(symbol)] = _entry_meta(open_pos)
                            except Exception as _e:
                                print(f"[UserLoop:{user_id}] entry snapshot failed: {_e}")

                            dash["openPosition"] = open_pos
                            # Pin R now, off the REAL fill and the stop we sent.
                            # This is the only moment both are known: from the
                            # next tick on the broker reports the current stop,
                            # which starts moving as soon as the trail engages.
                            _fill = open_pos.get("entryPrice") or price
                            entry_risk_by_sym[_nrm(symbol)] = abs(float(_fill) - float(sl_price))
                            _persist_open_snapshot({**open_pos, "symbol": symbol,
                                                    "initialStop": sl_price})
                            result = {"action": action, "symbol": symbol, "confidence": confidence,
                                      "price": price, "spreadPips": round(spread, 1), "time": now_str,
                                      "stopLoss": sl_price, "takeProfit": tp_price,
                                      "reasoning": signal.get("reasoning", ""),
                                      "keyFactors": signal.get("keyFactors", [])}
                            dash["trades"].insert(0, result)
                            dash["trades"] = dash["trades"][:50]
                            if alert_fn:
                                alert_fn(user_id, result)

            elif action == "CLOSE" and open_pos and dash.get("manualHold"):
                # /buy - /sell trades belong to the USER: the strategy engine
                # must not close them (a mean-reversion bot would instantly
                # exit a manual entry placed near the mean). SL/TP rule them.
                pass
            elif action == "CLOSE" and open_pos and _profit_too_small_to_take(
                    open_pos, price, symbol, entry_risk_by_sym.get(_nrm(symbol)),
                    user_id):
                # Winner cut short. Hold instead — see _profit_too_small_to_take.
                pass
            elif action == "CLOSE" and open_pos and _ride_instead_of_close(
                    broker, cfg, open_pos, symbol, price,
                    entry_risk_by_sym.get(_nrm(symbol)), ind, user_id):
                # Running hard with the trend behind it — the stop has been
                # pulled up to protect the gain and the trade keeps running.
                dash["openPosition"] = open_pos
                _persist_open_snapshot(_with_initial_stop(open_pos, symbol))
            elif action == "CLOSE" and open_pos:
                # A strategy exit is NOT always a win — label it honestly.
                # And a close the broker never confirmed is not an exit at
                # all: this used to swallow the error with a bare `pass`,
                # then journal the trade, move the balance and alert the
                # client for a position still open at the broker. Same
                # defect the weekend flatten had, on the path that runs far
                # more often.
                _close_res, _close_ok = None, True
                try:
                    _close_res = broker.close_position(symbol)
                except Exception as _ce:
                    _close_ok = False
                    print(f"[UserLoop:{user_id}] strategy exit on {symbol} "
                          f"FAILED: {_ce} — position stays open, retrying next tick")
                if not _close_ok:
                    # Keep managing it. The next tick tries again, and the
                    # broker-side stop is still in force meanwhile.
                    dash["openPosition"] = open_pos
                    _persist_open_snapshot(_with_initial_stop(open_pos, symbol))
                    if alert_fn:
                        alert_fn(user_id, {"action": "EXIT_FAILED", "symbol": symbol})
                else:
                    # Use the broker's actual execution price when it gives us one —
                    # the last fetched candle close is a stale proxy and can differ
                    # from the real fill by real spread/slippage, quietly
                    # misreporting P&L (this is why a client's own broker showed a
                    # different result than what the bot logged for the same trade).
                    exit_price = (_close_res or {}).get("fillPrice") or price
                    units_ = open_pos.get("units") or open_pos.get("quantity", 1000)
                    gross = forex.pnl_usd(open_pos["side"], open_pos["entryPrice"],
                                          exit_price, units_, symbol)
                    pv = forex.pip_value_per_unit(symbol, exit_price)
                    # Spread estimate + real broker commission — a live open_pos
                    # read straight from the broker never carries an
                    # "entrySpreadPips" estimate, so cost silently read $0 on
                    # every real close; commissionUsd (best-effort, see
                    # ctrader._extract_commission) closes that gap when the
                    # broker reports one.
                    cost_usd = (open_pos.get("entrySpreadPips", 0.0) * pv * units_
                               + (_close_res or {}).get("commissionUsd", 0.0))
                    net = gross - cost_usd
                    if cfg.PAPER_TRADING:
                        paper_balance += net
                    else:
                        # LIVE: this is the exact bug behind a client seeing a
                        # "Net P&L +$X, Balance $Y" message where Y didn't move
                        # by X at all — this branch bumped paper_balance only in
                        # PAPER mode, so a live close reported the balance from
                        # BEFORE the trade closed. Read the real one instead.
                        try:
                            paper_balance = broker.get_balance()
                        except Exception:
                            paper_balance += net
                    if net < 0:
                        last_loss_at = time.time()
                        loss_streak += 1
                    elif net > 0:
                        loss_streak = 0
                    result = {"action": "CLOSE", "symbol": symbol, "price": exit_price,
                              "entryPrice": open_pos.get("entryPrice"),
                              "side": open_pos.get("entrySide") or open_pos.get("side"),
                              "initialStop": open_pos.get("initialStop"),
                              "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
                              "netPnl": round(net, 2), "balance": round(paper_balance, 2),
                              "openedAt": open_pos.get("openedAt"), "time": now_str,
                              "reasoning": signal.get("reasoning", "")}
                    _log_trade(user_id, result, open_pos)
                    if cfg.PAPER_TRADING:
                        # Persist so the simulated balance survives a restart.
                        user_store.update(user_id, {"paper_balance": round(paper_balance, 2)})
                    last_close_at = time.time()
                    _persist_risk_state()
                    strategies.record_trade(net > 0, net,
                                            dash.get("startBalance") or paper_balance,
                                            user_id=user_id, symbol=symbol)
                    open_pos = None
                    dash["openPosition"] = None
                    _persist_open_snapshot(None)
                    dash["balance"] = paper_balance
                    dash["trades"].insert(0, result)
                    dash["trades"] = dash["trades"][:50]
                    if alert_fn:
                        alert_fn(user_id, result)

        except Exception as e:
            print(f"[UserLoop:{user_id}] Error: {e}")

        time.sleep(_LOOP_INTERVAL)


def _entitled(user_id):
    """May this user have a live trading loop at all?

    Access was enforced on the COMMAND path and nowhere else. A chat that is not
    entitled got "🔒 Activation required" for every command it sent — while
    start_all() on boot and the watchdog every 180s happily kept its trading
    loop alive off `active: True`, sending "Bot alive" heartbeats and taking
    positions. Observed live: a chat whose /terminal and /restart were both
    refused was still receiving heartbeats for a $27k account.

    Two independent reasons a legitimate client can look unlisted, and neither
    may cost them their bot:
      • the access store is unreachable (Redis hiccup) → allowed_state says
        "unknown", never "denied";
      • the local-JSON backend is wiped on every redeploy → fall back to the
        stored license_key, exactly as _license_ok does on the command path.

    Only a definite "denied" with no license on file stops a loop.
    """
    user_id = str(user_id)
    try:
        state = access.allowed_state(user_id)
    except Exception as e:
        print(f"[UserLoop:{user_id}] access check failed ({e}) — allowing")
        return True
    if state == "allowed":
        return True
    if state == "unknown":
        print(f"[UserLoop:{user_id}] access store unreachable — allowing "
              f"(a store outage must not stop a paying client's bot)")
        return True
    try:
        if user_store.load(user_id).get("license_key"):
            return True     # returning customer, access store wiped by a redeploy
    except Exception:
        pass
    return False


def start(user_id, alert_fn=None):
    user_id = str(user_id)
    if not _entitled(user_id):
        # Clear `active` too, or the watchdog resurrects this every 180s.
        print(f"[UserLoop] REFUSED start for {user_id}: not entitled "
              f"(no access grant and no license on file)")
        try:
            user_store.update(user_id, {"active": False})
        except Exception:
            pass
        stop(user_id)
        return False
    # Take the cross-container lease BEFORE spawning anything. A deploy overlaps
    # the old and new containers, and without this both start a loop for the
    # same cTrader account — the generation token below cannot see the other
    # process. None means no shared backend: uncontended, so carry on.
    if ownership.acquire(user_id) is False:
        print(f"[UserLoop] REFUSED start for {user_id}: another instance owns it")
        return False
    # Renew on a thread of its own, not from the trading tick.
    ownership.start_renewer(user_id, on_lost=ownership.mark_lost)

    with _lock:
        if user_id in _loops and _loops[user_id]["running"]:
            return False
        # Generation token: a stop()+start() restart can race a thread that is
        # asleep in its 5-minute tick — it wakes, sees the NEW entry's
        # running=True and keeps trading alongside the new loop (two engines
        # fighting over one account: open/close churn). The token lets the old
        # thread recognise it was replaced and exit.
        gen = _loops.get(user_id, {}).get("gen", 0) + 1
        _loops[user_id] = {"running": True, "gen": gen, "dash": {}}

    user_store.update(user_id, {"active": True})
    t = threading.Thread(target=_loop, args=(user_id, alert_fn, gen), daemon=True)
    t.start()
    with _lock:
        _loops[user_id]["thread"] = t
    print(f"[UserLoop] Started for user {user_id}")
    return True


def stop(user_id):
    user_id = str(user_id)
    with _lock:
        if user_id not in _loops:
            return False
        _loops[user_id]["running"] = False
    user_store.update(user_id, {"active": False})
    # Hand the lease back rather than making a replacement wait out the TTL.
    # release_claim only deletes a key that is still ours, so a stop() racing
    # a takeover cannot revoke the new owner's lease.
    try:
        ownership.stop_renewer(user_id)
        ownership.release(user_id)
    except Exception as e:
        print(f"[UserLoop:{user_id}] lease release failed (expires on its own): {e}")
    print(f"[UserLoop] Stopped for user {user_id}")
    return True


def is_running(user_id):
    user_id = str(user_id)
    with _lock:
        return _loops.get(user_id, {}).get("running", False)


def live_balance(user_id):
    """Read the account balance from the broker RIGHT NOW (real mode only).
    /status and the terminal must never show a number older than the request
    — a withdrawal between loop ticks made the cached figure look broken."""
    user = user_store.load(str(user_id))
    if user.get("paper", True):
        return None
    try:
        broker, _cfg = _make_broker(user)
        bal = broker.get_balance()
        user_store.update(str(user_id), {"paper_balance": round(bal, 2)})
        d = get_dash(str(user_id))
        if d:
            d["balance"] = bal
        return bal
    except Exception as e:
        print(f"[UserLoop:{user_id}] live_balance failed: {e}")
        return None


def get_dash(user_id):
    user_id = str(user_id)
    with _lock:
        return _loops.get(user_id, {}).get("dash", {})


def start_all(alert_fn=None):
    """Restart loops for all previously active users (after server reboot).

    start() does the entitlement check, so a chat that lost access is not
    resurrected here either — a redeploy used to hand every stale `active: True`
    record a fresh trading loop regardless of whether the chat could still use
    the bot."""
    for uid in user_store.all_active():
        start(uid, alert_fn)


def start_watchdog(alert_fn=None, interval=180):
    """Self-healing watchdog: every `interval` seconds, restart any user marked
    active whose loop thread has died (crash, unhandled error, server hiccup).
    Runs 24/7 inside the bot process, so overnight recovery needs no operator and
    no external session — start() is idempotent, so healthy loops are untouched."""
    def _run():
        while True:
            time.sleep(interval)
            try:
                for uid in (user_store.all_active() or []):
                    # Enforcement sweep. start() refuses new loops for chats
                    # that lost access, but a loop ALREADY running when the
                    # grant was revoked kept trading forever — nothing ever
                    # re-checked it. This is the only place that notices.
                    if not _entitled(uid):
                        print(f"[Watchdog] {uid} is no longer entitled — "
                              f"stopping its loop")
                        try:
                            stop(uid)
                            user_store.update(uid, {"active": False})
                            from apex import control as _ctl
                            _ctl.event("watchdog", "stopped unentitled loop",
                                       user_id=uid)
                        except Exception as e:
                            print(f"[Watchdog] stop failed for {uid}: {e}")
                        continue
                    if not is_running(uid):
                        print(f"[Watchdog] active loop for {uid} is down — restarting")
                        try:
                            start(uid, alert_fn)
                            from apex import control as _ctl
                            _ctl.event("watchdog", f"restarted dead loop for {uid}", user_id=uid)
                        except Exception as e:
                            print(f"[Watchdog] restart failed for {uid}: {e}")
            except Exception as e:
                print(f"[Watchdog] sweep error: {e}")
    threading.Thread(target=_run, daemon=True).start()
    print(f"[Watchdog] self-healing watchdog ON (every {interval}s)")


def _flash_spike(candles, pct):
    """True if the latest candle's high-low range exceeds `pct` of price — a
    flash-crash/spike signature. Fail-safe to False on bad data."""
    try:
        c = candles[-1]
        hi, lo = float(c["high"]), float(c["low"])
        ref = float(c.get("close") or c.get("open") or hi) or hi
        return ref > 0 and (hi - lo) / ref >= pct
    except Exception:
        return False


def _suggest_trade(user_id, signal, symbol, price, alert_fn):
    """Copilot mode: store a pending proposal and notify the user to approve it,
    instead of auto-executing. One open suggestion at a time (5-min window)."""
    user = user_store.load(user_id)
    pend = user.get("pending_suggestion")
    now = time.time()
    if pend and now - pend.get("ts", 0) < 300:
        return
    user_store.update(user_id, {"pending_suggestion": {
        "side": signal["action"], "symbol": symbol, "ts": now}})
    if alert_fn:
        alert_fn(user_id, {"action": "SUGGEST", "symbol": symbol, "side": signal["action"],
                           "price": price, "confidence": signal.get("confidence"),
                           "reasoning": signal.get("reasoning", ""),
                           "keyFactors": signal.get("keyFactors", [])})


_SIGNAL_REPEAT_S = 300


def _signal_only(user_id, signal, symbol, price, alert_fn):
    """Signals-Only mode: report the setup and place NOTHING.

    Deliberately not a copilot suggestion with the buttons removed. A pending
    suggestion is a promise the bot will act when tapped; here there is nothing
    to tap and nothing is stored to execute later, so the record must not grow
    a `pending_suggestion` that a stale ✅ Approve button could still redeem.

    Throttled per (symbol, side): a setup that stays valid re-qualifies on
    every tick, and a client who asked for signals wants the setup once, not
    once every five minutes for an hour.
    """
    side = signal.get("action")
    now = time.time()
    last = user_store.load(user_id).get("last_signal") or {}
    if (last.get("symbol") == symbol and last.get("side") == side
            and now - float(last.get("ts") or 0) < _SIGNAL_REPEAT_S):
        return
    user_store.update(user_id, {"last_signal": {"symbol": symbol, "side": side,
                                                "ts": now}})
    if alert_fn:
        alert_fn(user_id, {"action": "SIGNAL", "symbol": symbol, "side": side,
                           "price": price, "confidence": signal.get("confidence"),
                           "reasoning": signal.get("reasoning", ""),
                           "keyFactors": signal.get("keyFactors", [])})


def pending_suggestion(user_id):
    """Return the user's pending copilot suggestion ({side,symbol,ts}) or None."""
    return user_store.load(str(user_id)).get("pending_suggestion")


def clear_suggestion(user_id):
    """Drop the pending copilot suggestion (after approve/reject)."""
    user_store.update(str(user_id), {"pending_suggestion": None})


# A broker that answered "no" and a broker that did not answer are not the
# same event, and collapsing them into `{"ok": False}` is how a client gets
# told their order failed when it is sitting open in their account.
#
# The distinction is drawn on the transport, not on the message text: a
# rejection arrives as a reply, while a timeout, a dropped socket or a
# half-written frame means the request may well have been executed and the
# answer is what went missing. Anything we cannot place in either category is
# treated as AMBIGUOUS, because that is the reading that cannot cause a second
# order to be sent.
_DEFINITE_REJECTIONS = (
    "insufficient", "not enough", "rejected", "invalid", "not found",
    "no such", "market closed", "not tradeable", "not tradable",
    "position not open", "forbidden", "unauthor", "denied",
)
_AMBIGUOUS_MARKERS = (
    "timed out", "timeout", "connection", "reset by peer", "broken pipe",
    "eof", "unreachable", "temporarily", "no response", "closed socket",
    "ssl",
)


def broker_result_ambiguous(err) -> bool:
    """True when the broker's answer does not establish whether it executed."""
    text = str(err or "").lower()
    if not text:
        return True
    if any(m in text for m in _DEFINITE_REJECTIONS):
        return False
    if any(m in text for m in _AMBIGUOUS_MARKERS):
        return True
    return True


def force_trade(user_id, side, symbol=None, lots=None):
    """Open a manual trade immediately (called from AI assistant or /buy /sell commands).
    If lots is specified, use that lot size instead of auto-calculating from risk."""
    user_id = str(user_id)
    user = user_store.load(user_id)

    # Every order origin converges here, on the same financial safety layer the
    # automatic path uses. Manual trades do not have to invent a strategy
    # signal — but they do have to clear the same entitlement, risk, ownership
    # and idempotency checks, because an order is an order whoever asked.
    # (Sizing happens below; the gate is re-entered with the real units.)
    broker, cfg = _make_broker(user)
    sym = (symbol or cfg.SYMBOL).upper()
    if getattr(cfg, "PRODUCT", "forex") == "crypto":
        if not forex.is_crypto(sym):
            return {"ok": False, "error": f"{sym} isn't a crypto instrument — this is a "
                                          "crypto bot. Try e.g. BTCUSD or ETHUSD."}
    else:
        # `is_tradeable` now covers FX, metals AND crypto. Indices, stocks and
        # ETFs are still refused, and deliberately: they need per-exchange
        # trading calendars and quote-currency conversion in sizing, and
        # neither exists yet. Accepting them would not fail loudly — it would
        # size a position in the wrong currency and trade a closed exchange.
        if not forex.is_tradeable(sym):
            return {"ok": False, "error": f"{sym} isn't tradeable here — this bot trades "
                                          "forex, metals and crypto. Try e.g. EUR_USD, "
                                          "XAUUSD or BTCUSD."}
    try:
        candles = broker.get_candles(sym, cfg.TIMEFRAME, 5)
        price = candles[-1]["close"] if candles else 0.0
    except Exception:
        price = 0.0
    if not price:
        return {"ok": False, "error": "Could not fetch price"}

    try:
        bid, ask = broker.get_bid_ask(sym)
        spread = forex.spread_pips(bid, ask, sym)
    except Exception:
        spread = 0.0

    pip = forex.pip_size(sym, price)
    # Size a manual /buy the SAME way the autonomous bot does — ATR-based with
    # a noise floor — so it's never tiny because of a leftover wide fixed /sl.
    stop_pips_eff = cfg.STOP_LOSS_PIPS
    try:
        ind_m = indicators.analyze(broker.get_candles(sym, cfg.TIMEFRAME, 60) or [])
        atr_m = float(ind_m.get("atr") or 0)
    except Exception:
        atr_m = 0.0
    if getattr(cfg, "ATR_STOPS", True) and atr_m > 0:
        sl_dist = 2.0 * atr_m
        min_stop = max(4.0 * spread * pip, 15.0 * pip)
        if sl_dist < min_stop:
            sl_dist = min_stop
        tp_dist = 2.5 * sl_dist
        stop_pips_eff = forex.to_pips(sl_dist, sym, price)
    else:
        sl_dist = cfg.STOP_LOSS_PIPS * pip
        tp_dist = (max(cfg.TAKE_PROFIT_PIPS, 2.0 * cfg.STOP_LOSS_PIPS)
                   if cfg.TAKE_PROFIT_PIPS < cfg.STOP_LOSS_PIPS else cfg.TAKE_PROFIT_PIPS) * pip
    sl_price = round(price - sl_dist if side == "BUY" else price + sl_dist, 6)
    tp_price = round(price + tp_dist if side == "BUY" else price - tp_dist, 6)

    balance = user.get("paper_balance") or cfg.PAPER_BALANCE
    dash = get_dash(user_id)
    if dash:
        balance = dash.get("balance", balance)

    if lots is not None and lots > 0:
        units = forex.lots_to_units(lots, sym)
    else:
        # Same per-instrument leverage as the automatic path. A manual /buy on
        # BTCUSD must not be margined as though it were a currency pair.
        units = forex.calc_units(balance, cfg.RISK_PER_TRADE, stop_pips_eff, sym, price,
                                 leverage=leverage_for_symbol(broker, cfg, sym))
    units = forex.round_units(max(units, forex.min_units(sym)), sym)

    try:
        from apex import control as _ctl
        _ctl.event("order", f"{side} {sym} units={units} @~{price} "
                   f"SL={sl_price} TP={tp_price} (manual)", user_id=user_id)
    except Exception:
        pass
    # Same ownership gate as the automatic path. A manual order from the
    # control plane is still a real order, and the instance handling the HTTP
    # request is not necessarily the one that owns this user's account.
    _own_ok, _own_why = ownership.may_trade(
        user_id, live=not user.get("paper", True))
    if not _own_ok:
        print(f"[UserLoop:{user_id}] manual {side} {sym} refused: {_own_why}")
        return {"ok": False, "error": f"not the owning instance ({_own_why})"}

    _decision, _rid = gates.authorize_order(
        user_id, symbol=sym, side=side, units=units, sl=sl_price, tp=tp_price,
        origin="manual", user=user)
    gates.audit(user_id, f"{side} {sym}", _decision, origin="manual", rid=_rid)
    _claim_ok, _claim_why = _decision.allowed, _decision.reason
    if not _claim_ok:
        # Manual /buy and the MCP open_trade land here. A double-tap on the
        # Telegram button is the everyday version of the same bug.
        return {"ok": False, "error": "duplicate order blocked — an identical "
                                      "order was sent moments ago"}
    try:
        ledger.record(_rid, broker.place_order(side, units, sym,
                                               sl=sl_price, tp=tp_price))
    except Exception as e:
        # The idempotency claim STANDS. It was taken before the broker was
        # called, so an identical retry is refused by the ledger rather than
        # reaching the broker a second time — which is the whole reason the
        # claim is taken first.
        return {"ok": False, "error": str(e), "side": side, "symbol": sym,
                "ambiguous": broker_result_ambiguous(e)}

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    open_pos = {"side": side, "entryPrice": price, "symbol": sym,
                "units": units, "stopLoss": sl_price, "takeProfit": tp_price,
                # Record the original stop so the loop trails this manual trade
                # off its real R too — a /buy gets the same exit quality as an
                # autonomous entry.
                "initialStop": sl_price,
                "entrySpreadPips": spread, "openedAt": now_str}
    _persist_open_position(user_id, cfg, open_pos)

    with _lock:
        loop_data = _loops.get(user_id, {})
    if loop_data:
        dash = loop_data.get("dash", {})
        dash["openPosition"] = open_pos
        dash["manualHold"] = True  # user's trade — engine keeps hands off, SL/TP manage
        result = {"action": side, "symbol": sym, "confidence": 99,
                  "price": price, "spreadPips": round(spread, 1), "time": now_str}
        trades = dash.get("trades", [])
        trades.insert(0, result)
        dash["trades"] = trades[:50]

    return {"ok": True, "side": side, "symbol": sym, "price": price,
            "units": units, "spread": round(spread, 1),
            "sl": round(sl_price, 5), "tp": round(tp_price, 5)}


def list_broker_accounts(user):
    """The broker's own answer to "which accounts does this token hold, and is
    each one real money" — exposed here rather than imported by the caller.

    The UI layer has to be able to re-establish the environment from the
    account itself rather than from a stored flag, and this is the same call
    the OAuth callback makes to build that list in the first place. Putting it
    here keeps the architectural invariant intact: broker construction lives in
    the trading core, and everything else asks the core.

    Returns [] rather than raising for a missing token; a broker that refuses
    or times out still raises, because "we could not confirm" is a fact the
    caller must be able to tell its client apart from "there are none".
    """
    token = (user or {}).get("ctrader_access_token")
    if not token:
        return []
    from apex.brokers import ctrader as _ct
    if not _ct.is_configured():
        raise RuntimeError("broker connection is not configured")
    return _ct.list_accounts(token) or []


def read_candles(user_id, symbol=None, count=50, timeframe=None):
    """Market data for one user, without handing the caller their credentials.

    The AI assistant used to assemble its own broker config — access token,
    refresh token and account id copied out of the user record into a local
    namespace — twice, in two places, purely to read candles. That is a direct
    broker credential path inside the module that talks to a language model,
    and it is the kind that later grows an order call. Broker construction
    already lives here; this exposes the read and nothing else.

    Returns [] rather than raising: a chat reply degrades, it does not crash.
    """
    try:
        user = user_store.load(str(user_id))
        broker, bcfg = _make_broker(user)
        sym = (symbol or bcfg.SYMBOL).upper()
        return broker.get_candles(sym, timeframe or bcfg.TIMEFRAME, int(count)) or []
    except Exception as e:
        print(f"[UserLoop:{user_id}] read_candles failed: {e}")
        return []


def force_close(user_id, origin="manual", emergency=False):
    """Close the open position immediately (AI assistant, /close, control plane).

    Routed through gates.authorize_close so every close origin gets the same
    controls. Before this it reached the broker with none: a non-owning
    instance could close a position the owner was managing, and a timed-out
    close could be retried into closing a position that had been reopened in
    between — the response was lost, not the execution.

    `emergency=True` is a deliberate, audited override of the ownership check
    for the operator's emergency path. It does not remove idempotency.
    """
    user_id = str(user_id)
    user = user_store.load(user_id)

    with _lock:
        dash = _loops.get(user_id, {}).get("dash", {})
    open_pos = dash.get("openPosition")
    if not open_pos:
        return {"ok": False, "error": "No open position to close"}

    _decision, _close_rid = gates.authorize_close(
        user_id, position_id=open_pos.get("positionId"),
        symbol=open_pos.get("symbol"), origin=origin, user=user,
        emergency=emergency)
    gates.audit(user_id, "CLOSE", _decision, origin=origin, rid=_close_rid)
    if not _decision:
        return {"ok": False, "error": _decision.reason,
                "detail": _decision.detail}

    broker, cfg = _make_broker(user)

    sym = open_pos.get("symbol", cfg.SYMBOL)
    try:
        candles = broker.get_candles(sym, cfg.TIMEFRAME, 5)
        price = candles[-1]["close"] if candles else 0.0
    except Exception:
        price = 0.0

    try:
        _close_res = broker.close_position(sym)
    except Exception as e:
        # The claim STANDS. A close that raised may still have reached the
        # broker, and retrying it seconds later can close a position that was
        # reopened in between. The next tick re-reads the broker and settles it.
        return {"ok": False, "error": str(e), "symbol": sym,
                "ambiguous": broker_result_ambiguous(e)}
    # Record the outcome against the intent, so a duplicate request is answered
    # with what actually happened instead of a bare refusal the caller might
    # respond to by trying again.
    ledger.record(_close_rid, {"closed": True, "symbol": sym})
    _persist_open_position(user_id, cfg, None)
    # Prefer the broker's actual fill price over the last fetched candle —
    # the candle close is a stale proxy and can diverge from the real
    # execution price by real spread/slippage.
    price = (_close_res or {}).get("fillPrice") or price

    gross = cost_usd = net = 0.0
    if open_pos and price:
        units_ = open_pos.get("units", 1000)
        gross = forex.pnl_usd(open_pos["side"], open_pos["entryPrice"], price, units_, sym)
        pv = forex.pip_value_per_unit(sym, price)
        cost_usd = (open_pos.get("entrySpreadPips", 0.0) * pv * units_
                   + (_close_res or {}).get("commissionUsd", 0.0))
        net = gross - cost_usd

    with _lock:
        loop_data = _loops.get(user_id, {})
    if loop_data:
        d = loop_data.get("dash", {})
        old_bal = d.get("balance", cfg.PAPER_BALANCE)
        if cfg.PAPER_TRADING:
            new_bal = round(old_bal + net, 2)
        else:
            # LIVE: read the real post-close balance instead of adding our
            # own P&L estimate on top of a cached one — same fix as _loop's
            # close paths, same bug (a stale balance next to a fresh P&L
            # line in the same message).
            try:
                new_bal = round(broker.get_balance(), 2)
            except Exception:
                new_bal = round(old_bal + net, 2)
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        result = {"action": "CLOSE", "symbol": sym, "price": price,
                  "entryPrice": open_pos.get("entryPrice"),
                  "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
                  "netPnl": round(net, 2), "balance": new_bal,
                  "openedAt": open_pos.get("openedAt"), "time": now_str}
        _log_trade(user_id, result, open_pos)
        if cfg.PAPER_TRADING:
            # Persist so the simulated balance survives a restart.
            user_store.update(user_id, {"paper_balance": new_bal})
        d["openPosition"] = None
        d["balance"] = new_bal
        d["_manualClose"] = True   # tell the loop this close was manual
        d["_manualBal"] = True
        trades = d.get("trades", [])
        trades.insert(0, result)
        d["trades"] = trades[:50]

    return {"ok": True, "symbol": sym, "price": price,
            "grossPnl": round(gross, 2), "costUsd": round(cost_usd, 2),
            "netPnl": round(net, 2)}


def open_position_count(user_id):
    """How many positions are open RIGHT NOW, or None when it cannot be known.

    None is not zero. The emergency screen asks the client to confirm closing
    "N positions", and printing 0 because the loop has not ticked yet — or
    because the account is not the tracked one — would be a lie at the exact
    moment it is most expensive. The caller shows "unknown" instead.
    """
    dash = get_dash(user_id) or {}
    if not dash:
        return None
    n = dash.get("openCount")
    if isinstance(n, int):
        return n
    return 1 if dash.get("openPosition") else None


def force_close_all(user_id):
    """Close every open position on this account. The emergency stop.

    Deliberately built on force_close() rather than a fresh order path: that
    function already prices the exit off the broker's own fill, journals the
    trade, corrects the balance and clears the persisted snapshot. A second
    implementation would be a second set of those bugs.

    force_close() only knows the ONE position the loop tracks, so anything
    else on the account (multi-position mode, or a trade opened by hand in
    cTrader) is swept afterwards through the broker's existing
    close_position(). Failures are collected, never swallowed: a position the
    bot could not close is the single most important thing to say back.
    """
    user_id = str(user_id)
    closed, failed = [], []

    first = force_close(user_id)
    if first.get("ok"):
        closed.append(first.get("symbol"))
    elif "No open position" not in str(first.get("error", "")):
        failed.append({"symbol": first.get("symbol"), "error": first.get("error")})

    user = user_store.load(user_id)
    broker, fcfg = _make_broker(user)
    try:
        remaining = broker.get_all_positions() or []
    except Exception as e:
        return {"ok": not failed, "closed": closed, "failed": failed,
                "sweepError": str(e)[:160]}

    for pos in remaining:
        sym = pos.get("symbol")
        if not sym or sym in closed:
            continue
        # EVERY close passes the gate, including the sweep. The first close
        # above goes through force_close() and was gated; these did not, and
        # reached the broker directly — the one path in the codebase where a
        # position was closed without the gate seeing it.
        #
        # emergency=True, so this does not weaken the emergency: ownership is
        # still waived and a coordination outage still lets the operator out.
        # What it adds is the idempotency claim, keyed on CLOSE:{symbol}. Two
        # containers sweeping at once — a deploy overlap, or the operator
        # tapping twice — would otherwise each believe they were first, and the
        # second close lands on whatever was reopened in between. It also puts
        # the sweep in the audit, which is where an emergency most needs to be.
        _d, _rid = gates.authorize_close(user_id, symbol=sym, origin="emergency_sweep",
                                         user=user, emergency=True)
        gates.audit(user_id, "CLOSE", _d, origin="emergency_sweep", rid=_rid)
        if not _d:
            # A refused claim means somebody else is already closing this
            # position, not that it is stuck. Say which it is rather than
            # reporting a failure the operator would answer by trying again.
            failed.append({"symbol": sym,
                           "error": f"{_d.reason}: {_d.detail}"[:120],
                           "gate": _d.reason})
            continue
        try:
            res = broker.close_position(sym) or {}
        except Exception as e:
            # The claim STANDS — same rule as force_close(). A close that raised
            # may still have reached the broker, and retrying it can close a
            # position that was reopened in between.
            failed.append({"symbol": sym, "error": str(e)[:120],
                           "ambiguous": broker_result_ambiguous(e)})
            continue
        if str(res.get("status")) in ("FILLED", "FLAT"):
            closed.append(sym)
            ledger.record(_rid, {"closed": True, "symbol": sym})
        else:
            failed.append({"symbol": sym, "error": str(res.get("reason") or res)[:120]})

    return {"ok": not failed, "closed": closed, "failed": failed}

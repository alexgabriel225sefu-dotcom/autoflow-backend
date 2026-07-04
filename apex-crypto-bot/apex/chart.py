"""Candlestick chart rendering — the client's cTrader-in-Telegram.

Renders a dark-theme PNG of recent candles with EMA20/50 and, when a position
is open, entry/SL/TP levels — sent via sendPhoto on entries and /chart."""
import io


def _ema(closes, period):
    k = 2 / (period + 1)
    out, e = [], None
    for c in closes:
        e = c if e is None else c * k + e * (1 - k)
        out.append(e)
    return out


def render(candles, symbol, timeframe="5m", position=None):
    """candles: [{open,high,low,close,time}…] → PNG bytes."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    candles = candles[-120:]
    closes = [c["close"] for c in candles]
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)

    bg, up, dn = "#0b0e16", "#27c46a", "#ff2d4f"
    fig, ax = plt.subplots(figsize=(9, 5), dpi=110, facecolor=bg)
    ax.set_facecolor(bg)

    for i, c in enumerate(candles):
        color = up if c["close"] >= c["open"] else dn
        ax.plot([i, i], [c["low"], c["high"]], color=color, linewidth=0.7, zorder=2)
        lo, hi = sorted((c["open"], c["close"]))
        ax.add_patch(plt.Rectangle((i - 0.36, lo), 0.72, max(hi - lo, 1e-9),
                                   facecolor=color, edgecolor=color, zorder=3))

    ax.plot(range(len(candles)), ema20, color="#f59e0b", linewidth=1.1, label="EMA 20", zorder=4)
    ax.plot(range(len(candles)), ema50, color="#60a5fa", linewidth=1.1, label="EMA 50", zorder=4)

    if position:
        entry = position.get("entryPrice")
        sl = position.get("stopLoss") or position.get("sl")
        tp = position.get("takeProfit") or position.get("tp")
        side = position.get("side", "")
        if entry:
            ax.axhline(entry, color="#e6e9ef", linewidth=1, linestyle=":",
                       label=f"Entry {side} {entry:g}", zorder=5)
        if sl:
            ax.axhline(sl, color=dn, linewidth=1, linestyle="--", label=f"SL {sl:g}", zorder=5)
        if tp:
            ax.axhline(tp, color=up, linewidth=1, linestyle="--", label=f"TP {tp:g}", zorder=5)

    ax.set_title(f"{symbol}  ·  {timeframe}  ·  last {len(candles)} candles",
                 color="#e6e9ef", fontsize=11, loc="left")
    ax.tick_params(colors="#94a3b8", labelsize=8)
    for spine in ax.spines.values():
        spine.set_color("#1f2937")
    ax.grid(color="#1f2937", linewidth=0.4, alpha=0.6)
    ax.set_xlim(-1, len(candles))
    ax.margins(y=0.08)
    leg = ax.legend(loc="upper left", fontsize=7, facecolor=bg, edgecolor="#1f2937",
                    labelcolor="#e6e9ef")
    leg.set_zorder(6)
    ax.text(0.995, 0.015, "APEX FOREX BOT", transform=ax.transAxes, ha="right",
            color="#334155", fontsize=8, fontweight="bold")

    buf = io.BytesIO()
    fig.tight_layout()
    fig.savefig(buf, format="png", facecolor=bg, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()

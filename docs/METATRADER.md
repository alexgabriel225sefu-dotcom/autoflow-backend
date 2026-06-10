# MetaTrader 5 Integration (ApexBridge EA)

Trade through **any MT5 broker** — IC Markets, Pepperstone, FTMO, your prop
firm — and watch every trade appear live in your own MetaTrader, with SL/TP
visible on the chart.

## How it works (3Commas-style)

```
┌─────────────────────────┐         every ~10 s          ┌──────────────────────┐
│  Apex Forex Bot (cloud) │ ◄──── prices, balance, ────  │  Your MetaTrader 5   │
│  AI analysis, strategy, │       candles, position      │  (any broker)        │
│  risk management        │ ──── trade commands ────►    │  ApexBridge EA       │
└─────────────────────────┘                              └──────────────────────┘
```

The bot is the brain; the EA is the hands. Your broker credentials never
leave MetaTrader — the EA only talks to **your own** bot server, protected
by a shared secret.

---

## Setup (10 minutes)

### 1. Tell the bot to use MetaTrader

In Telegram:

```
/broker mt
/setkeys MT_BRIDGE_SECRET=pick_a_long_random_string
```

(The secret message is auto-deleted. Any 8+ character string works — it just
has to match in the EA.)

### 2. Install the EA in MetaTrader 5

1. In MT5: **File → Open Data Folder** → open `MQL5/Experts`
2. Copy [`mt5/ApexBridge.mq5`](../mt5/ApexBridge.mq5) there
3. Back in MT5: right-click **Expert Advisors** in the Navigator → **Refresh**
   (MetaEditor compiles it automatically; or open the file and press F7)

### 3. Allow the EA to reach your bot

**Tools → Options → Expert Advisors**:
- ✅ *Allow WebRequest for listed URL* → add your bot's URL, e.g.
  `https://your-app.up.railway.app`

### 4. Attach to a chart

1. Open the chart of the pair you want (e.g. **EURUSD**, M5)
2. Drag **ApexBridge** onto it and set:
   - `BotURL` — your Railway URL (no trailing slash)
   - `Secret` — the same value as `MT_BRIDGE_SECRET`
   - `Timeframe` — keep `M5` (must match the bot's `TIMEFRAME`)
3. Enable the **Algo Trading** toolbar button

Within ~10 seconds `/status` in Telegram shows the bridge connected and the
bot starts analyzing your broker's prices.

---

## Things to know

| Topic | Behavior |
|---|---|
| **Symbol** | The bot trades whatever chart the EA sits on. Move the EA to change pairs (`SCAN_SYMBOLS` is ignored in MT mode). |
| **Suffixed symbols** | `EURUSD.a`-style broker suffixes are handled automatically. |
| **SL/TP** | Sent with every order, so they're set natively in MT — even if your server goes down, the position stays protected. |
| **Trailing stop** | Managed by the bot; when the trail is hit the bot sends a CLOSE (your chart SL stays at the original safety level). |
| **MT closed it first?** | If the native SL/TP fires inside MetaTrader, the bot detects it on the next cycle and records the trade (`MT_SLTP`). |
| **Lot sizing** | The bot computes units from your risk %, converts to lots (min 0.01), and the EA clamps to the broker's lot step. |
| **Demo first** | Attach the EA to a **demo** MT5 account first — same flow, fake money. Set `/paper off` so commands actually reach the EA. |
| **PC must stay on** | The EA runs inside MetaTrader. Use your broker's free VPS (IC Markets offers one), a $5 Windows VPS, or simply keep MT5 open. |
| **MT4** | The bridge protocol is MT4-compatible; an MT4 EA can be provided on request. MT5 is recommended (every major broker offers it). |

## Troubleshooting

### EA prints `sync failed (HTTP -1 / 4014)`
The URL isn't whitelisted. Tools → Options → Expert Advisors → *Allow
WebRequest for listed URL* → add the **exact** URL from `BotURL`.

### EA prints `sync failed (HTTP 403)`
Secret mismatch. Re-check `/setkeys MT_BRIDGE_SECRET=...` vs the EA's
`Secret` input.

### Telegram says "MT bridge offline"
MetaTrader is closed, Algo Trading is off, or the EA was removed from the
chart. The bot resumes automatically when the EA reconnects.

### Orders rejected with `REJECTED`
Check the MT5 **Journal/Experts** tab — usually not enough margin, market
closed, or Algo Trading disabled for the account.

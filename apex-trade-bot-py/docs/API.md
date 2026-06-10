# API Reference

## Dashboard HTTP API

The bot runs a built-in web server (port `PORT`, default 3000).

### `GET /`
The live dashboard UI. Auto-refreshes every 5 seconds via `/api/status`.
Shows balance, total PnL, win rate, profit factor, equity curve, open
position, and trade history.

### `GET /api/status`
JSON snapshot of the bot's full state. CORS-enabled (`Access-Control-Allow-Origin: *`),
so you can consume it from your own tools.

```json
{
  "balance": 104.2,
  "startBalance": 100,
  "currentSymbol": "SOLUSDT",
  "currentPrice": 142.55,
  "mode": "PAPER",
  "exchange": "BINANCE",
  "tickCount": 42,
  "lastTick": "2026-06-10 14:05:00",
  "openPosition": {
    "symbol": "SOLUSDT",
    "side": "BUY",
    "entryPrice": 141.2,
    "quantity": 0.141,
    "stopLoss": 140.07,
    "takeProfit": 143.46,
    "currentPnl": 0.19,
    "openedAt": "2026-06-10T13:45:00"
  },
  "trades": [
    {
      "time": "2026-06-10 13:30:00",
      "symbol": "SOLUSDT",
      "side": "BUY",
      "entry": 140.1,
      "exit": 141.9,
      "qty": 0.142,
      "pnl": 0.2556,
      "pnlPct": 1.28,
      "reason": "TAKE_PROFIT",
      "win": true
    }
  ]
}
```

Notes:
- `trades` is newest-first, capped at the last 50 closed trades
- `openPosition` is `null` when flat
- `mode` is `PAPER`, `TESTNET`, or `LIVE`
- Close `reason` values: `TAKE_PROFIT`, `STOP_LOSS`, `AI_CLOSE`

---

## License API (aicashsystem.space)

### `POST /api/verify-license`

Called automatically at startup. Body:

```json
{ "key": "APEX-XXXX-XXXX-XXXX" }
```

Response:

```json
{ "valid": true, "email": "buyer@example.com" }
```

If the license server is temporarily unreachable, the bot starts in **grace
mode** rather than blocking your trading.

---

## Exchange connector interface

Every connector in `apex/exchanges/` implements the same four functions, so
adding a new exchange means writing one small module:

```python
get_price(symbol) -> float
get_candles(symbol, interval, limit) -> list[dict]  # time/open/high/low/close/volume
get_balance(asset="USDT") -> float
place_order(side, quantity, symbol) -> dict
```

Register it in `apex/exchanges/__init__.py` (`_REGISTRY`) and it becomes
available via `EXCHANGE=<name>` and `/exchange <name>`.

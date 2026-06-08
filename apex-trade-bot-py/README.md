# ⚡ Apex Trade Bot — Python

AI-powered crypto trading bot. Full source code. **You** configure the strategy,
pairs and risk; it runs on **your** exchange account. Paper-trading mode included
(zero real risk to start).

> This is the Python edition (port of the original Node.js bot), same behaviour and features.

## Features
- **8 exchanges** — Binance, Bybit, OKX, Kraken, KuCoin, Coinbase, Bitget, MEXC
- **Paper trading** — simulated money, no real risk while you test
- **Legendary strategies** — Turtle breakout, Livermore structure, Soros momentum,
  Druckenmiller sizing, PTJ/Seykota defense
- **AI signals** — Anthropic (primary) + Groq (free fallback)
- **Risk controls** — stop-loss, take-profit, trailing stop, daily/drawdown limits
- **Multi-symbol scanner**, **Telegram alerts + /status**, **live web dashboard**

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env     # then edit .env
python main.py
```

## Configuration (environment variables)

| Variable | Meaning |
|---|---|
| `EXCHANGE` | `binance` `bybit` `okx` `kraken` `kucoin` `coinbase` `bitget` `mexc` |
| `PAPER_TRADING` | `true` to simulate (recommended to start), `false` for real money |
| `PAPER_BALANCE` | Starting simulated balance (default `100`) |
| `TRADE_SYMBOL` | e.g. `SOLUSDT` |
| `SCAN_SYMBOLS` | Comma list for the multi-symbol scanner |
| `TIMEFRAME` | e.g. `5m` |
| `RISK_PER_TRADE` `STOP_LOSS_PCT` `TAKE_PROFIT_PCT` | Risk settings |
| `MIN_CONFIDENCE` | Minimum AI confidence to trade |
| `GROQ_API_KEY` | Free AI key (or `ANTHROPIC_API_KEY`) |
| `TELEGRAM_BOT_TOKEN` `TELEGRAM_CHAT_ID` | Optional alerts + `/status` |
| `LICENSE_KEY` | Your license key from purchase |

### Exchange API credentials (only for the exchange you choose)

| Exchange | Variables |
|---|---|
| Binance | `BINANCE_API_KEY` `BINANCE_API_SECRET` (`BINANCE_TESTNET`) |
| Bybit | `BYBIT_API_KEY` `BYBIT_API_SECRET` (`BYBIT_TESTNET`) |
| OKX | `OKX_API_KEY` `OKX_API_SECRET` `OKX_API_PASSPHRASE` |
| Kraken | `KRAKEN_API_KEY` `KRAKEN_API_SECRET` |
| KuCoin | `KUCOIN_API_KEY` `KUCOIN_API_SECRET` `KUCOIN_API_PASSPHRASE` |
| Coinbase | `COINBASE_API_KEY` (key name) `COINBASE_API_SECRET` (EC private key PEM) |
| Bitget | `BITGET_API_KEY` `BITGET_API_SECRET` `BITGET_API_PASSPHRASE` |
| MEXC | `MEXC_API_KEY` `MEXC_API_SECRET` |

## Safety

Start with `PAPER_TRADING=true`. When going live, test with a **small** amount first —
each exchange has subtle order-sizing rules. The bot runs on **your** machine with
**your** keys; results depend entirely on your configuration. Crypto trading is risky.

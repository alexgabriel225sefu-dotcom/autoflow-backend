# APEX4TRADERS transformation — running state

Resume point for this work. Written so that after a container reset the next
session can pick up without re-auditing the repository.

**Recovery: the git remote is the durable store.** Every commit is pushed
immediately. After a reset:

```
cd /home/user/autoflow-backend
git fetch origin claude/arcads-external-api-gExX7
git reset --hard origin/claude/arcads-external-api-gExX7
cd apex-forex-bot && pip install -q python-dotenv requests redis cffi
python3 tests/run_all.py            # expect: ALL <N> TEST FILES PASSED
```

Two branches, kept identical in content:
`claude/arcads-external-api-gExX7` (deploy) and
`claude/arcads-external-api-gexx7-6n4pr9` (designated).

---

## Where the Mini App lives

- **Live page**: `apex-forex-bot/apex/static/terminal.html` — a real file, ~40KB.
  `webapp.HTML` is only a fallback served if that file is missing.
- Screens are `<section class="screen" id="s-NAME">`; `showScreen(name)` routes
  on the hash. Helpers already defined: `Q`, `esc`, `money`, `num`, `api`,
  `sheetOpen`, `sheetClose`, `meter`, `kvRows`.
- Routes live in `apex-forex-bot/apex/bot.py`, inside `do_GET` / `do_POST`.

## Two rules that have already cost time

1. **Local-variable shadowing.** `do_GET`/`do_POST` are single long methods
   nested inside `_start_dashboard_server`, and `bot.py` has a module-level
   `dash`. Binding a bare `dash`, `stats`, `state`, `positions`, `parse_qs` or
   `token` in a route makes it local to the WHOLE method and raises
   `UnboundLocalError` in every branch above it — the server then drops
   connections with no response. **Prefix every local a route introduces.** Only
   `tg_user` and `chat_id` may be bare. This shipped twice; it is now asserted
   by regex in `test_risk_screen.py`, `test_intelligence_screen.py` and
   `test_miniapp_close.py`.

2. **`test_prose_assertions.py`** rejects any test that could pass on a comment
   alone. Assert rendered markup (`">Label</div>"`), not bare phrases that may
   also appear in a Python comment somewhere in the package.

## Standing constraints

- `gates.authorize_order` / `gates.authorize_close` are the only things that may
  permit an order. No screen reaches a broker.
- Never call `strategies.should_stop()` to draw a badge — it advances the peak
  balance and the daily reset as a side effect. Read `dash["riskGuard"]`.
- Never fabricate a financial value. If it is not published, render "Not
  available" with the reason.
- Free margin and margin level are **not in cTrader's account response**
  (`ProtoOATrader` carries balance, leverage and bonuses, not margin state).
  They are shown as unavailable on purpose.
- cTrader limits: 5 historical req/s and 50 non-historical req/s **per
  connection regardless of user count**. `broker.get_candles` already routes
  through `apex/candle_cache.py` — do not wrap it again.
- Do not change `EV_GATE_MODE`. That is the operator's decision after reading
  the shadow logs.

---

## Phase status

| Phase | State | Notes |
|---|---|---|
| 1 Design system + navigation | done | tokens, TopBar, EnvironmentBadge, bottom nav, hash router |
| 2 Home + Account | done | account card reads the broker's own figures |
| 3 Markets | done | list, shared snapshot, and symbol detail with its own chart |
| 4 Positions + close | done | `POST /api/app/close` → `user_loop.force_close(origin="miniapp")` |
| 5 History | done | pre-existing, wired into the new shell |
| 6 Trade Replay | done | pre-existing; broker-anchored historical bars |
| 7 Intelligence | done | four blocks kept apart; no win probability |
| 8 Risk Centre | done | renders the engine, never replaces it |
| 9 Automation | done | third settings tier `MINIAPP_SETTABLE`; environment is not writable |
| 10 APEX Copilot | done | facts only; `assistant.chat` deliberately NOT wired in |
| 11 Streaming | done | SSE; adds NO broker calls — publishes in-memory dash + one shared snapshot |
| 12 Error/empty/loading | done | every screen has loading, empty and failure copy |
| 13 Security regression | done | 9 new suites; scope, shadowing, credentials, isolation |
| 14 Performance | **next** | |
| 15 Full regression | green | see the count in the last commit message |

## Decision/event model (2nd brief §33-35)

`apex/trade_events.py` — append-only, bounded to 2000 events per user, in
Redis via `user_store.get_blob`/`set_blob`.

- Each event stamps `schema`, `risk_version`, and `strategy_version` **looked up
  from the registry, never assumed**.
- Wired at two call sites in `user_loop.py`: every refusal
  (`DECISION_DECLINED`) and every fill (`ORDER_FILLED`). Both wrapped so a
  journalling failure can never reach the execution path.
- **Still to wire**: `ORDER_AUTHORIZED` / `ORDER_REJECTED` at the gate,
  `ORDER_SUBMITTED`, `STOP_UPDATED`, `POSITION_CLOSED`.
- There is no backfill. Absence renders as "no recorded decision", never as
  "no reason".

## Endpoints added so far

```
GET  /api/app/markets        shared snapshot, one fetch for all clients
GET  /api/app/risk           risk engine state, presentation only
GET  /api/app/intelligence   market / strategy / risk / decision, kept apart
GET  /api/app/automation     status + the writable list, from the policy
POST /api/app/automation     the ONLY write gate is validate_miniapp
GET  /api/app/symbol         one instrument; symbol checked against the universe
GET  /api/app/account        identity only; number masked, no tokens
GET  /api/app/alerts         recorded events + risk verdict
GET  /api/app/stream         SSE; auth before open, per-chat account events
POST /api/app/ask            read-only, user-scoped, no generated text
POST /api/app/close          the one financial action; same gate as /close
GET  /go                     ad-click bridge (Meta attribution, separate work)
```

Pre-existing: `/api/app/data`, `/api/app/tick`, `/api/app/history`,
`/api/app/replay`.

## Known limitations (do not claim these are done)

- Streaming is SSE and **adds no broker load**: it publishes `get_dash`
  (in-memory) plus one shared `markets.snapshot`. Polling still runs
  underneath (`tick` 1.5s, `refresh` 6s) and is the fallback — the stream is
  an accelerator, never a replacement.
- Trades live in Redis (`user_store`), not Supabase. Supabase holds licences,
  bot configs and affiliate tables only. No `trades`/`trade_events` tables
  there — deliberately, per "do not create duplicate tables".
- Mobile and Telegram Desktop rendering is **unverified** — built mobile-first
  with safe-area handling, but never seen on a device.
- All twelve screens from the brief now exist: Home, Markets, Symbol detail,
  Portfolio, History, Replay, Intelligence, Risk, Automation, Ask APEX,
  Settings, Trading Account, Alerts. Account/Alerts/Symbol are reachable
  contextually rather than from the bottom bar, which is what §26 asks for.
- The Copilot serves NO generated text. `apex.assistant.chat()` runs a tool
  loop that can act and answers via a send function, so wiring it into a
  natural-language surface would give it a path §18 forbids. Answers come
  from recorded state or are UNKNOWN.
- Automation writes land on the client's own user_store record, never on
  os.environ — a per-client change must not become process-wide.

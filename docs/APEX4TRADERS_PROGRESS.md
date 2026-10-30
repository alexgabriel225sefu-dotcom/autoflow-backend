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
| 14 Performance | done | bounded queries, shared caches, paged history, one shared stream |
| 15 Full regression | green | see the count in the last commit message |

## Decision/event model (2nd brief §33-35)

`apex/trade_events.py` — append-only, bounded to 2000 events per user, in
Redis via `user_store.get_blob`/`set_blob`.

- Each event stamps `schema`, `risk_version`, and `strategy_version` **looked up
  from the registry, never assumed**.
- Wired at two call sites in `user_loop.py`: every refusal
  (`DECISION_DECLINED`) and every fill (`ORDER_FILLED`). Both wrapped so a
  journalling failure can never reach the execution path.
- Wired at every point of the decision path: refusal, gate verdict (both
  ways), submission, fill, stop move, close.
- There is no backfill. Absence renders as "no recorded decision", never as
  "no reason".

## Endpoints added so far

```
GET  /api/app/markets        shared snapshot, one fetch for all clients
GET  /api/app/risk           risk engine state, presentation only
GET  /api/app/intelligence   market / strategy / risk / decision, kept apart
GET  /api/app/automation     status + the writable list, from the policy
POST /api/app/automation     the ONLY write gate is validate_miniapp
GET  /api/app/trade          one trade: R, duration, decision timeline
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

## Mockup audit — closed out

The exhaustive pass against the mockup found 32 of 41 elements missing. All of
them are now built, verified by the gated suite (113 files) and by the Chromium
boot test (zero page errors, 18 screens, no 375px overflow).

Built in this pass:

- **Splash** (§1) — four steps that tick from what actually happened, not a
  timer, with a 6s hard clear. A splash that can outlive the app is worse
  than none.
- **TopBar** — bell to Alerts, kebab to Settings, and a global search that
  filters markets and trade ids from data already in hand. Searching is never
  a reason to query.
- **Environment banners** (§5) — DEMO says "No real funds are at risk";
  an environment the broker has not confirmed says new live orders are
  unavailable, with [Retry connection].
- **Outage banner** (§22) — one voice. Appears after three consecutive
  failures, states that positions and stops are held by the broker and are
  unaffected by this screen, and carries the only [Retry].
- **Position detail** (`#s-position`) — volume, entry, current, SL, TP, R
  multiple (or "Not recorded"), opened, status. R needs a recorded stop
  distance; without one there is no R to show.
- **Order/close outcome** (`#s-order`, §21) — six outcomes with wording that
  is true of each. Opening and closing fail differently: "nothing was closed"
  and "no new position was created" are not interchangeable. Unknown is its
  own outcome and never collapses into failure.
- **Portfolio** — empty state names the state and offers [Explore markets];
  rows open the detail; Home carries [View all positions].
- **History** (§9) — grouped by day from each trade's own timestamp. A trade
  with no recorded time groups under "Date not recorded", never silently
  under today.
- **Intelligence** (§12) — setup-strength bar, shown only when the platform
  scored the instrument. An empty bar at 0% reads as a weak setup rather than
  as no reading.
- **Replay** (§14) — outcome from the recorded exit reason, and
  [Replay again] / [Back to trade history]. "TP hit" is only claimed when the
  exit reason says so; inferring it from a positive P&L would turn a manual
  close into a target hit.
- **Risk** (§15) — the eight engine checks, ticked from the engine's own
  verdict. An unread state shows every line as unknown: a green tick nobody
  verified is worse than no list.
- **Automation** (§16) — Manual / Assisted / Automatic as the server reports
  them. Selecting one routes to `/automation` in chat, where the same
  authorisation runs as for every other change.
- **Alerts** (§19) — grouped Risk / Trades / Market by event type, never by
  whether the wording sounds urgent.
- **Ask** (§13) — answers carry structured `facts` from the server, plus
  [View chart] / [View position]. A number with no stated source is
  indistinguishable from an invented one.
- **Account / Security** — [Manage account] and [Log out other sessions] both
  say the truth: credentials are handled in chat, and there is no second
  session to end.

### One test was rewritten, not deleted

`test_miniapp_close.py` asserted `HTML.count("Do not retry yet") >= 2`. That
count was a proxy for "both failure paths tell the client not to retry", and
it stopped being one when both paths started sharing a renderer. It now asserts
that both paths route to `close_unknown` and that `close_unknown` carries the
instruction — one occurrence reached from two places, which cannot drift apart
the way two copies can.

### The two rules that keep costing time

1. Never call `showScreen()` during script evaluation. It reads `let`s
   declared further down; the throw stops the whole script and every handler
   below it never exists. Tests stay green and the app is dead.
2. Every route local in `do_GET`/`do_POST` must be prefixed. A bare name makes
   itself local to the whole method and raises UnboundLocalError in every
   branch above it.

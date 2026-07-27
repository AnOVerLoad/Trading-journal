# CLAUDE.md — Thai Stock Trading Journal

This file is the source of truth for how this project is built. Read it fully before
writing code. It encodes decisions already made across a long design conversation — do
not re-litigate them without a reason.

---

## 1. Mission

Turn a Thai stock trading journal (migrated out of Excel, now living in Notion) into an
analytics app that answers one question honestly:

> **Where does my edge actually come from — and where do my losses actually come from?**

The history already whispers the answer: **the edge lives in setups; the losses live in
tips.** Across 46 closed trades the win rate is ~22%, profit factor 0.74, and the biggest
losing bucket by far is `Guru's advice`. The app exists to make that undeniable and to
change behaviour at the point of entry.

## 2. Architecture — read this before designing anything

- **Notion is the capture layer.** Human-facing record: mobile entry, screenshots,
  narrative, manual browsing. It is the single source of truth for raw records.
- **The app is the analytics brain.** It pulls Notion into local pandas DataFrames and
  computes everything (expectancy, R-multiples, equity curve) in Python.
- **Sync-then-analyze.** NEVER run statistics live against the Notion API (rate limits).
  Pull once into DataFrames, cache, compute against the cache. This is non-negotiable and
  is the reason the sync layer (`src/notion_sync.py`) is built and proven first.
- **The app will also WRITE trades back** to Notion later (Log Trade screen). Notion just
  stores; the app owns all math. Derived fields (Result, R-multiple, Realized P&L) are
  computed by the app, never typed by hand in Notion.

## 3. Data model (three Notion databases)

Two-level core: a **Trade** = one position/idea; an **Execution** = one buy/sell fill.
One trade → many executions (one-to-many), linked by the shared `Trade ID` value.

- **Trades** — one row per idea. Title = `Trade ID` (e.g. `T001`).
- **Executions** — one row per fill. Title = `Execution ID` (e.g. `E0001`), carries
  `Trade ID` as text — this is the join key. (No native Notion relation is required; the
  app joins on `Trade ID`.)
- **Stocks** — master list of symbols (mostly empty metadata for now).

### The taxonomy rule that must never be violated

Four categorical axes are kept deliberately separate. Do not merge them:

- **Setup** = the *chart pattern* (Breakout, Red to green, Pullback). A testable edge.
- **Entry context** = *why the button was pressed* (Guru's advice, Buy the dip, Bad news…).
- **Mistakes** = *process errors* (Held loser past stop, Cut winner early…).
- **Emotion** = *felt state* (Fear, FOMO, Greed…). Starts empty; fills forward.

**Setup is mostly blank on purpose. That blank IS the finding** — it quantifies how often
entries had no technical setup, only a tip. NEVER backfill Setup with `Guru's advice` or
any entry reason. Keeping Setup pure is what lets us compare "traded a real setup" vs
"followed a tip". If you ever feel tempted to fold entry reasons into Setup, stop.

## 4. Conventions (match these exactly — the data was built this way)

- Cost basis = **average cost**.
- **1R is anchored at trade inception** (initial planned baht risk = `Est. Loss` of the
  first buy). Never recomputed after scaling in.
- **P&L is recomputed from prices** (avg-cost, commission-inclusive), never trusted from
  any stored "net" column. `Realized P&L` on a trade reflects only the closed portion.
- Accounts: two only — `KS` and `LIB`. Kept as a Select, not a separate database.

## 5. Reconciliation targets — the sync is correct ONLY if these match

After `src/notion_sync.py` pulls the three databases, `src/reconcile.py` must produce:

| Check                         | Expected            |
|-------------------------------|---------------------|
| Trades total                  | 59 (46 closed, 13 open) |
| Executions total              | 182                 |
| Stocks total                  | 42                  |
| Realized P&L (closed trades)  | −9,892 ฿ (±10 rounding) |
| Win rate (closed)             | 21.7% (10W / 36L)   |
| Profit factor                 | 0.74                |

If these don't match, the pipeline is wrong — fix the connection/extraction BEFORE
building any screen. This is the first smoke test: `python -m src.notion_sync`.

## 6. Tech stack & setup

- Python + **Streamlit** + **Plotly**, reading via the official **notion-client**.
- Secrets live in `.env` (gitignored). NEVER hardcode the Notion token or database IDs in
  source. The user creates a Notion internal integration, shares all three databases with
  it (Database → ••• → Connections → add integration — the step everyone forgets), and
  pastes token + IDs into `.env`. See `.env.example`.
- `pip install -r requirements.txt`, then `streamlit run app.py`.

## 7. Design tokens (already decided — use these, don't invent new ones)

- **Primary accent: olive** `#6E7A34` (leans yellow-green so it never reads as "win").
- **Win = green** `#2E8B57`, **Loss = red** `#C0392B`. Same mapping for +/- R.
- **Light base, warm off-white background** `#FAF8F2`; cards `#F1EFE6`; text `#2B2B26`.
- All tokens live in `src/theme.py` (Python/Plotly) and `.streamlit/config.toml`
  (Streamlit chrome). Import from there; never hardcode hex in screens.
- Design refines *forward* against live rendered output — do not stall the build to
  perfect visuals. The existing Dashboard mockup is a reference, not a spec.

## 8. Roadmap

**v1 (manual core):**
1. **Sync layer** ✅ built here — prove the pull first.
2. **Log Trade** — the first real screen. Writes to Notion, auto-computes 1R & R-multiple.
   Must enforce a **plan gate**: no trade saves as "open" without stop, target, size, and
   a one-line thesis. This is the screen that changes behaviour — build it first among UI.
3. **Dashboard** — KPIs, equity curve, avg P&L by entry reason, open positions.
4. **Trade review** — filter closed trades by setup/grade/emotion (process-vs-outcome).
5. **Setup analytics** — expectancy & win rate per setup.
6. **Watchlist** — manual in v1.

**v2 (needs price history):** MAE/MFE (maximum adverse/favourable excursion), live SET
price feed, benchmark vs SET index, mistake-trending over time.

## 9. House style for this codebase

- Keep the sync layer free of Streamlit imports so it runs standalone as a smoke test.
- Cache Notion reads in the app (`st.cache_data`) — do not re-pull on every rerun.
- Multi-select fields (Entry context, Mistakes, Emotion) come back as **lists**. Preserve
  them as lists for analysis; join to strings only for display.
- Small, composable functions. Every derived number must be reproducible from executions.

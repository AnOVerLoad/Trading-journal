# Trading Journal App

Analytics app for a Thai stock trading journal. Notion is the capture layer; this app is
the analytics brain (pulls Notion → pandas, computes in Python). Read **CLAUDE.md** first —
it holds every design decision.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # then fill in your Notion token + 3 database IDs
```

**Before running:** create a Notion internal integration and share all three databases
with it (Database → ••• → Connections). Details in `.env.example` and CLAUDE.md §6.

## Prove the pipeline first

```bash
python -m src.notion_sync     # prints reconciliation — must match CLAUDE.md §5
```

Expected: 59 trades (46 closed / 13 open), 182 executions, 42 stocks,
realized P&L −9,892 ฿, win rate 21.7%, profit factor 0.74.

## Run the app

```bash
streamlit run app.py
```

## Layout

```
CLAUDE.md            <- source of truth: architecture, data model, rules, targets, tokens
app.py               <- Streamlit entry (currently the sync-check screen)
.streamlit/config.toml
src/
  config.py          <- .env loading + constants + reconciliation targets
  theme.py           <- olive / win-green / loss-red palette + Plotly template
  notion_sync.py     <- the sync spine (Notion -> pandas); runnable smoke test
  reconcile.py       <- verify pulled data against known-good numbers
```

## Next build

Log Trade screen with a **plan gate**: no trade saves as "open" without stop, target,
size, and a one-line thesis. See CLAUDE.md §8.

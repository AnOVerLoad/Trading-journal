"""Design tokens and the Plotly template.

Single source of truth for colour. Screens import from here — never hardcode hex.
Decided tokens: olive accent, green=win / red=loss, warm off-white light base.
"""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio

# --- Palette ------------------------------------------------------------------
OLIVE = "#6E7A34"        # primary accent (leans yellow-green; never reads as "win")
OLIVE_DARK = "#525C27"   # headers / hover
OLIVE_LIGHT = "#A9B36B"  # fills / secondary series
WIN = "#2E8B57"          # brighter, cooler green = win / positive R — kept visibly distinct
                         # from brand olive (CLAUDE.md's originally-documented win colour)
LOSS = "#A8574A"         # muted terracotta = loss / negative R (toned down from a bright red)
BG = "#FAF8F2"           # warm off-white background
CARD = "#F1EFE6"         # card / secondary background
TEXT = "#2B2B26"         # near-black warm
MUTED = "#6B6B60"        # secondary text
GRID = "#E4E1D5"         # gridlines

# Categorical sequence for charts (accent first, semantics available separately).
COLORWAY = [OLIVE, OLIVE_LIGHT, "#B08D57", "#4C7A88", "#8C6A9E", MUTED]

SERIF = "Iowan Old Style, Georgia, ui-serif, 'Times New Roman', serif"


def pl_color(value: float) -> str:
    """Semantic colour for a P&L or R value: green if >= 0 else red."""
    return WIN if value is not None and value >= 0 else LOSS


TEMPLATE_NAME = "trading_journal"


def register_template() -> str:
    """Register and return the Plotly template name. Call once at app start."""
    template = go.layout.Template(
        layout=go.Layout(
            paper_bgcolor=BG,
            plot_bgcolor=BG,
            font=dict(color=TEXT, family="sans-serif", size=13),
            colorway=COLORWAY,
            xaxis=dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID),
            yaxis=dict(gridcolor=GRID, zerolinecolor=GRID, linecolor=GRID),
            title=dict(font=dict(color=OLIVE_DARK, size=18)),
            legend=dict(bgcolor="rgba(0,0,0,0)"),
            margin=dict(l=48, r=24, t=56, b=40),
        )
    )
    pio.templates[TEMPLATE_NAME] = template
    pio.templates.default = TEMPLATE_NAME
    return TEMPLATE_NAME


def css() -> str:
    """CSS to inject via st.markdown(theme.css(), unsafe_allow_html=True).

    Applies the serif/tabular-nums treatment from the approved mockups to
    Streamlit's own metric and header widgets, so screens share one look.
    """
    return f"""
    <style>
      [data-testid="stMetricValue"] {{
        font-family: {SERIF};
        font-variant-numeric: tabular-nums;
        font-size: 22px;
      }}
      [data-testid="stMetricLabel"] {{ color: {MUTED}; font-size: 13px; }}
      [data-testid="stMetricDelta"] {{
        color: {MUTED} !important;
        background: transparent !important;
        padding: 0 !important;
        font-size: 12px;
      }}
      [data-testid="stMetricDelta"] svg {{ display: none; }}
      [data-testid="stAppViewContainer"] h1,
      [data-testid="stAppViewContainer"] h2,
      [data-testid="stAppViewContainer"] h3 {{
        font-family: {SERIF} !important;
        color: {OLIVE_DARK} !important;
      }}
      [data-testid="stAppViewContainer"] h1 {{ font-size: 28px !important; }}
      [data-testid="stAppViewContainer"] h2 {{ font-size: 18px !important; }}

      /* Input fills: paler than the page card colour, defined by a 1px warm
         border instead of a heavy fill — covers both widget implementations
         Streamlit uses under the hood (react-aria and BaseWeb). */
      [data-testid="stNumberInputContainer"],
      [data-testid="stSelectbox"] [role="group"],
      [data-testid="stMultiSelect"] [data-baseweb="select"] > div,
      [data-testid="stTextAreaRootElement"],
      [data-testid="stTextInput"] [data-baseweb="input"],
      [data-baseweb="input"] {{
        background-color: {BG} !important;
        border: 1px solid {GRID} !important;
      }}
      [data-testid="stNumberInputStepDown"],
      [data-testid="stNumberInputStepUp"] {{
        background-color: transparent !important;
        border-left: 1px solid {GRID} !important;
      }}

      /* Tabular figures everywhere numbers appear, so digits line up in
         columns — KPI values, P&L/price/R text, dataframe cells, and
         Plotly's own SVG tick/axis/bar-label text (inherits through). */
      [data-testid="stAppViewContainer"] {{
        font-variant-numeric: tabular-nums;
      }}
      [data-testid="stAppViewContainer"] .js-plotly-plot text {{
        font-variant-numeric: tabular-nums !important;
      }}

      /* Metric cards: light, consistent framing — restrained, no shadow. */
      [data-testid="stMetric"] {{
        background-color: {CARD};
        border: 1px solid {GRID};
        border-radius: 8px;
        padding: 14px 16px;
      }}
    </style>
    """

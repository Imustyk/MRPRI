"""Design tokens and global CSS for the dashboard.

The palette is the academic navy/gold/paper scheme the project already used.
This module keeps those brand colours but turns them into a real token set so
that cards, tabs, tables, badges and charts stay visually consistent.
"""

from __future__ import annotations

NAVY = "#1e3a5f"
GOLD = "#b8892a"
RED = "#b4232c"
GREEN = "#2a6b4a"
MUTED = "#5c6673"
PAPER = "#f4efe6"
CARD = "#fffdf8"

# --- extended tokens -------------------------------------------------------
NAVY_DEEP = "#16293f"
NAVY_SOFT = "#2f5686"
TEAL = "#2a7f8f"
AMBER = "#c98a12"
PLUM = "#6b4a86"
SLATE = "#8a93a0"
MUTED_SAFE = "#8a93a0"
INK = "#1b2430"

#: Semantic tones used by KPI cards, badges and callouts.
TONES = {
    "neutral": NAVY,
    "good": GREEN,
    "warn": AMBER,
    "bad": RED,
    "info": TEAL,
    "muted": SLATE,
}

#: Sequential / diverging scales for the Plotly charts.
SEQUENTIAL = [
    [0.0, "#eef3f8"],
    [0.35, "#9db8d2"],
    [0.7, NAVY_SOFT],
    [1.0, NAVY_DEEP],
]
DIVERGING = [
    [0.0, NAVY_DEEP],
    [0.25, "#7fa3c4"],
    [0.5, "#f4efe6"],
    [0.75, "#e0a08f"],
    [1.0, RED],
]
RISK_SCALE = {
    "unscored": SLATE,
    "low": GREEN,
    "medium": AMBER,
    "high": "#d1601a",
    "critical": RED,
}

PLOTLY_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="IBM Plex Sans, Source Sans 3, system-ui, sans-serif", color=INK, size=13),
    margin=dict(l=48, r=24, t=56, b=48),
    paper_bgcolor="rgba(0,0,0,0)",
    plot_bgcolor="rgba(0,0,0,0)",
    hoverlabel=dict(bgcolor="white", bordercolor="#d9d0c0", font_size=12, font_family="IBM Plex Sans, sans-serif"),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, bgcolor="rgba(0,0,0,0)"),
    colorway=[NAVY, GOLD, TEAL, PLUM, RED, GREEN, AMBER, SLATE],
    title=dict(font=dict(size=15, color=NAVY), x=0.01, xanchor="left", y=0.97, yanchor="top"),
    xaxis=dict(gridcolor="rgba(27,36,48,0.07)", zerolinecolor="rgba(27,36,48,0.18)", linecolor="rgba(27,36,48,0.18)"),
    yaxis=dict(gridcolor="rgba(27,36,48,0.07)", zerolinecolor="rgba(27,36,48,0.18)", linecolor="rgba(27,36,48,0.18)"),
)

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Source+Serif+4:wght@600;700&display=swap');

:root {
  --navy: #1e3a5f;
  --navy-deep: #16293f;
  --navy-soft: #2f5686;
  --gold: #b8892a;
  --red: #b4232c;
  --green: #2a6b4a;
  --amber: #c98a12;
  --teal: #2a7f8f;
  --plum: #6b4a86;
  --ink: #1b2430;
  --muted: #5c6673;
  --slate: #8a93a0;
  --paper: #f4efe6;
  --card: #fffdf8;
  --line: #e2dacb;
  --line-soft: #efe9dd;
  --radius: 12px;
  --shadow: 0 1px 2px rgba(27,36,48,.05), 0 8px 24px rgba(27,36,48,.06);
  --shadow-lift: 0 2px 4px rgba(27,36,48,.06), 0 14px 38px rgba(27,36,48,.10);
}

/* ---------- base typography ---------- */
html, body, [class*="css"], .stMarkdown, button, input, textarea, select {
  font-family: "IBM Plex Sans", system-ui, -apple-system, sans-serif;
}
.block-container { padding-top: 1.4rem; padding-bottom: 4rem; max-width: 1440px; }
h1, h2, h3, h4 { font-family: "Source Serif 4", Georgia, serif; color: var(--navy); letter-spacing: -0.02em; font-weight: 700; }
h1 { font-size: 2.05rem; line-height: 1.2; margin-bottom: .1rem; }
h2 { font-size: 1.45rem; margin-top: 1.4rem; }
h3 { font-size: 1.12rem; }
p, li { line-height: 1.62; }
a { color: var(--navy-soft); }

/* ---------- page header ---------- */
.page-head { border-bottom: 1px solid var(--line); padding-bottom: .85rem; margin-bottom: 1.15rem; }
.page-head .kicker {
  font-size: .72rem; font-weight: 700; letter-spacing: .13em; text-transform: uppercase;
  color: var(--gold); margin-bottom: .3rem;
}
.page-head h1 { margin: 0 0 .35rem 0; }
.page-head .sub { color: var(--muted); font-size: .97rem; margin: 0; max-width: 78ch; }

/* ---------- story / disclaimer / banners ---------- */
.story { color: var(--muted); font-size: .97rem; margin: 0 0 1rem 0; max-width: 92ch; }
.disclaimer {
  background: #fdf6e8; border: 1px solid #ecd9b0; border-left: 4px solid var(--gold);
  padding: .7rem .95rem; border-radius: 0 10px 10px 0; color: #4a3a1c; font-size: .89rem; margin: 0 0 1rem 0;
}
.disclaimer strong { color: #3a2c12; }
.demo-banner {
  background: #fdeced; border: 1px solid var(--red); color: #7a1218; padding: .7rem 1rem;
  border-radius: 10px; font-weight: 600; margin: 0 0 1rem 0;
}

/* ---------- KPI cards ---------- */
.kpi-grid { display: grid; gap: .7rem; margin: 0 0 .35rem 0; }
.kpi-card {
  position: relative; background: var(--card); border: 1px solid var(--line);
  border-radius: var(--radius); padding: .8rem .95rem .85rem 1.05rem;
  box-shadow: var(--shadow); overflow: hidden; transition: transform .14s ease, box-shadow .14s ease;
}
.kpi-card::before {
  content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
  background: var(--kpi-accent, var(--navy));
}
.kpi-card:hover { transform: translateY(-2px); box-shadow: var(--shadow-lift); }
.kpi-label {
  font-size: .715rem; font-weight: 700; letter-spacing: .085em; text-transform: uppercase;
  color: var(--muted); margin-bottom: .3rem; display: flex; align-items: center; gap: .3rem;
}
.kpi-value {
  font-size: 1.62rem; font-weight: 700; color: var(--navy-deep);
  font-variant-numeric: tabular-nums; letter-spacing: -0.025em; line-height: 1.12; word-break: break-word;
}
.kpi-value.sm { font-size: 1.22rem; }
.kpi-help { font-size: .76rem; color: var(--slate); margin-top: .3rem; line-height: 1.4; }
.kpi-delta { font-size: .78rem; font-weight: 600; margin-top: .28rem; }
.kpi-delta.up { color: var(--red); }
.kpi-delta.down { color: var(--green); }
.kpi-delta.flat { color: var(--slate); }

/* ---------- sections ---------- */
.section {
  background: var(--card); border: 1px solid var(--line-soft); border-radius: var(--radius);
  padding: 1rem 1.1rem; margin: 0 0 1rem 0; box-shadow: var(--shadow);
}
.section-title {
  font-family: "Source Serif 4", Georgia, serif; font-size: 1.06rem; font-weight: 700;
  color: var(--navy); margin: 0 0 .15rem 0; display: flex; align-items: center; gap: .45rem;
}
.section-note { font-size: .85rem; color: var(--muted); margin: 0 0 .7rem 0; }
.rule { height: 1px; background: var(--line-soft); margin: 1.2rem 0; border: 0; }

/* ---------- badges ---------- */
.badge {
  display: inline-block; background: #eef3f8; color: var(--navy); border: 1px solid #c5d0dc;
  border-radius: 999px; padding: .12rem .55rem; margin: .12rem .25rem .12rem 0;
  font-size: .775rem; font-weight: 600; white-space: nowrap;
}
.badge.risk   { background: #fde8ea; border-color: #e7b4b8; color: #7a1218; }
.badge.ok     { background: #e6f1ea; border-color: #b3d3c1; color: #1d4d35; }
.badge.warn   { background: #fdf2dd; border-color: #e6cd97; color: #6d4a06; }
.badge.info   { background: #e4f0f2; border-color: #a9cdd3; color: #1c5560; }
.badge.muted  { background: #f1f2f4; border-color: #dcdfe4; color: #545c67; }
.badge.solid  { background: var(--navy); border-color: var(--navy); color: #fff; }

/* ---------- sidebar ---------- */
[data-testid="stSidebar"] { background: var(--navy-deep); }
[data-testid="stSidebar"] > div { padding-top: 1.1rem; }
[data-testid="stSidebar"] * { color: #e8eef5 !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3,
[data-testid="stSidebar"] h4 { color: #fff !important; }
[data-testid="stSidebar"] .stRadio label, [dataid="stSidebar"] label { color: #e8eef5 !important; }
[data-testid="stSidebar"] hr { border-color: rgba(255,255,255,.14); }
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] caption { color: #a9bbcd !important; }
[data-testid="stSidebar"] strong { color: #fff !important; }

.brand { display: flex; align-items: center; gap: .55rem; margin-bottom: .1rem; }
.brand-mark {
  width: 34px; height: 34px; border-radius: 9px; flex: 0 0 34px;
  background: linear-gradient(140deg, var(--gold), #8f6a1f);
  display: flex; align-items: center; justify-content: center;
  color: #fff !important; font-size: 1rem; box-shadow: 0 2px 8px rgba(0,0,0,.28);
}
.brand-text { font-family: "Source Serif 4", Georgia, serif; font-size: 1.02rem; font-weight: 700; color: #fff !important; line-height: 1.2; }
.brand-sub { font-size: .74rem; color: #a9bbcd !important; line-height: 1.35; margin-top: .15rem; }

.nav-group {
  font-size: .68rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase;
  color: #8ea3b8 !important; margin: 1.05rem 0 .3rem 0;
}
.sidebar-stat {
  background: rgba(255,255,255,.07); border: 1px solid rgba(255,255,255,.12);
  border-radius: 10px; padding: .55rem .7rem; font-size: .8rem; color: #cfe0ee !important;
}
.sidebar-stat b { color: #fff !important; font-variant-numeric: tabular-nums; }
.sidebar-chip {
  display: inline-block; background: rgba(184,137,42,.22); border: 1px solid rgba(184,137,42,.5);
  color: #e8cf9a !important; border-radius: 999px; padding: .1rem .5rem; font-size: .72rem; font-weight: 600;
}

/* sidebar radio -> pill nav */
[data-testid="stSidebar"] [role="radiogroup"] { gap: .12rem; }
[data-testid="stSidebar"] [role="radiogroup"] label {
  border-radius: 8px; padding: .34rem .55rem; margin: 0; transition: background .12s ease;
}
[data-testid="stSidebar"] [role="radiogroup"] label:hover { background: rgba(255,255,255,.08) !important; }
[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {
  background: rgba(255,255,255,.14) !important; box-shadow: inset 3px 0 0 var(--gold);
}
[data-testid="stSidebar"] [role="radiogroup"] label p { font-size: .875rem; font-weight: 500; }

/* sidebar inputs need dark-on-light treatment */
[data-testid="stSidebar"] .stSelectbox div, [data-testid="stSidebar"] input,
[data-testid="stSidebar"] [data-baseweb="select"] { color: var(--ink) !important; }
[data-testid="stSidebar"] .stTextInput input, [data-testid="stSidebar"] .stNumberInput input {
  background: #fffdf8 !important; border-color: rgba(255,255,255,.2) !important;
}
[data-testid="stSidebar"] .stTextInput input:focus, [data-testid="stSidebar"] .stNumberInput input:focus {
  border-color: var(--gold) !important; box-shadow: 0 0 0 1px var(--gold) !important;
}
[data-testid="stSidebar"] [data-baseweb="popover"] { background: var(--card); }
[data-testid="stSidebar"] [data-baseweb="menu"] { background: var(--card); }
[data-testid="stSidebar"] [data-baseweb="select"] > div { background: #fffdf8 !important; }

/* ---------- tabs ---------- */
[data-baseweb="tab-list"] { gap: .1rem; border-bottom: 1px solid var(--line); margin-bottom: .9rem; }
[data-baseweb="tab"] {
  background: transparent; border: 0; padding: .5rem .85rem; border-radius: 8px 8px 0 0;
  color: var(--muted); font-weight: 600; font-size: .9rem; transition: color .12s ease, background .12s ease;
}
[data-baseweb="tab"]:hover { background: rgba(30,58,95,.06); color: var(--navy); }
[data-baseweb="tab"][aria-selected="true"] { color: var(--navy); box-shadow: inset 0 -3px 0 var(--gold); }
[data-baseweb="tab-highlight"] { background: var(--gold) !important; height: 3px; }
[data-baseweb="tab-border"] { background: var(--line); }
[data-testid="stTabs"] [data-baseweb="tab-panel"] { padding-top: .2rem; }

/* ---------- expander ---------- */
[data-testid="stExpander"] {
  border: 1px solid var(--line-soft); border-radius: 10px; background: var(--card);
  overflow: hidden; margin-bottom: .6rem;
}
[data-testid="stExpander"] summary { font-weight: 600; color: var(--navy); font-size: .92rem; padding: .55rem .8rem; }
[data-testid="stExpander"] summary:hover { background: rgba(30,58,95,.05); }

/* ---------- dataframes ---------- */
[data-testid="stDataFrame"] { border: 1px solid var(--line-soft); border-radius: 10px; overflow: hidden; }
[data-testid="stDataFrame"] [role="columnheader"] {
  background: #f1ece1 !important; color: var(--navy) !important; font-weight: 700 !important; font-size: .8rem !important;
}
[data-testid="stDataFrame"] [role="gridcell"] { font-size: .83rem; font-variant-numeric: tabular-nums; }
[data-testid="stDataFrame"] [role="row"]:hover [role="gridcell"] { background: rgba(184,137,42,.09) !important; }
[data-testid="stDataEditor"] { border: 1px solid var(--line-soft); border-radius: 10px; }

/* ---------- buttons ---------- */
.stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {
  border-radius: 9px; font-weight: 600; font-size: .875rem; border: 1px solid var(--line);
  background: var(--card); color: var(--navy); padding: .42rem .9rem;
  transition: transform .12s ease, box-shadow .12s ease, background .12s ease, border-color .12s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover, .stFormSubmitButton > button:hover {
  border-color: var(--navy-soft); color: var(--navy-deep); transform: translateY(-1px);
  box-shadow: 0 4px 14px rgba(27,36,48,.10); background: #fff;
}
.stButton > button[kind="primary"], .stFormSubmitButton > button[kind="primary"] {
  background: var(--navy); border-color: var(--navy); color: #fff;
}
.stButton > button[kind="primary"]:hover, .stFormSubmitButton > button[kind="primary"]:hover {
  background: var(--navy-soft); border-color: var(--navy-soft); color: #fff;
}
.stButton > button:disabled, .stDownloadButton > button:disabled {
  opacity: .48; transform: none; box-shadow: none; cursor: not-allowed;
}
button:focus-visible, input:focus-visible, [role="tab"]:focus-visible, summary:focus-visible {
  outline: 2px solid var(--gold); outline-offset: 2px;
}

/* ---------- forms / inputs ---------- */
[data-testid="stForm"] { border: 1px solid var(--line-soft); border-radius: var(--radius); padding: 1rem 1.1rem; background: var(--card); }
[data-testid="stFormBorder"] { background: var(--card); }
[data-testid="stSidebar"] [data-testid="stForm"] { background: rgba(255,255,255,.05); border-color: rgba(255,255,255,.12); }
[data-testid="stWidgetLabel"] label, .stSelectbox label, .stMultiSelect label, .stTextInput label,
.stNumberInput label, .stDateInput label, .stSlider label, .stRadio label, .stCheckbox label {
  font-size: .8rem !important; font-weight: 600 !important; color: var(--muted) !important;
  letter-spacing: .01em;
}
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] label { color: #cfe0ee !important; }
input, textarea, [data-baseweb="select"] > div { border-radius: 9px !important; }
textarea { font-family: "IBM Plex Sans", system-ui, sans-serif !important; line-height: 1.5; }

/* ---------- alerts ---------- */
[data-testid="stAlert"] { border-radius: 10px; border: 1px solid var(--line); font-size: .89rem; }
[data-testid="stAlert"][data-baseweb="kind="info"]     { background: #eef4f8; border-color: #c5d6e4; color: #1d3d5c; }
[data-testid="stAlert"][data-baseweb="kind="warning"]  { background: #fdf6e8; border-color: #e6cd97; color: #5c4110; }
[data-testid="stAlert"][data-baseweb="kind="success"]  { background: #e9f2ec; border-color: #b3d3c1; color: #1d4d35; }
[data-testid="stAlert"][data-baseweb="kind="error"]    { background: #fdeced; border-color: #e7b4b8; color: #7a1218; }

/* ---------- metrics fallback (st.metric) ---------- */
[data-testid="stMetric"] {
  background: var(--card); border: 1px solid var(--line); border-radius: var(--radius);
  padding: .7rem .85rem; box-shadow: var(--shadow);
}
[data-testid="stMetricLabel"] { color: var(--muted); font-size: .78rem; }
[data-testid="stMetricValue"] { color: var(--navy-deep); font-weight: 700; }
[data-testid="stMetricDelta"] { font-size: .78rem; }

/* ---------- spinner / progress ---------- */
[data-testid="stSpinner"] i { border-top-color: var(--navy) !important; border-bottom-color: var(--gold) !important; }
[data-testid="stProgress"] [role="progressbar"] { background: #e7e1d4; border-radius: 999px; }
[data-testid="stProgress"] [role="progressbar"] > div { background: linear-gradient(90deg, var(--navy-soft), var(--navy)); border-radius: 999px; }

/* ---------- plotly modebar ---------- */
.js-plotly-plot .modebar { background: transparent !important; }
.js-plotly-plot .modebar-btn path { fill: var(--slate) !important; }
.js-plotly-plot .modebar-btn:hover path { fill: var(--navy) !important; }
.js-plotly-plot .plotly .cursor-crosshair { cursor: crosshair; }

/* ---------- misc ---------- */
hr { border-color: var(--line-soft); }
.stCaption, [data-testid="stCaptionContainer"] { color: var(--muted) !important; font-size: .82rem; line-height: 1.5; }
[data-testid="stCode"] { border-radius: 10px; border: 1px solid var(--line-soft); }
.stApp [data-testid="stVerticalBlock"] { gap: .35rem; }
#MainMenu, footer, [data-testid="stStatusWidget"] { visibility: hidden; height: 0; }
.app-footer {
  margin-top: 2.5rem; padding-top: .9rem; border-top: 1px solid var(--line-soft);
  font-size: .78rem; color: var(--slate); display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap;
}
.empty {
  border: 1px dashed var(--line); border-radius: var(--radius); background: rgba(255,253,248,.6);
  padding: 1.6rem 1.2rem; text-align: center; color: var(--muted); font-size: .9rem;
}
.empty .empty-title { font-weight: 700; color: var(--navy); font-size: 1rem; margin-bottom: .25rem; }
.legend-row { display: flex; gap: 1rem; flex-wrap: wrap; font-size: .8rem; color: var(--muted); margin: .3rem 0 .6rem 0; }
.legend-key { display: inline-flex; align-items: center; gap: .3rem; }
.legend-swatch { width: 11px; height: 11px; border-radius: 3px; display: inline-block; }

::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: #cfc6b4; border-radius: 999px; border: 2px solid var(--paper); }
::-webkit-scrollbar-thumb:hover { background: var(--slate); }
[data-testid="stSidebar"] ::-webkit-scrollbar-thumb { background: rgba(255,255,255,.22); border-color: transparent; }

@media (prefers-reduced-motion: reduce) {
  * { animation-duration: .001ms !important; transition-duration: .001ms !important; }
}
</style>
"""

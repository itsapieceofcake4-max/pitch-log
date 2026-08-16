"""
rugby/theme.py
==============
アプリ全体の見た目を一箇所に集約したデザインシステム。

コンセプト — Modern Turf
------------------------
「ピッチログ」の名のとおり **上質な芝** をモチーフにする。ベタ塗りの緑ではなく、
深いエメラルドを基調に刈り込みのストライプで質感を出し、プロ水準の戦術分析
ツールとしての落ち着きを狙う。

- **面は深い緑、データは明るく**。UI を沈ませ、選手・軌跡・数値だけが浮き上がる。
- **アクセントは 3 役に限定**（ゴールド＝操作 / シアン＝チームA / コーラル＝チームB）。
  色数を絞ることで視線が迷わない。
- **視線導線**：見出しには短いアクセントバーを添え、8px グリッドで余白を刻む。
  同じ役割の要素は必ず同じ形・同じ余白にして、目が形を再学習しなくて済むようにする。

このパレットは **Streamlit の CSS / Plotly のグラフ / 書き出す MP4** の
3 か所すべてが参照する。色を変えれば画面も動画も一緒に変わる。
"""

from __future__ import annotations

import streamlit as st


# ── パレット ──────────────────────────────────────────────────────────────────
# Tailwind 系のフラットな色域から、緑背景でも濁らないものを選んでいる。

COLORS = {
    # 面（深いエメラルド〜黒緑）
    "bg": "#071310",
    "surface": "#0C1E18",
    "surface_2": "#112A22",
    "surface_3": "#16362B",
    "border": "#1E4437",
    "border_soft": "#153328",

    # 文字（わずかに緑を含んだ白で、面となじませる）
    "text": "#E9F2ED",
    "text_muted": "#8FA89C",
    "text_dim": "#5E7A6D",

    # アクセント（操作＝ゴールド）
    "accent": "#FBBF24",
    "accent_soft": "#FCD34D",
    "accent_deep": "#D9A21B",

    # チーム・データ
    "team_a": "#22D3EE",        # cyan-400
    "team_b": "#FB7185",        # rose-400
    "unknown": "#94A3B8",       # slate-400
    "ball": "#FEF3C7",          # amber-100

    # 状態
    "ok": "#34D399",
    "warn": "#FBBF24",
    "danger": "#FB7185",

    # ピッチ（刈り込みストライプの濃淡）
    "turf_dark": "#0E3A27",
    "turf_light": "#134A32",
    "pitch_line": "#F1F7F4",
}

# 芝のストライプ幅（メートル）
TURF_STRIPE_M = 8.0

FONT_SANS = ('"Inter", "Roboto", -apple-system, BlinkMacSystemFont, '
             '"Segoe UI Variable Display", "Segoe UI", "Yu Gothic UI", '
             '"Hiragino Sans", "Noto Sans JP", Meiryo, sans-serif')


def _css() -> str:
    c = COLORS
    return f"""
<style>
/* Inter を読み込む。取得できない環境では下のフォールバックが効く */
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

:root {{
  --bg:{c['bg']}; --surface:{c['surface']}; --surface2:{c['surface_2']};
  --surface3:{c['surface_3']};
  --border:{c['border']}; --border-soft:{c['border_soft']};
  --text:{c['text']}; --muted:{c['text_muted']}; --dim:{c['text_dim']};
  --accent:{c['accent']}; --accent-soft:{c['accent_soft']}; --accent-deep:{c['accent_deep']};
  --team-a:{c['team_a']}; --team-b:{c['team_b']};
  --ok:{c['ok']}; --warn:{c['warn']}; --danger:{c['danger']};
  --turf-d:{c['turf_dark']}; --turf-l:{c['turf_light']};
  --font-sans:{FONT_SANS};
  --r-sm:8px; --r-md:12px; --r-lg:16px;
  --shadow: 0 10px 30px rgba(0,0,0,.42);
}}

/* ── 下地：芝の刈り込みを極薄く敷いて質感を出す ─────────── */
html, body, [data-testid="stAppViewContainer"] {{
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  -webkit-font-smoothing: antialiased;
}}
[data-testid="stAppViewContainer"] > .main {{
  background:
    radial-gradient(1100px 520px at 10% -10%, rgba(52,211,153,.055), transparent 60%),
    radial-gradient(900px 460px at 92% -6%, rgba(251,191,36,.045), transparent 62%),
    repeating-linear-gradient(
      100deg,
      rgba(255,255,255,.012) 0 64px,
      rgba(0,0,0,0) 64px 128px
    );
}}
[data-testid="stHeader"] {{ background: transparent; }}
[data-testid="stToolbar"] {{ right: 8px; }}
.block-container {{ padding-top: 1.1rem; padding-bottom: 3rem; max-width: 1520px; }}

/* ── タイポグラフィ ─────────────────────────────────── */
h1,h2,h3,h4 {{ letter-spacing:-.018em; font-weight:650; color:var(--text); }}
[data-testid="stMarkdownContainer"] p {{ color: var(--text); line-height:1.72; }}
[data-testid="stCaptionContainer"], .stCaption, small {{
  color: var(--muted) !important; line-height:1.62;
}}
hr {{ border-color: var(--border-soft) !important; margin:1.4rem 0 !important; }}
strong, b {{ color: var(--text); font-weight:650; }}
a {{ color: var(--accent-soft); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
code {{
  font-family: ui-monospace, "SF Mono", "Cascadia Mono", Consolas, monospace;
  font-size:.855em; background: var(--surface2); color: var(--accent-soft);
  border:1px solid var(--border-soft); border-radius:6px; padding:.12em .4em;
}}

/* ── 見出し（視線の起点）──────────────────────────── */
.pl-sec {{
  display:flex; align-items:center; gap:10px;
  margin: 4px 0 12px 0;
}}
.pl-sec::before {{
  content:""; width:3px; height:17px; border-radius:2px;
  background: linear-gradient(180deg, var(--accent), var(--accent-deep));
  flex:0 0 auto;
}}
.pl-sec h4 {{ margin:0; font-size:.98rem; font-weight:650; letter-spacing:.005em; }}
.pl-sec .sub {{ color:var(--dim); font-size:.78rem; margin-left:2px; }}

/* ── アプリヘッダー ─────────────────────────────────── */
.pl-header {{
  display:flex; align-items:center; gap:14px; flex-wrap:wrap;
  padding:14px 20px; margin:0 0 18px 0;
  background:
    linear-gradient(115deg, {c['surface']} 0%, {c['surface_2']} 55%, rgba(251,191,36,.07) 100%),
    repeating-linear-gradient(100deg, rgba(255,255,255,.016) 0 40px, rgba(0,0,0,0) 40px 80px);
  border:1px solid var(--border); border-radius: var(--r-lg);
  box-shadow: 0 1px 0 rgba(255,255,255,.05) inset, var(--shadow);
}}
.pl-mark {{
  display:flex; align-items:center; justify-content:center;
  width:40px; height:40px; border-radius:11px; font-size:20px;
  background: linear-gradient(145deg, {c['turf_light']}, {c['turf_dark']});
  border:1px solid rgba(251,191,36,.35);
  box-shadow: 0 0 20px rgba(251,191,36,.18), 0 2px 8px rgba(0,0,0,.4);
}}
.pl-title {{ display:flex; flex-direction:column; gap:2px; min-width:0; }}
.pl-title b {{
  font-size:1.06rem; font-weight:700; letter-spacing:.17em;
  text-transform:uppercase; line-height:1; white-space:nowrap;
}}
.pl-title span {{
  font-size:.75rem; color:var(--muted); letter-spacing:.015em;
  white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
}}
.pl-badge {{
  font-size:.66rem; font-weight:700; padding:3px 9px; border-radius:999px;
  letter-spacing:.11em; font-variant-numeric: tabular-nums;
  background:rgba(251,191,36,.11); color:var(--accent);
  border:1px solid rgba(251,191,36,.32);
}}
.pl-chips {{ margin-left:auto; display:flex; gap:7px; flex-wrap:wrap; }}
.pl-chip {{
  font-size:.71rem; font-weight:600; padding:6px 12px; border-radius:999px;
  letter-spacing:.06em; border:1px solid var(--border-soft);
  background:rgba(255,255,255,.022); color:var(--dim); white-space:nowrap;
  transition:.2s ease;
}}
.pl-chip.on {{
  color:{c['ok']}; border-color:rgba(52,211,153,.4); background:rgba(52,211,153,.1);
}}

/* ── タブ（横並びの導線）──────────────────────────── */
[data-testid="stTabs"] [role="tablist"] {{
  gap:2px; border-bottom:1px solid var(--border-soft); padding-bottom:0;
}}
[data-testid="stTabs"] button[role="tab"] {{
  height:auto; padding:10px 15px; border-radius:9px 9px 0 0;
  color:var(--dim); font-weight:600; font-size:.875rem;
  border-bottom:2px solid transparent; transition:.18s ease;
}}
[data-testid="stTabs"] button[role="tab"]:hover {{
  color:var(--text); background:rgba(255,255,255,.03);
}}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
  color:var(--accent); background:linear-gradient(180deg, rgba(251,191,36,.10), transparent);
  border-bottom:2px solid var(--accent);
}}
[data-testid="stTabs"] [data-baseweb="tab-highlight"] {{ background:transparent; }}

/* ── サイドバー ─────────────────────────────────────── */
[data-testid="stSidebar"] {{
  background: linear-gradient(180deg, {c['surface']}, {c['bg']} 72%);
  border-right:1px solid var(--border);
}}
[data-testid="stSidebar"] .block-container {{ padding-top:1.5rem; }}

/* ── 数値（比較しやすいよう桁を揃える）─────────────── */
[data-testid="stMetric"] {{
  background: linear-gradient(158deg, var(--surface), var(--surface2));
  border:1px solid var(--border); border-radius:var(--r-md);
  padding:14px 16px; transition:.2s ease;
}}
[data-testid="stMetric"]:hover {{
  border-color:rgba(251,191,36,.34); transform:translateY(-1px);
  box-shadow:0 8px 22px rgba(0,0,0,.32);
}}
[data-testid="stMetricLabel"] {{
  color:var(--muted) !important; font-size:.71rem !important;
  font-weight:600; letter-spacing:.07em; text-transform:uppercase;
}}
[data-testid="stMetricValue"] {{
  font-size:1.58rem !important; font-weight:600; color:var(--text);
  font-variant-numeric: tabular-nums lining-nums; letter-spacing:-.01em;
}}

/* ── パネル ─────────────────────────────────────────── */
[data-testid="stExpander"] {{
  background:var(--surface); border:1px solid var(--border);
  border-radius:var(--r-md); overflow:hidden;
}}
[data-testid="stExpander"] summary {{ font-weight:600; color:var(--text); }}
[data-testid="stExpander"] summary:hover {{ color:var(--accent); }}

/* ── 入力 ───────────────────────────────────────────── */
[data-baseweb="input"], [data-baseweb="select"] > div, [data-baseweb="textarea"] {{
  background:var(--surface2) !important; border-color:var(--border) !important;
  border-radius:var(--r-sm) !important;
}}
[data-baseweb="input"]:focus-within, [data-baseweb="select"] > div:focus-within {{
  border-color:var(--accent) !important;
  box-shadow:0 0 0 3px rgba(251,191,36,.15) !important;
}}
input, textarea {{ color:var(--text) !important; }}

/* ── ボタン ─────────────────────────────────────────── */
[data-testid="stBaseButton-secondary"], [data-testid="stDownloadButton"] button {{
  background:var(--surface2); color:var(--text); border:1px solid var(--border);
  border-radius:var(--r-sm); font-weight:600; transition:.18s ease;
}}
[data-testid="stBaseButton-secondary"]:hover, [data-testid="stDownloadButton"] button:hover {{
  border-color:var(--accent); color:var(--accent); background:rgba(251,191,36,.08);
}}
[data-testid="stBaseButton-primary"] {{
  background:linear-gradient(135deg, var(--accent-soft), var(--accent-deep));
  color:#241A02; border:none; border-radius:var(--r-sm); font-weight:700;
  box-shadow:0 5px 18px rgba(251,191,36,.22); transition:.18s ease;
}}
[data-testid="stBaseButton-primary"]:hover {{
  filter:brightness(1.06); box-shadow:0 8px 24px rgba(251,191,36,.32);
  transform:translateY(-1px);
}}

/* ── 通知 ───────────────────────────────────────────── */
[data-testid="stAlert"] {{
  border-radius:var(--r-sm); border:1px solid var(--border-soft);
  border-left-width:3px; background:var(--surface);
}}

/* ── スライダー ─────────────────────────────────────── */
[data-testid="stSlider"] [role="slider"] {{
  background:var(--accent) !important;
  box-shadow:0 0 0 4px rgba(251,191,36,.16) !important;
}}
[data-testid="stSlider"] [data-baseweb="slider"] div[style*="background"] {{
  background:var(--accent) !important;
}}

/* ── 表 ─────────────────────────────────────────────── */
[data-testid="stDataFrame"], [data-testid="stDataFrameResizable"] {{
  border:1px solid var(--border); border-radius:var(--r-md); overflow:hidden;
}}

/* ── 画像・動画：ピッチと同じ角丸で面を揃える ───────── */
[data-testid="stImage"] img, [data-testid="stVideo"] video {{
  border-radius:var(--r-md); border:1px solid var(--border-soft);
}}

/* ── 進行状況（サイドバー）──────────────────────────── */
.pl-step {{
  display:flex; align-items:center; gap:9px;
  padding:8px 11px; margin-bottom:5px; border-radius:var(--r-sm);
  background:rgba(255,255,255,.022); border:1px solid var(--border-soft);
  font-size:.845rem; color:var(--muted); transition:.18s ease;
}}
.pl-step.done {{
  color:var(--text); border-color:rgba(52,211,153,.3); background:rgba(52,211,153,.07);
}}
.pl-step.now {{
  color:var(--text); border-color:rgba(251,191,36,.42); background:rgba(251,191,36,.09);
}}
.pl-step .ic {{ font-size:.9rem; line-height:1; width:12px; text-align:center; }}
.pl-step.done .ic {{ color:var(--ok); }}
.pl-step.now .ic {{ color:var(--accent); }}
</style>
"""


def inject() -> None:
    """CSS を適用する。`st.set_page_config` の直後に一度だけ呼ぶ。"""
    st.markdown(_css(), unsafe_allow_html=True)


def header(subtitle: str, chips: list[tuple[str, bool]] | None = None) -> None:
    """アプリ上部の見出しバー。chips は (ラベル, 点灯するか)。"""
    items = "".join(
        f'<div class="pl-chip{" on" if on else ""}">{label}</div>'
        for label, on in (chips or [])
    )
    st.markdown(
        f'<div class="pl-header">'
        f'<div class="pl-mark">🏉</div>'
        f'<div class="pl-title"><b>Pitch&nbsp;Log</b><span>{subtitle}</span></div>'
        f'<div class="pl-badge">V25</div>'
        f'<div class="pl-chips">{items}</div>'
        f'</div>',
        unsafe_allow_html=True,
    )


def section(title: str, sub: str = "") -> None:
    """節見出し。左のアクセントバーが視線の起点になる。"""
    extra = f'<span class="sub">{sub}</span>' if sub else ""
    st.markdown(
        f'<div class="pl-sec"><h4>{title}</h4>{extra}</div>',
        unsafe_allow_html=True,
    )


def step_list(steps: list[tuple[str, bool, bool]]) -> None:
    """サイドバーの進行状況。(ラベル, 完了か, 現在地か)。"""
    html = []
    for label, done, now in steps:
        cls = "done" if done else ("now" if now else "")
        icon = "✓" if done else ("▸" if now else "○")
        html.append(f'<div class="pl-step {cls}"><span class="ic">{icon}</span>{label}</div>')
    st.markdown("".join(html), unsafe_allow_html=True)


# ── 芝のストライプ ────────────────────────────────────────────────────────────

def turf_stripes(x_min: float, x_max: float, stripe_m: float = TURF_STRIPE_M):
    """刈り込みストライプの区間を返す。[(x0, x1, 明るいほうか), ...]

    ピッチ描画（Plotly / OpenCV）の両方から使い、見た目を揃える。
    """
    out = []
    x = x_min
    i = 0
    while x < x_max:
        out.append((x, min(x + stripe_m, x_max), i % 2 == 1))
        x += stripe_m
        i += 1
    return out


# ── Plotly ────────────────────────────────────────────────────────────────────

def plotly_layout(**overrides) -> dict:
    """アプリと同じ見た目に揃えた Plotly レイアウト。"""
    base = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=COLORS["surface"],
        font=dict(color=COLORS["text"], family=FONT_SANS, size=12),
        margin=dict(l=12, r=12, t=34, b=12),
        colorway=[COLORS["accent"], COLORS["team_a"], COLORS["team_b"],
                  COLORS["ok"], COLORS["unknown"]],
        hoverlabel=dict(
            bgcolor=COLORS["surface_3"],
            bordercolor=COLORS["border"],
            font=dict(color=COLORS["text"], family=FONT_SANS, size=11),
        ),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
    )
    base.update(overrides)
    return base

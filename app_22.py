"""
app_22.py
=========
Pitch Log — Phase 4 Extended: 22-Player Scene Visualization Dashboard

Standard CSV input: Export_GSA_22players_30s.csv  (94 columns)
  Frame, Time,
  Ball_X/Y/GridID/xT,
  Home_P1_X/Y/GridID/xT … Home_P11_X/Y/GridID/xT,
  Away_P1_X/Y/GridID/xT … Away_P11_X/Y/GridID/xT

Features
--------
- Smooth Plotly-native animation (no st.rerun lag)
- Home players: blue  |  Away players: red  |  Ball: yellow
- Hover tooltip per player: GridID + xT + team/number
- xT heatmap background (toggle)
- xT timeline: Ball + selectable Home/Away player traces
- Causal contribution placeholders for all 22 players (GSA-ready)

Run
---
  streamlit run app_22.py
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Pitch Log — 22P",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── constants ─────────────────────────────────────────────────────────────────
PITCH_W = 105.0
PITCH_H = 68.0
X_BINS  = 105
Y_BINS  = 68

COLOR_HOME  = "#3b9eff"   # Home = blue (brighter)
COLOR_AWAY  = "#ff5555"   # Away = red  (brighter)
COLOR_BALL  = "#FFD700"   # Ball = yellow
COLOR_BG    = "#0e1825"
COLOR_PITCH = "#1a3d1a"

# ── Zone evaluation constants (mirrors xt_pipeline_22.py) ─────────────────────
ZONE_SAFE_MAX  = 0.33   # normalised X: safe zone upper bound
ZONE_BUILD_MAX = 0.66   # normalised X: build zone upper / attacking third start

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* ── Base ── */
.stApp, body {
    background-color: #0e1825 !important;
    color: #dde8f4 !important;
}
.main .block-container { padding-top: 1.2rem; }

/* ── 見出し ── */
h1, h2, h3, h4 { color: #ffffff !important; font-weight: 700; }

/* ── サイドバー ── */
section[data-testid="stSidebar"] {
    background-color: #13202f !important;
    border-right: 1px solid #1e3348;
}
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] li,
section[data-testid="stSidebar"] span,
section[data-testid="stSidebar"] label { color: #b0c8e0 !important; }
section[data-testid="stSidebar"] strong,
section[data-testid="stSidebar"] b     { color: #e8f2ff !important; }
section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3   { color: #e8f2ff !important; }

/* ── サイドバー コードブロック ── */
section[data-testid="stSidebar"] code {
    background: #091422; color: #5bbfff;
    padding: 2px 6px; border-radius: 4px; font-size: 0.82em;
}
section[data-testid="stSidebar"] pre {
    background: #091422 !important;
    border: 1px solid #1e3348; border-radius: 6px; padding: 8px 10px;
}
section[data-testid="stSidebar"] pre code {
    background: transparent; color: #5bbfff; padding: 0;
}

/* ── メトリクスカード ── */
div[data-testid="stMetric"] {
    background: #1a2e42 !important;
    border: 1px solid #234060 !important;
    border-radius: 10px !important;
    padding: 14px 18px !important;
}
div[data-testid="stMetricLabel"] p {
    color: #7aaac8 !important;
    font-size: 0.73rem !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    letter-spacing: 0.07em;
}
div[data-testid="stMetricValue"] {
    color: #5ec4ff !important;
    font-size: 1.65rem !important;
    font-weight: 700 !important;
}
div[data-testid="stMetricDelta"] { color: #4ade80 !important; }

/* ── エクスパンダー ── */
div[data-testid="stExpander"] {
    background: #1a2e42 !important;
    border: 1px solid #234060 !important;
    border-radius: 8px !important;
}
div[data-testid="stExpander"] summary {
    color: #c8dff0 !important; font-weight: 600;
}
div[data-testid="stExpander"] p,
div[data-testid="stExpander"] li { color: #9abcda !important; line-height: 1.75; }
div[data-testid="stExpander"] strong { color: #e0f0ff !important; }
div[data-testid="stExpander"] code {
    background: #091422; color: #5bbfff;
    padding: 2px 5px; border-radius: 3px; font-size: 0.82em;
}
div[data-testid="stExpander"] pre {
    background: #091422 !important;
    border: 1px solid #1e3348; border-radius: 6px;
}

/* ── キャプション ── */
.stCaption p, [data-testid="stCaptionContainer"] p {
    color: #7095b5 !important; font-size: 0.82rem !important;
}

/* ── Infoボックス ── */
div[data-testid="stInfo"] {
    background: #0f2540 !important;
    border-left: 4px solid #2e6fa8 !important;
}
div[data-testid="stInfo"] p { color: #93bfe0 !important; }

/* ── テキスト入力 ── */
.stTextInput input {
    background: #091422 !important; color: #dde8f4 !important;
    border: 1px solid #234060 !important; border-radius: 6px !important;
}
.stTextInput label { color: #7aaac8 !important; font-weight: 600 !important; }

/* ── スライダー ── */
.stSlider label { color: #9abcda !important; }

/* ── トグル ── */
.stToggle label, .stToggle p { color: #b8d4ec !important; }

/* ── マルチセレクト ── */
.stMultiSelect label { color: #7aaac8 !important; font-weight: 600 !important; }

/* ── 区切り線 ── */
hr { border-color: #1e3348 !important; margin: 0.7rem 0 !important; }

/* ── データテーブル ── */
.stDataFrame { border: 1px solid #234060; border-radius: 8px; overflow: hidden; }

/* ── スクロールバー ── */
::-webkit-scrollbar { width: 5px; }
::-webkit-scrollbar-track { background: #0e1825; }
::-webkit-scrollbar-thumb { background: #234060; border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: #2e5580; }
</style>
""", unsafe_allow_html=True)


# ── data loaders ──────────────────────────────────────────────────────────────

@st.cache_data(show_spinner="xTマップ読み込み中…")
def load_xt_map(path: str) -> np.ndarray:
    p = Path(path)
    if not p.exists():
        st.error(f"**{path}** が見つかりません。")
        st.stop()
    arr = pd.read_csv(p, index_col=0).values.astype(np.float32)
    if arr.shape != (Y_BINS, X_BINS):
        st.error(f"xTマップ shape 不正: {arr.shape}")
        st.stop()
    return arr


@st.cache_data(show_spinner="シーンデータ読み込み中…")
def load_scene(path: str, _mtime: float = 0.0) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        st.error(f"**{path}** が見つかりません。")
        st.stop()
    return pd.read_csv(p)


@st.cache_data(show_spinner="貢献度スコア読み込み中…")
def load_causal(path: str) -> pd.DataFrame | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        return pd.read_csv(p)
    except Exception:
        return None


def detect_fps(df: pd.DataFrame) -> float:
    """Infer playback FPS from the Time column."""
    if "Time" not in df.columns or len(df) < 2:
        return 25.0
    dt = pd.to_numeric(df["Time"], errors="coerce").diff().dropna().median()
    fps = round(1.0 / dt) if dt > 0 else 25.0
    return float(max(1, fps))


def _team_nums(df: pd.DataFrame, team: str) -> list[int]:
    nums = []
    for col in df.columns:
        m = re.match(rf"^{team}_P(\d+)_X$", col)
        if m and f"{team}_P{m.group(1)}_Y" in df.columns:
            nums.append(int(m.group(1)))
    return sorted(nums)

def home_nums(df: pd.DataFrame) -> list[int]: return _team_nums(df, "Home")
def away_nums(df: pd.DataFrame) -> list[int]: return _team_nums(df, "Away")


# ── Zone helpers ──────────────────────────────────────────────────────────────

def _dm(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance in metres between two normalised-[0,1] pitch coordinates."""
    return float(np.sqrt(((x1 - x2) * 105.0) ** 2 + ((y1 - y2) * 68.0) ** 2))


def _eff_x(x_norm: float, team: str) -> float:
    return (1.0 - x_norm) if team == "Away" else x_norm


def _compute_lbp_inapp(
    df: pd.DataFrame, fps: float, h_nums: list[int], a_nums: list[int]
) -> pd.DataFrame:
    """
    Compute line-breaking pass columns on the fly if not already present.
    Returns a new DataFrame; the original is never mutated.
    Mirrors add_zone_and_lbp_columns() in xt_pipeline_22.py.
    """
    if "is_line_breaking_pass" in df.columns:
        return df

    _CTRL_M = 2.0
    _TRAV_M = 8.0
    _DEF_M  = 3.0
    _LOOK   = 30

    n       = len(df)
    is_lbp  = np.zeros(n, dtype=int)
    passers = [""] * n
    recvs   = [""] * n
    defs_ct = np.zeros(n, dtype=int)

    def _holder(row, bx, by):
        bst, bd = (None, None), np.inf
        for pfx, nums in [("Home", h_nums), ("Away", a_nums)]:
            for num in nums:
                px = row.get(f"{pfx}_P{num}_X", np.nan)
                py = row.get(f"{pfx}_P{num}_Y", np.nan)
                if pd.isna(px) or pd.isna(py):
                    continue
                d = _dm(float(px), float(py), bx, by)
                if d < bd:
                    bd, bst = d, (pfx, num)
        return bst if bd <= _CTRL_M else (None, None)

    i = 0
    while i < n:
        row = df.iloc[i]
        bx  = float(row.get("Ball_X", np.nan))
        by  = float(row.get("Ball_Y", np.nan))
        if np.isnan(bx) or np.isnan(by):
            i += 1
            continue

        pt, pn = _holder(row, bx, by)
        if pt is None:
            i += 1
            continue

        px_n   = float(row.get(f"{pt}_P{pn}_X", np.nan))
        eff_px = _eff_x(px_n, pt)
        if not (ZONE_SAFE_MAX <= eff_px < ZONE_BUILD_MAX):
            i += 1
            continue

        found = False
        for k in range(1, min(_LOOK + 1, n - i)):
            fr  = df.iloc[i + k]
            fbx = float(fr.get("Ball_X", np.nan))
            fby = float(fr.get("Ball_Y", np.nan))
            if np.isnan(fbx) or np.isnan(fby):
                continue
            if _dm(bx, by, fbx, fby) < _TRAV_M:
                continue

            rt, rn = _holder(fr, fbx, fby)
            if rt is None or rt != pt or rn == pn:
                continue

            rx_n   = float(fr.get(f"{rt}_P{rn}_X", np.nan))
            eff_rx = _eff_x(rx_n, rt)
            if eff_rx < ZONE_BUILD_MAX:
                continue

            dp  = "Away" if pt == "Home" else "Home"
            dns = a_nums if pt == "Home" else h_nums
            nb  = 0
            for dn in dns:
                dx = fr.get(f"{dp}_P{dn}_X", np.nan)
                dy = fr.get(f"{dp}_P{dn}_Y", np.nan)
                if not (pd.isna(dx) or pd.isna(dy)):
                    if _dm(float(dx), float(dy), fbx, fby) <= _DEF_M:
                        nb += 1

            pid = f"{pt}_P{pn}"
            rid = f"{rt}_P{rn}"
            for j in range(i, i + k + 1):
                is_lbp[j]  = 1
                passers[j] = pid
                recvs[j]   = rid
                defs_ct[j] = nb

            found = True
            i += k + 1
            break

        if not found:
            i += 1

    out = df.copy()
    out["is_line_breaking_pass"] = is_lbp
    out["lbp_passer"]            = passers
    out["lbp_receiver"]          = recvs
    out["lbp_nearby_def_count"]  = defs_ct
    return out


def _zone_boundary_traces() -> list:
    """Dashed white vertical lines at zone boundaries (X=0.33 and X=0.66 normalised)."""
    traces = []
    for x_norm in [ZONE_SAFE_MAX, ZONE_BUILD_MAX]:
        x_m = x_norm * PITCH_W
        traces.append(go.Scatter(
            x=[x_m, x_m], y=[0.0, PITCH_H],
            mode="lines",
            line=dict(color="rgba(255,255,255,0.38)", width=1.5, dash="dash"),
            showlegend=False, hoverinfo="skip",
        ))
    return traces


# ── pitch lines (static traces) ───────────────────────────────────────────────

def _pitch_traces() -> list:
    lc, lw = "rgba(255,255,255,0.82)", 1.6
    W, H   = PITCH_W, PITCH_H

    def ln(x0, y0, x1, y1):
        return go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines",
                          line=dict(color=lc, width=lw),
                          showlegend=False, hoverinfo="skip")

    def arc(cx, cy, r, a0=0, a1=360, n=72):
        t = np.linspace(np.radians(a0), np.radians(a1), n)
        return go.Scatter(x=(cx + r * np.cos(t)).tolist(),
                          y=(cy + r * np.sin(t)).tolist(),
                          mode="lines", line=dict(color=lc, width=lw),
                          showlegend=False, hoverinfo="skip")

    return [
        ln(0, 0, W, 0), ln(W, 0, W, H), ln(W, H, 0, H), ln(0, H, 0, 0),
        ln(W/2, 0, W/2, H), arc(W/2, H/2, 9.15),
        ln(0, H/2-20.16, 16.5, H/2-20.16),
        ln(16.5, H/2-20.16, 16.5, H/2+20.16),
        ln(16.5, H/2+20.16, 0, H/2+20.16),
        ln(W, H/2-20.16, W-16.5, H/2-20.16),
        ln(W-16.5, H/2-20.16, W-16.5, H/2+20.16),
        ln(W-16.5, H/2+20.16, W, H/2+20.16),
        ln(0, H/2-9.16, 5.5, H/2-9.16),
        ln(5.5, H/2-9.16, 5.5, H/2+9.16),
        ln(5.5, H/2+9.16, 0, H/2+9.16),
        ln(W, H/2-9.16, W-5.5, H/2-9.16),
        ln(W-5.5, H/2-9.16, W-5.5, H/2+9.16),
        ln(W-5.5, H/2+9.16, W, H/2+9.16),
        arc(11, H/2, 9.15), arc(W-11, H/2, 9.15),
        go.Scatter(x=[11, W-11], y=[H/2, H/2], mode="markers",
                   marker=dict(size=4, color=lc),
                   showlegend=False, hoverinfo="skip"),
        ln(0, H/2-3.66, -2, H/2-3.66),
        ln(-2, H/2-3.66, -2, H/2+3.66),
        ln(-2, H/2+3.66, 0, H/2+3.66),
        ln(W, H/2-3.66, W+2, H/2-3.66),
        ln(W+2, H/2-3.66, W+2, H/2+3.66),
        ln(W+2, H/2+3.66, W, H/2+3.66),
    ]


# ── animated figure (all frames pre-computed, Plotly JS handles playback) ─────

@st.cache_data(show_spinner="アニメーション生成中… (初回のみ数秒かかります)")
def build_animated_fig(
    xt_path: str,
    scene_path: str,
    show_xt: bool,
    trail_frames: int,
    fps: float = 25.0,
) -> go.Figure:
    """
    Pre-compute 750 Plotly frames so playback runs entirely in the browser.

    Animated trace layout per frame (6 traces):
        0  ball trail
        1  home trails  (all 11 combined with None separators)
        2  away trails  (all 11 combined with None separators)
        3  home player dots  (markers+text, blue, with hover customdata)
        4  away player dots  (markers+text, red,  with hover customdata)
        5  ball dot          (marker, yellow, with hover)
    """
    xt_map   = load_xt_map(xt_path)
    df       = load_scene(scene_path)
    h_nums   = home_nums(df)
    a_nums   = away_nums(df)
    n_frames = len(df)

    # ── static traces ─────────────────────────────────────────────────────────
    static: list = []

    if show_xt:
        xc   = np.arange(X_BINS) + 0.5
        yc   = np.arange(Y_BINS) + 0.5
        zmax = float(np.percentile(xt_map[xt_map > 0], 99)) if xt_map.max() > 0 else 1.0
        static.append(go.Heatmap(
            z=xt_map.tolist(), x=xc.tolist(), y=yc.tolist(),
            colorscale=[
                [0.00, "rgba(0,40,0,0)"],
                [0.25, "rgba(50,205,50,0.18)"],
                [0.50, "rgba(255,215,0,0.35)"],
                [0.75, "rgba(255,100,0,0.55)"],
                [1.00, "rgba(200,0,30,0.80)"],
            ],
            zmin=0, zmax=zmax,
            showscale=True,
            colorbar=dict(
                title=dict(text="xT", font=dict(color="white", size=11)),
                thickness=10, len=0.55,
                tickfont=dict(color="white", size=9),
            ),
            hoverinfo="skip",
        ))

    for tr in _pitch_traces():
        static.append(tr)

    n_static     = len(static)
    n_anim       = 6
    anim_indices = list(range(n_static, n_static + n_anim))

    # ── per-frame trace builder ───────────────────────────────────────────────
    def make_frame(idx: int) -> list:
        row = df.iloc[idx]
        t0  = max(0, idx - trail_frames)
        tdf = df.iloc[t0 : idx + 1]
        out = []

        # ① ball trail
        out.append(go.Scatter(
            x=(tdf["Ball_X"].values * PITCH_W).tolist(),
            y=(tdf["Ball_Y"].values * PITCH_H).tolist(),
            mode="lines",
            line=dict(color="rgba(255,215,0,0.35)", width=1.5, dash="dot"),
            showlegend=False, hoverinfo="skip",
        ))

        # ② home trails — all 11 players combined (None = line break)
        hx_t, hy_t = [], []
        for n in h_nums:
            hx_t.extend((tdf[f"Home_P{n}_X"].values * PITCH_W).tolist() + [None])
            hy_t.extend((tdf[f"Home_P{n}_Y"].values * PITCH_H).tolist() + [None])
        out.append(go.Scatter(
            x=hx_t, y=hy_t, mode="lines",
            line=dict(color="rgba(30,144,255,0.22)", width=1),
            showlegend=False, hoverinfo="skip",
        ))

        # ③ away trails — all 11 players combined
        ax_t, ay_t = [], []
        for n in a_nums:
            ax_t.extend((tdf[f"Away_P{n}_X"].values * PITCH_W).tolist() + [None])
            ay_t.extend((tdf[f"Away_P{n}_Y"].values * PITCH_H).tolist() + [None])
        out.append(go.Scatter(
            x=ax_t, y=ay_t, mode="lines",
            line=dict(color="rgba(255,68,68,0.22)", width=1),
            showlegend=False, hoverinfo="skip",
        ))

        # ④ home player dots (blue)
        hpx = [float(row.get(f"Home_P{n}_X", np.nan)) * PITCH_W for n in h_nums]
        hpy = [float(row.get(f"Home_P{n}_Y", np.nan)) * PITCH_H for n in h_nums]
        h_cd = [
            [n,
             int(row.get(f"Home_P{n}_GridID") or 0),
             float(row.get(f"Home_P{n}_xT") or 0.0)]
            for n in h_nums
        ]
        out.append(go.Scatter(
            x=hpx, y=hpy,
            mode="markers+text",
            marker=dict(size=22, color=COLOR_HOME,
                        line=dict(color="white", width=1.8)),
            text=[str(n) for n in h_nums],
            textfont=dict(color="white", size=10, family="Arial Black"),
            textposition="middle center",
            customdata=h_cd,
            hovertemplate=(
                "<b>Home P%{customdata[0]}</b><br>"
                "GridID : %{customdata[1]}<br>"
                "xT     : %{customdata[2]:.4f}"
                "<extra></extra>"
            ),
            showlegend=False,
        ))

        # ⑤ away player dots (red)
        apx = [float(row.get(f"Away_P{n}_X", np.nan)) * PITCH_W for n in a_nums]
        apy = [float(row.get(f"Away_P{n}_Y", np.nan)) * PITCH_H for n in a_nums]
        a_cd = [
            [n,
             int(row.get(f"Away_P{n}_GridID") or 0),
             float(row.get(f"Away_P{n}_xT") or 0.0)]
            for n in a_nums
        ]
        out.append(go.Scatter(
            x=apx, y=apy,
            mode="markers+text",
            marker=dict(size=22, color=COLOR_AWAY,
                        line=dict(color="white", width=1.8)),
            text=[str(n) for n in a_nums],
            textfont=dict(color="white", size=10, family="Arial Black"),
            textposition="middle center",
            customdata=a_cd,
            hovertemplate=(
                "<b>Away P%{customdata[0]}</b><br>"
                "GridID : %{customdata[1]}<br>"
                "xT     : %{customdata[2]:.4f}"
                "<extra></extra>"
            ),
            showlegend=False,
        ))

        # ⑥ ball dot (yellow)
        bx  = row.get("Ball_X",      np.nan)
        by  = row.get("Ball_Y",      np.nan)
        bxt = float(row.get("Ball_xT",     0) or 0)
        bgd = int(row.get("Ball_GridID",   0) or 0)
        out.append(go.Scatter(
            x=[float(bx) * PITCH_W] if pd.notna(bx) else [None],
            y=[float(by) * PITCH_H] if pd.notna(by) else [None],
            mode="markers",
            marker=dict(size=14, color=COLOR_BALL,
                        line=dict(color="#888", width=1.5)),
            customdata=[[bxt, bgd]],
            hovertemplate=(
                "<b>Ball</b><br>"
                "GridID : %{customdata[1]}<br>"
                "xT     : %{customdata[0]:.4f}"
                "<extra></extra>"
            ),
            showlegend=False,
        ))
        return out

    # ── pre-compute all frames ────────────────────────────────────────────────
    frames = [
        go.Frame(data=make_frame(i), name=str(i), traces=anim_indices)
        for i in range(n_frames)
    ]

    # ── slider steps (sample to keep DOM light) ───────────────────────────────
    step_every   = max(1, n_frames // 150)
    slider_steps = [
        {
            "args": [[str(i)], {
                "frame": {"duration": 0, "redraw": True},
                "mode": "immediate", "transition": {"duration": 0},
            }],
            "label": str(int(df.iloc[i]["Frame"])),
            "method": "animate",
        }
        for i in range(0, n_frames, step_every)
    ]

    # ── assemble ──────────────────────────────────────────────────────────────
    fig = go.Figure(data=static + make_frame(0), frames=frames)

    btn_common = {"fromcurrent": True, "transition": {"duration": 0}}
    fig.update_layout(
        plot_bgcolor=COLOR_PITCH,
        paper_bgcolor=COLOR_BG,
        xaxis=dict(range=[-4, PITCH_W + 4], showgrid=False, zeroline=False,
                   color="white", title="", fixedrange=True),
        yaxis=dict(range=[-4, PITCH_H + 4], showgrid=False, zeroline=False,
                   scaleanchor="x", scaleratio=1,
                   color="white", title="", fixedrange=True),
        margin=dict(l=5, r=50, t=10, b=100),
        height=590,
        dragmode=False,
        showlegend=False,
        updatemenus=[{
            "type": "buttons",
            "showactive": True,
            "bgcolor": "#1e2a1e",
            "bordercolor": "rgba(255,255,255,0.20)",
            "font": {"color": "white", "size": 13},
            "x": 0.0, "y": -0.13,
            "xanchor": "left", "yanchor": "top",
            "direction": "left",
            "buttons": [
                {"label": "▶ ×1",
                 "method": "animate",
                 "args": [None, {"frame": {"duration": int(1000 / fps), "redraw": True},
                                 **btn_common}]},
                {"label": "⏸",
                 "method": "animate",
                 "args": [[None], {"frame": {"duration": 0, "redraw": False},
                                   "mode": "immediate", "transition": {"duration": 0}}]},
                {"label": "×0.5",
                 "method": "animate",
                 "args": [None, {"frame": {"duration": int(2000 / fps), "redraw": True},
                                 **btn_common}]},
                {"label": "×2",
                 "method": "animate",
                 "args": [None, {"frame": {"duration": int(500 / fps), "redraw": True},
                                 **btn_common}]},
                {"label": "×4",
                 "method": "animate",
                 "args": [None, {"frame": {"duration": int(250 / fps), "redraw": True},
                                 **btn_common}]},
                {"label": "⏮",
                 "method": "animate",
                 "args": [["0"], {"frame": {"duration": 0, "redraw": True},
                                  "mode": "immediate", "transition": {"duration": 0}}]},
            ],
        }],
        sliders=[{
            "active": 0,
            "currentvalue": {
                "prefix": "Frame: ",
                "font": {"color": "white", "size": 11},
                "visible": True, "xanchor": "center",
            },
            "bgcolor": "#1e2a1e",
            "bordercolor": "rgba(255,255,255,0.20)",
            "font": {"color": "white", "size": 9},
            "tickcolor": "rgba(255,255,255,0.35)",
            "pad": {"t": 60, "b": 5},
            "len": 1.0, "x": 0, "y": 0,
            "steps": slider_steps,
        }],
    )
    return fig


# ── Zone-mode animated figure ─────────────────────────────────────────────────

@st.cache_data(show_spinner="ゾーン別アニメーション生成中… (初回のみ数秒かかります)")
def build_zone_animated_fig(
    xt_path: str,
    scene_path: str,
    show_xt: bool,
    trail_frames: int,
    fps: float = 25.0,
) -> go.Figure:
    """
    Zone-mode variant of build_animated_fig.
    Adds:
      - Zone boundary lines (static: dashed white at x=34.65m and x=69.3m)
      - 3 extra animated traces per frame (LBP arrow + passer glow + receiver glow)
    Original 6 animated traces are identical to the normal mode.
    build_animated_fig is NOT touched.
    """
    xt_map   = load_xt_map(xt_path)
    df       = load_scene(scene_path)
    h_nums   = home_nums(df)
    a_nums   = away_nums(df)
    n_frames = len(df)

    # Ensure LBP columns exist
    df = _compute_lbp_inapp(df, fps, h_nums, a_nums)

    lbp_flags   = df["is_line_breaking_pass"].values
    lbp_passers = df["lbp_passer"].values
    lbp_recvs   = df["lbp_receiver"].values

    # ── static traces ─────────────────────────────────────────────────────────
    static: list = []

    if show_xt:
        xc   = np.arange(X_BINS) + 0.5
        yc   = np.arange(Y_BINS) + 0.5
        zmax = float(np.percentile(xt_map[xt_map > 0], 99)) if xt_map.max() > 0 else 1.0
        static.append(go.Heatmap(
            z=xt_map.tolist(), x=xc.tolist(), y=yc.tolist(),
            colorscale=[
                [0.00, "rgba(0,40,0,0)"],
                [0.25, "rgba(50,205,50,0.18)"],
                [0.50, "rgba(255,215,0,0.35)"],
                [0.75, "rgba(255,100,0,0.55)"],
                [1.00, "rgba(200,0,30,0.80)"],
            ],
            zmin=0, zmax=zmax,
            showscale=True,
            colorbar=dict(
                title=dict(text="xT", font=dict(color="white", size=11)),
                thickness=10, len=0.55,
                tickfont=dict(color="white", size=9),
            ),
            hoverinfo="skip",
        ))

    for tr in _pitch_traces():
        static.append(tr)

    # Zone boundary dashed lines
    for tr in _zone_boundary_traces():
        static.append(tr)

    n_static     = len(static)
    n_anim       = 9   # 6 original + 3 LBP overlays (arrow, passer glow, receiver glow)
    anim_indices = list(range(n_static, n_static + n_anim))

    def _player_pos_m(row, player_id: str):
        """Return (x_metres, y_metres) for a player id like 'Home_P3', or (None, None)."""
        if not player_id:
            return None, None
        xv = row.get(f"{player_id}_X", np.nan)
        yv = row.get(f"{player_id}_Y", np.nan)
        if pd.isna(xv) or pd.isna(yv):
            return None, None
        return float(xv) * PITCH_W, float(yv) * PITCH_H

    def make_zone_frame(idx: int) -> list:
        row = df.iloc[idx]
        t0  = max(0, idx - trail_frames)
        tdf = df.iloc[t0 : idx + 1]
        out = []

        # ① ball trail
        out.append(go.Scatter(
            x=(tdf["Ball_X"].values * PITCH_W).tolist(),
            y=(tdf["Ball_Y"].values * PITCH_H).tolist(),
            mode="lines",
            line=dict(color="rgba(255,215,0,0.35)", width=1.5, dash="dot"),
            showlegend=False, hoverinfo="skip",
        ))

        # ② home trails
        hx_t, hy_t = [], []
        for n in h_nums:
            hx_t.extend((tdf[f"Home_P{n}_X"].values * PITCH_W).tolist() + [None])
            hy_t.extend((tdf[f"Home_P{n}_Y"].values * PITCH_H).tolist() + [None])
        out.append(go.Scatter(x=hx_t, y=hy_t, mode="lines",
                              line=dict(color="rgba(30,144,255,0.22)", width=1),
                              showlegend=False, hoverinfo="skip"))

        # ③ away trails
        ax_t, ay_t = [], []
        for n in a_nums:
            ax_t.extend((tdf[f"Away_P{n}_X"].values * PITCH_W).tolist() + [None])
            ay_t.extend((tdf[f"Away_P{n}_Y"].values * PITCH_H).tolist() + [None])
        out.append(go.Scatter(x=ax_t, y=ay_t, mode="lines",
                              line=dict(color="rgba(255,68,68,0.22)", width=1),
                              showlegend=False, hoverinfo="skip"))

        # ④ home player dots (blue)
        hpx = [float(row.get(f"Home_P{n}_X", np.nan)) * PITCH_W for n in h_nums]
        hpy = [float(row.get(f"Home_P{n}_Y", np.nan)) * PITCH_H for n in h_nums]
        h_cd = [
            [n, int(row.get(f"Home_P{n}_GridID") or 0), float(row.get(f"Home_P{n}_xT") or 0.0)]
            for n in h_nums
        ]
        out.append(go.Scatter(
            x=hpx, y=hpy,
            mode="markers+text",
            marker=dict(size=22, color=COLOR_HOME, line=dict(color="white", width=1.8)),
            text=[str(n) for n in h_nums],
            textfont=dict(color="white", size=10, family="Arial Black"),
            textposition="middle center",
            customdata=h_cd,
            hovertemplate=(
                "<b>Home P%{customdata[0]}</b><br>"
                "GridID : %{customdata[1]}<br>"
                "xT     : %{customdata[2]:.4f}"
                "<extra></extra>"
            ),
            showlegend=False,
        ))

        # ⑤ away player dots (red)
        apx = [float(row.get(f"Away_P{n}_X", np.nan)) * PITCH_W for n in a_nums]
        apy = [float(row.get(f"Away_P{n}_Y", np.nan)) * PITCH_H for n in a_nums]
        a_cd = [
            [n, int(row.get(f"Away_P{n}_GridID") or 0), float(row.get(f"Away_P{n}_xT") or 0.0)]
            for n in a_nums
        ]
        out.append(go.Scatter(
            x=apx, y=apy,
            mode="markers+text",
            marker=dict(size=22, color=COLOR_AWAY, line=dict(color="white", width=1.8)),
            text=[str(n) for n in a_nums],
            textfont=dict(color="white", size=10, family="Arial Black"),
            textposition="middle center",
            customdata=a_cd,
            hovertemplate=(
                "<b>Away P%{customdata[0]}</b><br>"
                "GridID : %{customdata[1]}<br>"
                "xT     : %{customdata[2]:.4f}"
                "<extra></extra>"
            ),
            showlegend=False,
        ))

        # ⑥ ball dot (yellow)
        bx  = row.get("Ball_X",    np.nan)
        by  = row.get("Ball_Y",    np.nan)
        bxt = float(row.get("Ball_xT",   0) or 0)
        bgd = int(row.get("Ball_GridID", 0) or 0)
        out.append(go.Scatter(
            x=[float(bx) * PITCH_W] if pd.notna(bx) else [None],
            y=[float(by) * PITCH_H] if pd.notna(by) else [None],
            mode="markers",
            marker=dict(size=14, color=COLOR_BALL, line=dict(color="#888", width=1.5)),
            customdata=[[bxt, bgd]],
            hovertemplate=(
                "<b>Ball</b><br>"
                "GridID : %{customdata[1]}<br>"
                "xT     : %{customdata[0]:.4f}"
                "<extra></extra>"
            ),
            showlegend=False,
        ))

        # ⑦⑧⑨ LBP overlays (empty when no line-breaking pass)
        is_lbp_f = bool(lbp_flags[idx])
        if is_lbp_f:
            p_id = lbp_passers[idx]
            r_id = lbp_recvs[idx]
            px_m, py_m = _player_pos_m(row, p_id)
            rx_m, ry_m = _player_pos_m(row, r_id)
        else:
            px_m = py_m = rx_m = ry_m = None

        # ⑦ Green arrow: passer → receiver
        out.append(go.Scatter(
            x=[px_m, rx_m] if (px_m is not None and rx_m is not None) else [],
            y=[py_m, ry_m] if (py_m is not None and ry_m is not None) else [],
            mode="lines",
            line=dict(color="rgba(0,255,128,0.90)", width=5),
            showlegend=False, hoverinfo="skip",
        ))

        # ⑧ Passer glow (large semi-transparent green ring)
        out.append(go.Scatter(
            x=[px_m] if px_m is not None else [],
            y=[py_m] if py_m is not None else [],
            mode="markers",
            marker=dict(
                size=46, color="rgba(0,255,128,0.18)",
                line=dict(color="rgba(0,255,128,0.90)", width=3),
            ),
            showlegend=False, hoverinfo="skip",
        ))

        # ⑨ Receiver glow
        out.append(go.Scatter(
            x=[rx_m] if rx_m is not None else [],
            y=[ry_m] if ry_m is not None else [],
            mode="markers",
            marker=dict(
                size=46, color="rgba(0,255,128,0.18)",
                line=dict(color="rgba(0,255,128,0.90)", width=3),
            ),
            showlegend=False, hoverinfo="skip",
        ))

        return out

    # ── pre-compute all frames ────────────────────────────────────────────────
    frames = [
        go.Frame(data=make_zone_frame(i), name=str(i), traces=anim_indices)
        for i in range(n_frames)
    ]

    step_every   = max(1, n_frames // 150)
    slider_steps = [
        {
            "args": [[str(i)], {
                "frame": {"duration": 0, "redraw": True},
                "mode": "immediate", "transition": {"duration": 0},
            }],
            "label": str(int(df.iloc[i]["Frame"])),
            "method": "animate",
        }
        for i in range(0, n_frames, step_every)
    ]

    fig = go.Figure(data=static + make_zone_frame(0), frames=frames)

    btn_common = {"fromcurrent": True, "transition": {"duration": 0}}
    fig.update_layout(
        plot_bgcolor=COLOR_PITCH,
        paper_bgcolor=COLOR_BG,
        xaxis=dict(range=[-4, PITCH_W + 4], showgrid=False, zeroline=False,
                   color="white", title="", fixedrange=True),
        yaxis=dict(range=[-4, PITCH_H + 4], showgrid=False, zeroline=False,
                   scaleanchor="x", scaleratio=1,
                   color="white", title="", fixedrange=True),
        margin=dict(l=5, r=50, t=10, b=100),
        height=590,
        dragmode=False,
        showlegend=False,
        updatemenus=[{
            "type": "buttons",
            "showactive": True,
            "bgcolor": "#1e2a1e",
            "bordercolor": "rgba(255,255,255,0.20)",
            "font": {"color": "white", "size": 13},
            "x": 0.0, "y": -0.13,
            "xanchor": "left", "yanchor": "top",
            "direction": "left",
            "buttons": [
                {"label": "▶ ×1", "method": "animate",
                 "args": [None, {"frame": {"duration": int(1000 / fps), "redraw": True},
                                 **btn_common}]},
                {"label": "⏸", "method": "animate",
                 "args": [[None], {"frame": {"duration": 0, "redraw": False},
                                   "mode": "immediate", "transition": {"duration": 0}}]},
                {"label": "×0.5", "method": "animate",
                 "args": [None, {"frame": {"duration": int(2000 / fps), "redraw": True},
                                 **btn_common}]},
                {"label": "×2", "method": "animate",
                 "args": [None, {"frame": {"duration": int(500 / fps), "redraw": True},
                                 **btn_common}]},
                {"label": "×4", "method": "animate",
                 "args": [None, {"frame": {"duration": int(250 / fps), "redraw": True},
                                 **btn_common}]},
                {"label": "⏮", "method": "animate",
                 "args": [["0"], {"frame": {"duration": 0, "redraw": True},
                                  "mode": "immediate", "transition": {"duration": 0}}]},
            ],
        }],
        sliders=[{
            "active": 0,
            "currentvalue": {
                "prefix": "Frame: ",
                "font": {"color": "white", "size": 11},
                "visible": True, "xanchor": "center",
            },
            "bgcolor": "#1e2a1e",
            "bordercolor": "rgba(255,255,255,0.20)",
            "font": {"color": "white", "size": 9},
            "tickcolor": "rgba(255,255,255,0.35)",
            "pad": {"t": 60, "b": 5},
            "len": 1.0, "x": 0, "y": 0,
            "steps": slider_steps,
        }],
    )
    return fig


# ── xT timeline ───────────────────────────────────────────────────────────────

def build_timeline_fig(
    df: pd.DataFrame,
    sel_home: list[int],
    sel_away: list[int],
    h_nums: list[int],
    a_nums: list[int],
) -> go.Figure:
    fig   = go.Figure()
    times = df["Time"].values

    # ── team aggregate: max xT per frame ─────────────────────────────────────
    home_xt_cols = [f"Home_P{n}_xT" for n in h_nums if f"Home_P{n}_xT" in df.columns]
    away_xt_cols = [f"Away_P{n}_xT" for n in a_nums if f"Away_P{n}_xT" in df.columns]

    if home_xt_cols:
        home_max_xt = df[home_xt_cols].max(axis=1).values
        fig.add_trace(go.Scatter(
            x=times, y=home_max_xt, mode="lines",
            line=dict(color=COLOR_HOME, width=2.5),
            name="Home MAX xT",
            fill="tozeroy",
            fillcolor="rgba(59,158,255,0.10)",
            hovertemplate="Home MAX xT  t=%{x:.2f}s  xT=%{y:.4f}<extra></extra>",
        ))

    if away_xt_cols:
        away_max_xt = df[away_xt_cols].max(axis=1).values
        fig.add_trace(go.Scatter(
            x=times, y=away_max_xt, mode="lines",
            line=dict(color=COLOR_AWAY, width=2.5),
            name="Away MAX xT",
            fill="tozeroy",
            fillcolor="rgba(255,85,85,0.10)",
            hovertemplate="Away MAX xT  t=%{x:.2f}s  xT=%{y:.4f}<extra></extra>",
        ))

    # ── individual player traces (optional, thinner) ──────────────────────────
    for n in sel_home:
        col = f"Home_P{n}_xT"
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=times, y=df[col].values, mode="lines",
                line=dict(color=COLOR_HOME, width=1, dash="dot"),
                name=f"H{n}", opacity=0.55,
                hovertemplate=f"H{{n}} t=%{{x:.2f}}s xT=%{{y:.4f}}<extra></extra>".replace("{n}", str(n)),
            ))

    for n in sel_away:
        col = f"Away_P{n}_xT"
        if col in df.columns:
            fig.add_trace(go.Scatter(
                x=times, y=df[col].values, mode="lines",
                line=dict(color=COLOR_AWAY, width=1, dash="dot"),
                name=f"A{n}", opacity=0.55,
                hovertemplate=f"A{{n}} t=%{{x:.2f}}s xT=%{{y:.4f}}<extra></extra>".replace("{n}", str(n)),
            ))

    # ── Ball xT (yellow, possession-aware) ────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=times, y=df["Ball_xT"].values, mode="lines",
        line=dict(color=COLOR_BALL, width=2, dash="dash"),
        name="Ball xT",
        hovertemplate="Ball xT  t=%{x:.2f}s  xT=%{y:.4f}<extra></extra>",
    ))

    # ── goal line ─────────────────────────────────────────────────────────────
    all_max = max(
        float(df["Ball_xT"].max()),
        float(home_max_xt.max()) if home_xt_cols else 0,
        float(away_max_xt.max()) if away_xt_cols else 0,
    )
    fig.add_vline(x=float(times[-1]),
                  line=dict(color="rgba(255,215,0,0.65)", width=2, dash="dot"))
    fig.add_annotation(
        x=float(times[-1]), y=all_max,
        text="GOAL", showarrow=False,
        font=dict(color="#ffd700", size=11, family="Arial Black"),
        xanchor="right", yshift=10,
    )

    n_sec = float(times[-1]) if len(times) else 30
    fig.update_layout(
        title=dict(
            text=(
                "<b style='color:#3b9eff'>Home MAX xT</b>"
                "  vs  "
                "<b style='color:#ff5555'>Away MAX xT</b>"
                "  |  "
                "<span style='color:#FFD700'>Ball xT</span>"
            ),
            font=dict(color="white", size=12),
        ),
        plot_bgcolor="#0e1825", paper_bgcolor="#0e1825",
        xaxis=dict(
            title="Time (sec)", color="#b0c8e0",
            range=[0, n_sec],
            showgrid=True, gridcolor="rgba(255,255,255,0.07)", zeroline=False,
        ),
        yaxis=dict(
            title="xT", color="#b0c8e0",
            showgrid=True, gridcolor="rgba(255,255,255,0.07)", zeroline=False,
            rangemode="tozero",
        ),
        legend=dict(
            font=dict(color="white", size=9), bgcolor="rgba(0,0,0,0.4)",
            orientation="h", x=0, y=-0.30,
        ),
        margin=dict(l=10, r=10, t=40, b=75),
        height=310,
    )
    return fig


# ── contribution score panel (22-player) ──────────────────────────────────────

def render_contribution_panel(
    causal_df: pd.DataFrame | None,
    h_nums: list[int],
    a_nums: list[int],
    show: bool,
) -> None:
    """
    Contribution scores from external causal analysis system (GSA).

    Expected CSV columns:
        Frame,
        Home_P1_contribution … Home_P11_contribution,
        Away_P1_contribution … Away_P11_contribution
    """
    def _get(row, key):
        v = row.get(key)
        return float(v) if v is not None and not pd.isna(v) else None

    with st.expander("⚡ 因果貢献度スコア — 22名（外部システム連携）", expanded=show):
        if causal_df is None:
            st.info(
                "貢献度スコアはまだ読み込まれていません。\n\n"
                "外部因果解析システム（GSA等）の出力CSVをサイドバーの\n"
                "「貢献度CSVパス」に指定してください。\n\n"
                "期待するカラム:\n"
                "`Home_P1_contribution` … `Home_P11_contribution`\n"
                "`Away_P1_contribution` … `Away_P11_contribution`"
            )
            st.markdown("**🔵 Home Team**")
            cols = st.columns(6)
            for i, n in enumerate(h_nums):
                cols[i % 6].metric(f"H{n}", "—", help="GSA未連携")
            st.markdown("**🔴 Away Team**")
            cols = st.columns(6)
            for i, n in enumerate(a_nums):
                cols[i % 6].metric(f"A{n}", "—", help="GSA未連携")
        else:
            row = causal_df.iloc[-1]

            st.markdown("**🔵 Home Team**")
            h_scores = {n: _get(row, f"Home_P{n}_contribution") for n in h_nums}
            h_ranked = sorted(h_nums, key=lambda n: h_scores[n] or -999, reverse=True)
            cols = st.columns(6)
            for i, n in enumerate(h_ranked):
                s = h_scores[n]
                cols[i % 6].metric(f"H{n}",
                                   f"+{s:.3f}" if s is not None else "—",
                                   f"rank {i+1}" if s is not None else None)

            st.markdown("**🔴 Away Team**")
            a_scores = {n: _get(row, f"Away_P{n}_contribution") for n in a_nums}
            a_ranked = sorted(a_nums, key=lambda n: a_scores[n] or -999, reverse=True)
            cols = st.columns(6)
            for i, n in enumerate(a_ranked):
                s = a_scores[n]
                cols[i % 6].metric(f"A{n}",
                                   f"+{s:.3f}" if s is not None else "—",
                                   f"rank {i+1}" if s is not None else None)


# ── LBP alert panel (zone mode only) ─────────────────────────────────────────

def render_lbp_alerts(df: pd.DataFrame) -> None:
    """Render line-breaking pass detection results for zone mode."""
    if "is_line_breaking_pass" not in df.columns or df["is_line_breaking_pass"].sum() == 0:
        st.info("このシーンにラインブレイクパスは検出されませんでした。")
        return

    lbp_df = df[df["is_line_breaking_pass"] == 1]

    # Group consecutive flagged frames into distinct events (gap > 5 = new event)
    events, prev_f = [], -999
    for _, row in lbp_df.iterrows():
        f = int(row["Frame"])
        if f > prev_f + 5:
            events.append(row)
        prev_f = f

    for ev in events:
        t      = float(ev.get("Time", 0))
        passer = str(ev.get("lbp_passer", ""))
        recv   = str(ev.get("lbp_receiver", ""))
        defs   = int(ev.get("lbp_nearby_def_count", 0))
        st.warning(
            f"**【Zone 2→3】アタッキングサードへの縦パスを検知**  \n"
            f"出し手: `{passer}` → 受け手: `{recv}`  \n"
            f"周囲 3m 以内の相手DF: **{defs}名** | 発生時刻: **{t:.2f}s**  \n"
            f"中盤の配給価値が上昇中 — GSA 因果スコアに反映されます"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:

    # ── sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## ⚽ Pitch Log")
        st.markdown("**Phase 4 Extended: 22-Player Visualization**")
        st.divider()

        # ── 解析モード ────────────────────────────────────────────────────
        view_mode = st.radio(
            "解析モード",
            ["通常モード（全体xT一律評価）", "ゾーン別評価モード（縦パス特化）"],
            index=0,
            help=(
                "ゾーン別：ピッチをセーフ/ビルド/アタッキングサードに分割し、\n"
                "ラインブレイクパス（縦パス）を自動検出して強調表示します。"
            ),
        )
        zone_mode = view_mode.startswith("ゾーン")
        st.divider()

        # ── セットアップ手順 ───────────────────────────────────────────────
        with st.expander("📋 セットアップ手順", expanded=False):
            st.markdown("""
**すべて同じフォルダに置く**

---

**Step 1 — サンプルデータ生成**
```
python generate_sample_tracking_22.py
```
→ `Sample_TrackingData_22.csv` が生成される

---

**Step 2 — GridID・xT付与 & CSV出力**
```
python xt_pipeline_22.py
```
- 必要: `xT_BaseMap_105x68.csv`
- 必要: `Sample_TrackingData_22.csv`

→ `Export_GSA_22players_30s.csv` が生成される

---

**Step 3 — ダッシュボード起動（今ここ）**
```
streamlit run app_22.py
```
- 必要: `xT_BaseMap_105x68.csv`
- 必要: `Export_GSA_22players_30s.csv`

---

**Step 4 — GSA連携（将来・任意）**

`causal_scores_22.csv` を置くだけで\n貢献度スコアが自動表示される

カラム例:
`Frame,`
`Home_P1_contribution, ...,`
`Away_P11_contribution`

---

**実データを使う場合**

`Sample_TrackingData_22.csv` を実トラッキングデータに差し替える。
カラム形式:
`frame, time_sec, ball_x, ball_y,`
`is_goal_frame,`
`Home_1_x, Home_1_y, ...,`
`Away_11_x, Away_11_y`
（座標は 0〜1 に正規化）
""")

        st.divider()
        st.markdown("### データファイル")
        xt_path     = st.text_input("xTベースマップ CSV",  "xT_BaseMap_105x68.csv")
        scene_path  = st.text_input("シーン CSV",
                                    "Export_GSA_22players_30s.csv")
        causal_path = st.text_input("貢献度 CSV（任意）",  "causal_scores_22.csv",
                                    help=(
                                        "外部因果解析システム（GSA等）の出力。\n"
                                        "Home_P1_contribution … Away_P11_contribution"
                                    ))
        st.divider()

        st.markdown("### 表示オプション")
        show_xt      = st.toggle("xTヒートマップ",   value=True)
        show_causal  = st.toggle("貢献度パネル",     value=True)
        trail_frames = st.slider("軌跡フレーム数", 0, 100, 20, step=5)
        st.divider()

        st.markdown("### xTグラフ — 個別選手（任意）")
        st.caption("チーム最大xTは常時表示。追加で見たい選手を選択。")
        st.markdown("**🔵 Home（個別追加）**")
        home_sel_ph = st.empty()
        st.markdown("**🔴 Away（個別追加）**")
        away_sel_ph = st.empty()
        st.divider()

        st.markdown(
            "**凡例**\n\n"
            "🔵 Home（青）\n"
            "🔴 Away（赤）\n"
            "🟡 ボール（黄）\n\n"
            "**再生操作**\n\n"
            "▶ ×1 / ×0.5 / ×2 / ×4 : 速度\n"
            "⏸ : 一時停止\n"
            "⏮ : 先頭へ\n"
            "スライダー : コマ送り\n\n"
            "ホバーで GridID・xT 表示"
        )

    # ── load ──────────────────────────────────────────────────────────────────
    _scene_mtime = Path(scene_path).stat().st_mtime if Path(scene_path).exists() else 0.0
    df        = load_scene(scene_path, _scene_mtime)
    causal_df = load_causal(causal_path)
    h_nums    = home_nums(df)
    a_nums    = away_nums(df)
    n_frames  = len(df)
    fps       = detect_fps(df)

    with home_sel_ph:
        sel_home = st.multiselect("Home", options=h_nums, default=[],
                                  format_func=lambda n: f"H{n}",
                                  label_visibility="collapsed")
    with away_sel_ph:
        sel_away = st.multiselect("Away", options=a_nums, default=[],
                                  format_func=lambda n: f"A{n}",
                                  label_visibility="collapsed")

    # ── GSA export section (sidebar, after data is loaded) ────────────────────
    with st.sidebar:
        st.divider()
        st.markdown("### 📤 GSAエクスポート")

        if n_frames > 1:
            frame_range = st.slider(
                "エクスポート範囲 (Frame)",
                min_value=1, max_value=n_frames,
                value=(1, n_frames), step=1,
                help="GSAに渡すフレーム範囲を選択。全体または特定シーンを切り出せます。",
            )
        else:
            frame_range = (1, n_frames)

        f_start, f_end   = frame_range
        n_export         = f_end - f_start + 1
        duration_sec     = n_export / fps

        st.caption(
            f"選択: **{n_export}** フレーム / **{duration_sec:.1f}** 秒  "
            f"（{fps:.0f} fps）"
        )

        export_df = df.iloc[f_start - 1 : f_end].copy().reset_index(drop=True)
        export_df["Frame"] = range(1, len(export_df) + 1)
        if "Time" in export_df.columns:
            export_df["Time"] = (export_df["Frame"] / fps).round(5)

        csv_bytes = export_df.to_csv(index=False).encode("utf-8")
        fname = (
            f"GSA_export"
            f"_F{f_start:04d}-{f_end:04d}"
            f"_{n_export}frames"
            f"_{duration_sec:.0f}s.csv"
        )

        st.download_button(
            label="📥 CSVをダウンロード",
            data=csv_bytes,
            file_name=fname,
            mime="text/csv",
            use_container_width=True,
            help=f"保存ファイル名: {fname}",
        )

    # ── header ────────────────────────────────────────────────────────────────
    st.markdown(
        "<h2 style='margin-bottom:0'>⚽ Pitch Log — 22-Player Goal Scene Viewer</h2>"
        "<p style='color:#8b949e;margin-top:2px;font-size:.85rem'>"
        "Phase 4 Extended | Home 11 + Away 11 + Ball | xT × Causal Analysis</p>",
        unsafe_allow_html=True,
    )

    # ── metrics ───────────────────────────────────────────────────────────────
    peak_xt = float(df["Ball_xT"].max()) if "Ball_xT" in df.columns else 0.0
    mc = st.columns(5)
    mc[0].metric("総フレーム数",   f"{n_frames}")
    mc[1].metric("シーン長",       f"{n_frames / fps:.1f} 秒")
    mc[2].metric("Peak Ball xT",  f"{peak_xt:.4f}")
    mc[3].metric("Home 選手数",    f"{len(h_nums)}")
    mc[4].metric("Away 選手数",    f"{len(a_nums)}")

    st.divider()

    # ── two-panel layout ──────────────────────────────────────────────────────
    col_l, col_r = st.columns([11, 9], gap="medium")

    with col_l:
        if zone_mode:
            st.markdown("#### ゾーン別ピッチビュー  🟢 LBP検知  🔵 Home  🔴 Away")
            st.caption(
                "Zone1: セーフ (X<33%) | Zone2: ビルド (33-66%) | "
                "Zone3: アタッキングサード (X>66%) | 緑矢印: ラインブレイクパス"
            )
            fig_pitch = build_zone_animated_fig(xt_path, scene_path, show_xt, trail_frames, fps)
        else:
            st.markdown("#### ピッチビュー  🔵 Home  🔴 Away  🟡 Ball")
            st.caption("▶/⏸/×0.5/×2/×4/⏮ で操作 | スライダーでコマ送り | ホバーで詳細表示")
            fig_pitch = build_animated_fig(xt_path, scene_path, show_xt, trail_frames, fps)
        st.plotly_chart(fig_pitch, use_container_width=True,
                        config={"displayModeBar": False})

    with col_r:
        if zone_mode:
            st.markdown("#### ラインブレイクパス検知アラート")
            lbp_df = _compute_lbp_inapp(df, fps, h_nums, a_nums)
            render_lbp_alerts(lbp_df)
            st.divider()

        st.markdown("#### xT タイムライン（30秒全体）")
        fig_line = build_timeline_fig(df, sel_home, sel_away, h_nums, a_nums)
        st.plotly_chart(fig_line, use_container_width=True,
                        config={"displayModeBar": False})

        render_contribution_panel(causal_df, h_nums, a_nums, show_causal)

    # ── frame data table ──────────────────────────────────────────────────────
    with st.expander("フレームデータ詳細（先頭フレーム）", expanded=False):
        row = df.iloc[0]
        rows_data = []

        rows_data.append({
            "チーム": "—", "選手": "Ball",
            "X": f"{row['Ball_X']:.5f}", "Y": f"{row['Ball_Y']:.5f}",
            "GridID": row["Ball_GridID"], "xT": f"{row['Ball_xT']:.5f}",
        })
        for n in h_nums:
            rows_data.append({
                "チーム": "Home", "選手": f"P{n}",
                "X":      f"{row.get(f'Home_P{n}_X', np.nan):.5f}",
                "Y":      f"{row.get(f'Home_P{n}_Y', np.nan):.5f}",
                "GridID": row.get(f"Home_P{n}_GridID", pd.NA),
                "xT":     f"{row.get(f'Home_P{n}_xT', np.nan):.5f}",
            })
        for n in a_nums:
            rows_data.append({
                "チーム": "Away", "選手": f"P{n}",
                "X":      f"{row.get(f'Away_P{n}_X', np.nan):.5f}",
                "Y":      f"{row.get(f'Away_P{n}_Y', np.nan):.5f}",
                "GridID": row.get(f"Away_P{n}_GridID", pd.NA),
                "xT":     f"{row.get(f'Away_P{n}_xT', np.nan):.5f}",
            })

        st.dataframe(pd.DataFrame(rows_data), use_container_width=True, hide_index=True)

    st.markdown(
        "<p style='text-align:center;color:#30363d;font-size:.7rem;margin-top:1rem'>"
        "Pitch Log | Phase 4 Extended | 22-Player xT × Causal Analysis Platform</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()

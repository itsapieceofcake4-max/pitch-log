"""
app_23.py
=========
Pitch Log v23 — 22-Player Scene Viewer + VAEP / Off-ball / Defensive Analysis

v23 additions over app_22
--------------------------
- VAEP analysis panel:  per-player attack VAEP + defensive VAEP horizontal bar chart
- Off-ball run panel:   xthreat from runs, line-break & run-behind counts
- Defensive breakdown:  stop_danger, reduce_danger, force_backward, beaten counts
- Sidebar inputs for dynamic_events CSV and contributions CSV
- In-app contributions computation via xt_pipeline_23

Run
---
  streamlit run app_23.py
"""

from __future__ import annotations

import io
import json
import re
from pathlib import Path

import importlib.util as _ilu
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# ── page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Pitch Log — v23",
    page_icon="⚽",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ── constants ─────────────────────────────────────────────────────────────────
PITCH_W = 105.0
PITCH_H = 68.0
X_BINS  = 105
Y_BINS  = 68

COLOR_HOME  = "#3b9eff"
COLOR_AWAY  = "#ff5555"
COLOR_BALL  = "#FFD700"
COLOR_BG    = "#0e1825"
COLOR_PITCH = "#1a3d1a"

ZONE_SAFE_MAX  = 0.33
ZONE_BUILD_MAX = 0.66


# ── Match metadata helpers ─────────────────────────────────────────────────────

def _fmt_mmss(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def load_match_info(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
.stApp, body {
    background-color: #0e1825 !important;
    color: #dde8f4 !important;
}
.main .block-container { padding-top: 1.2rem; }
h1, h2, h3, h4 { color: #ffffff !important; font-weight: 700; }

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

.stCaption p, [data-testid="stCaptionContainer"] p {
    color: #7095b5 !important; font-size: 0.82rem !important;
}

div[data-testid="stInfo"] {
    background: #0f2540 !important;
    border-left: 4px solid #2e6fa8 !important;
}
div[data-testid="stInfo"] p { color: #93bfe0 !important; }

.stTextInput input {
    background: #091422 !important; color: #dde8f4 !important;
    border: 1px solid #234060 !important; border-radius: 6px !important;
}
.stTextInput label { color: #7aaac8 !important; font-weight: 600 !important; }

.stSlider label { color: #9abcda !important; }
.stToggle label, .stToggle p { color: #b8d4ec !important; }
.stMultiSelect label { color: #7aaac8 !important; font-weight: 600 !important; }
hr { border-color: #1e3348 !important; margin: 0.7rem 0 !important; }
.stDataFrame { border: 1px solid #234060; border-radius: 8px; overflow: hidden; }
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


@st.cache_data(show_spinner="v23 貢献度読み込み中…")
def load_contributions(path: str, _mtime: float = 0.0) -> pd.DataFrame | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        df = pd.read_csv(p)
        for col in ["vaep_attack", "vaep_defend", "off_ball_xthreat", "vaep_total",
                    "xshot_gain", "xloss_gain"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
        return df
    except Exception:
        return None


def detect_fps(df: pd.DataFrame) -> float:
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

def _dm(x1, y1, x2, y2) -> float:
    return float(np.sqrt(((x1 - x2) * 105.0) ** 2 + ((y1 - y2) * 68.0) ** 2))

def _eff_x(x_norm, team) -> float:
    return (1.0 - x_norm) if team == "Away" else x_norm


def _compute_lbp_inapp(df, fps, h_nums, a_nums) -> pd.DataFrame:
    if "is_line_breaking_pass" in df.columns:
        return df

    _CTRL_M, _TRAV_M, _DEF_M, _LOOK = 2.0, 8.0, 3.0, 30
    n = len(df)
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
            i += 1; continue
        pt, pn = _holder(row, bx, by)
        if pt is None:
            i += 1; continue
        px_n   = float(row.get(f"{pt}_P{pn}_X", np.nan))
        eff_px = _eff_x(px_n, pt)
        if not (ZONE_SAFE_MAX <= eff_px < ZONE_BUILD_MAX):
            i += 1; continue

        found = False
        for k in range(1, min(_LOOK + 1, n - i)):
            fr  = df.iloc[i + k]
            fbx = float(fr.get("Ball_X", np.nan))
            fby = float(fr.get("Ball_Y", np.nan))
            if np.isnan(fbx) or np.isnan(fby): continue
            if _dm(bx, by, fbx, fby) < _TRAV_M: continue
            rt, rn = _holder(fr, fbx, fby)
            if rt is None or rt != pt or rn == pn: continue
            rx_n   = float(fr.get(f"{rt}_P{rn}_X", np.nan))
            eff_rx = _eff_x(rx_n, rt)
            if eff_rx < ZONE_BUILD_MAX: continue

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
                is_lbp[j] = 1; passers[j] = pid; recvs[j] = rid; defs_ct[j] = nb
            found = True; i += k + 1; break

        if not found:
            i += 1

    out = df.copy()
    out["is_line_breaking_pass"] = is_lbp
    out["lbp_passer"]            = passers
    out["lbp_receiver"]          = recvs
    out["lbp_nearby_def_count"]  = defs_ct
    return out


# ── Wizard helpers ─────────────────────────────────────────────────────────────

def _parse_mmss(s: str) -> float | None:
    s = s.strip()
    if not s:
        return None
    if ":" in s:
        parts = s.split(":", 1)
        try:
            return float(parts[0]) * 60 + float(parts[1])
        except Exception:
            return None
    try:
        return float(s)
    except Exception:
        return None


def _tick_mmss(sec: float) -> str:
    sec = max(0.0, float(sec))
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


def _mini_pitch_fig(row, h_nums, a_nums, schema="raw"):
    fig = go.Figure()
    for tr in _pitch_traces():
        fig.add_trace(tr)

    def _col(raw_name, proc_name):
        v = row.get(raw_name if schema == "raw" else proc_name, np.nan)
        return float(v) if pd.notna(v) else np.nan

    bx = _col("ball_x", "Ball_X")
    by = _col("ball_y", "Ball_Y")
    if not np.isnan(bx):
        fig.add_trace(go.Scatter(
            x=[bx * PITCH_W], y=[by * PITCH_H], mode="markers",
            marker=dict(size=13, color="rgba(255,215,0,0.8)",
                        line=dict(color="white", width=1.5)),
            showlegend=False, hoverinfo="skip",
        ))

    hxs = [_col(f"Home_{n}_x", f"Home_P{n}_X") for n in h_nums]
    hys = [_col(f"Home_{n}_y", f"Home_P{n}_Y") for n in h_nums]
    fig.add_trace(go.Scatter(
        x=[v * PITCH_W if not np.isnan(v) else None for v in hxs],
        y=[v * PITCH_H if not np.isnan(v) else None for v in hys],
        mode="markers+text",
        marker=dict(size=17, color=COLOR_HOME, line=dict(color="white", width=1.3)),
        text=[str(n) for n in h_nums],
        textfont=dict(color="white", size=8, family="Arial Black"),
        textposition="middle center",
        showlegend=False, hoverinfo="skip",
    ))

    axs = [_col(f"Away_{n}_x", f"Away_P{n}_X") for n in a_nums]
    ays = [_col(f"Away_{n}_y", f"Away_P{n}_Y") for n in a_nums]
    fig.add_trace(go.Scatter(
        x=[v * PITCH_W if not np.isnan(v) else None for v in axs],
        y=[v * PITCH_H if not np.isnan(v) else None for v in ays],
        mode="markers+text",
        marker=dict(size=17, color=COLOR_AWAY, line=dict(color="white", width=1.3)),
        text=[str(n) for n in a_nums],
        textfont=dict(color="white", size=8, family="Arial Black"),
        textposition="middle center",
        showlegend=False, hoverinfo="skip",
    ))

    fig.update_layout(
        plot_bgcolor=COLOR_PITCH, paper_bgcolor=COLOR_BG,
        xaxis=dict(range=[-4, PITCH_W + 4], showgrid=False, zeroline=False,
                   fixedrange=True, visible=False),
        yaxis=dict(range=[-4, PITCH_H + 4], showgrid=False, zeroline=False,
                   scaleanchor="x", scaleratio=1, fixedrange=True, visible=False),
        margin=dict(l=2, r=2, t=2, b=2),
        height=240, showlegend=False, dragmode=False,
    )
    return fig


def _wizard_steps(current: int) -> None:
    labels = ["① データ読み込み", "② シーン特定", "③ シーン情報", "④ 変換・保存"]
    cols   = st.columns(4)
    for i, (col, label) in enumerate(zip(cols, labels), start=1):
        done   = i < current
        active = i == current
        color  = "#5ec4ff" if active else ("#4ade80" if done else "#4a5568")
        border = f"2px solid {color}"
        weight = "700" if active else "500"
        col.markdown(
            f"<div style='text-align:center;padding:8px 4px;border-radius:8px;"
            f"border:{border};color:{color};font-weight:{weight};font-size:.82rem'>"
            f"{'✓ ' if done else ''}{label}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("<br>", unsafe_allow_html=True)


def render_import_wizard(xt_path: str, scene_path: str, match_info_path: str) -> None:
    ss   = st.session_state
    step = ss.get("import_step", 1)
    _wizard_steps(step)

    # STEP 1
    if step == 1:
        st.markdown("### データ読み込み")
        st.caption("試合全体のトラッキングCSVを読み込みます。30秒への切り出しは次のステップで行います。")

        with st.expander("📡 トラッキングデータの取得先", expanded=False):
            st.markdown("""
#### 🏆 SkillCorner
| リンク | 内容 |
|---|---|
| [SkillCorner 公式サイト](https://www.skillcorner.com/) | サービス概要 |
| [SkillCorner Client Portal](https://platform.skillcorner.com/) | データダウンロード（要ログイン） |
| [SkillCorner Open Data (GitHub)](https://github.com/SkillCorner/opendata) | 無償サンプルデータ |

#### 📋 このアプリが期待するCSV形式
```
frame, time_sec, ball_x, ball_y, is_goal_frame,
Home_1_x, Home_1_y, ..., Home_11_x, Home_11_y,
Away_1_x, Away_1_y, ..., Away_11_x, Away_11_y
```
- 座標は **0〜1 正規化**  |  Home は `x=1` 方向に攻撃
""")

        st.divider()
        _src = st.radio("データソース", ["💾 ファイルアップロード", "🌐 URL指定"],
                        horizontal=True, key="wiz_src")
        _raw_bytes = None; _fname = ""

        if _src == "💾 ファイルアップロード":
            _up = st.file_uploader("トラッキングCSV（試合全体）", type=["csv"], key="wiz_upload")
            if _up:
                _raw_bytes = _up.getvalue(); _fname = _up.name
                ss.pop("wiz_raw_bytes", None)
        else:
            _url = st.text_input("CSV の URL", placeholder="https://example.com/match_tracking.csv", key="wiz_url")
            if st.button("⬇️ ダウンロード", key="wiz_dl", use_container_width=True):
                if _url:
                    try:
                        import urllib.request as _ur
                        with st.spinner("ダウンロード中…"):
                            req = _ur.Request(_url, headers={"User-Agent": "PitchLog/1.0"})
                            with _ur.urlopen(req, timeout=60) as r:
                                _dl = r.read()
                        ss["wiz_raw_bytes"] = _dl
                        st.success(f"完了 ({len(_dl)//1024} KB)")
                    except Exception as e:
                        st.error(f"エラー: {e}")
            if "wiz_raw_bytes" in ss:
                _raw_bytes = ss["wiz_raw_bytes"]
                st.caption(f"✅ ダウンロード済 ({len(_raw_bytes)//1024} KB)")

        if _raw_bytes and st.button("次へ →", type="primary", use_container_width=True, key="wiz_step1_next"):
            try:
                _df = pd.read_csv(io.BytesIO(_raw_bytes))
                _dt = pd.to_numeric(_df.get("time_sec", pd.Series([0.1])), errors="coerce").diff().dropna().median()
                _fps = int(round(1.0 / _dt)) if _dt > 0 else 10
                _dur = len(_df) / _fps
                h_raw = sorted([int(m.group(1)) for col in _df.columns
                                 if (m := re.match(r"^Home_(\d+)_x$", col)) and f"Home_{m.group(1)}_y" in _df.columns])
                a_raw = sorted([int(m.group(1)) for col in _df.columns
                                 if (m := re.match(r"^Away_(\d+)_x$", col)) and f"Away_{m.group(1)}_y" in _df.columns])
                ss.update({
                    "import_raw_df":    _df,
                    "import_raw_fps":   _fps,
                    "import_raw_dur":   _dur,
                    "import_h_nums":    h_raw,
                    "import_a_nums":    a_raw,
                    "import_step":      2,
                })
                st.rerun()
            except Exception as e:
                st.error(f"読み込みエラー: {e}")

    # STEP 2
    elif step == 2:
        _df   = ss.get("import_raw_df")
        _fps  = ss.get("import_raw_fps", 10)
        _dur  = ss.get("import_raw_dur", 0)
        h_raw = ss.get("import_h_nums", [])
        a_raw = ss.get("import_a_nums", [])

        st.markdown("### シーン特定")
        st.caption(f"検出: **{len(_df)} フレーム** / **{_dur:.0f} 秒** @ {_fps} fps  |  Home: {len(h_raw)}名  Away: {len(a_raw)}名")

        c_ball, c_prev = st.columns([2, 1])
        with c_ball:
            st.markdown("#### ボール軌跡（縦軸 = 正規化 X 座標）")
            if _df is not None and "ball_x" in _df.columns:
                t_arr = np.arange(len(_df)) / _fps
                bx_arr = pd.to_numeric(_df["ball_x"], errors="coerce").values
                fig_ball = go.Figure()
                fig_ball.add_trace(go.Scatter(x=t_arr, y=bx_arr, mode="lines",
                                              line=dict(color=COLOR_BALL, width=1.5),
                                              name="ball_x", hoverinfo="skip"))
                fig_ball.update_layout(
                    plot_bgcolor="#0e1825", paper_bgcolor="#0e1825",
                    xaxis=dict(title="時刻 (秒)", color="#b0c8e0", showgrid=True,
                               gridcolor="rgba(255,255,255,0.07)"),
                    yaxis=dict(title="ball_x", color="#b0c8e0",
                               showgrid=True, gridcolor="rgba(255,255,255,0.07)"),
                    height=220, margin=dict(l=5, r=5, t=10, b=40),
                    showlegend=False,
                )
                st.plotly_chart(fig_ball, use_container_width=True, config={"displayModeBar": False})

        with c_prev:
            st.markdown("#### ピッチプレビュー")
            _prev_frame = st.number_input("プレビューフレーム", 0, len(_df) - 1, 0, key="wiz_prev_frame")
            if _df is not None and h_raw:
                _pf = _mini_pitch_fig(_df.iloc[_prev_frame], h_raw, a_raw, schema="raw")
                st.plotly_chart(_pf, use_container_width=True, config={"displayModeBar": False})

        st.divider()
        st.markdown("#### 時間範囲を選択")
        _t_cols = st.columns(2)
        _ts_str = _t_cols[0].text_input("開始時刻 (M:SS)", "0:00", key="wiz_ts")
        _te_str = _t_cols[1].text_input("終了時刻 (M:SS)", _tick_mmss(_dur), key="wiz_te")
        _ts = _parse_mmss(_ts_str) or 0.0
        _te = _parse_mmss(_te_str) or _dur
        _fs = int(_ts * _fps)
        _fe = min(int(_te * _fps), len(_df) - 1)

        st.info(f"⏱ **{_tick_mmss(_ts)}** 〜 **{_tick_mmss(_te)}** → {_fe - _fs} フレーム @ {_fps} fps")

        n1, n2 = st.columns(2)
        if n1.button("← 戻る", use_container_width=True): ss["import_step"] = 1; st.rerun()
        if n2.button("次へ →", type="primary", use_container_width=True, key="wiz_step2_next"):
            ss.update({"import_frame_start": _fs, "import_frame_end": _fe,
                       "import_t_start": _ts, "import_t_end": _te, "import_step": 3})
            st.rerun()

    # STEP 3
    elif step == 3:
        _ts = ss.get("import_t_start", 0.0)
        _te = ss.get("import_t_end", 30.0)
        _fps = ss.get("import_raw_fps", 10)
        _fs  = ss.get("import_frame_start", 0)
        _fe  = ss.get("import_frame_end", 0)

        st.markdown("### シーン情報")
        st.info(f"⏱ **{_tick_mmss(_ts)}** 〜 **{_tick_mmss(_te)}**  "
                f"({_te - _ts:.1f}秒 / {_fe - _fs}フレーム @ {_fps} fps)")

        _stype  = st.selectbox("シーンタイプ", ["ゴールシーン", "ビルドアップ", "プレッシング", "セットプレー", "その他"], key="wiz_stype")
        _sname  = st.text_input("シーン名（任意）", placeholder="例: 先制ゴール", key="wiz_sname")
        _mname  = st.text_input("試合名", placeholder="Brisbane Roar 0-1 Perth Glory", key="wiz_mname")
        _mround = st.text_input("ラウンド", placeholder="Round 09 | A-League 2024-25", key="wiz_mround")

        n1, n2 = st.columns(2)
        if n1.button("← 戻る", use_container_width=True): ss["import_step"] = 2; st.rerun()
        if n2.button("次へ →", type="primary", use_container_width=True, key="wiz_step3_next"):
            ss.update({"import_scene_type": _stype, "import_scene_name": _sname,
                       "import_match_name": _mname, "import_match_round": _mround, "import_step": 4})
            st.rerun()

    # STEP 4
    elif step == 4:
        _raw_df = ss.get("import_raw_df")
        _fps    = ss.get("import_raw_fps", 10)
        _fs     = ss.get("import_frame_start", 0)
        _fe     = ss.get("import_frame_end", 0)
        _ts     = ss.get("import_t_start", 0.0)
        _te     = ss.get("import_t_end", 30.0)
        _stype  = ss.get("import_scene_type", "")
        _sname  = ss.get("import_scene_name", "")
        _mname  = ss.get("import_match_name", "Unknown Match")
        _mround = ss.get("import_match_round", "")

        st.markdown("### 変換・保存の確認")
        c1, c2 = st.columns(2)
        c1.markdown(f"**試合**  \n{_mname or '（未入力）'}  \n{_mround or ''}")
        c2.markdown(f"**シーン**  \n{_stype}  \n{_sname or '（名前なし）'}")
        st.info(f"⏱ **{_tick_mmss(_ts)}** 〜 **{_tick_mmss(_te)}**  "
                f"（{_te - _ts:.1f}秒 / {_fe - _fs}フレーム @ {_fps} fps）  \n"
                f"出力先: `{scene_path}`  /  `{match_info_path}`")

        n1, n2 = st.columns(2)
        if n1.button("← 戻る", use_container_width=True): ss["import_step"] = 3; st.rerun()
        if n2.button("🔄 変換して読み込む", type="primary", use_container_width=True):
            try:
                _pipe_path = None
                for _cand in [Path(__file__).parent / "xt_pipeline_22.py",
                               Path(scene_path).parent / "xt_pipeline_22.py"]:
                    if _cand.exists():
                        _pipe_path = _cand; break
                if _pipe_path is None:
                    st.error("xt_pipeline_22.py が見つかりません。"); st.stop()

                _spec = _ilu.spec_from_file_location("_pipe22", _pipe_path)
                _pipe = _ilu.module_from_spec(_spec)
                _spec.loader.exec_module(_pipe)

                with st.spinner("xT計算・LBP検出中…"):
                    _xt_arr = _pipe.load_xt_map(xt_path)
                    _enr    = _pipe.assign_grid_and_xt_22(_raw_df, _xt_arr)
                    _win    = _enr.iloc[_fs:_fe + 1].reset_index(drop=True)
                    _res    = _pipe.reformat_to_22player_schema(_win, _fps, _ts)
                    _res    = _pipe.add_zone_and_lbp_columns(_res, _fps)
                    _res.to_csv(scene_path, index=False)

                    _meta = {
                        "match_name":       _mname or "Unknown Match",
                        "match_round":      _mround,
                        "scene_type":       _stype,
                        "scene_name":       _sname,
                        "goal_time_sec":    round(_te, 3),
                        "window_start_sec": round(_ts, 3),
                        "window_end_sec":   round(_te, 3),
                        "window_sec":       round(_te - _ts, 1),
                        "window_frames":    len(_win),
                        "fps":              _fps,
                        "output_csv":       scene_path,
                    }
                    with open(match_info_path, "w", encoding="utf-8") as _mf:
                        json.dump(_meta, _mf, indent=2, ensure_ascii=False)

                st.success(f"✅ 変換完了！  {len(_win)} フレーム（{_te - _ts:.1f}秒）を保存しました。")
                for k in list(ss.keys()):
                    if k.startswith("import_") or k.startswith("wiz_"):
                        ss.pop(k, None)
                ss["import_mode"] = False
                st.rerun()

            except Exception as _e:
                import traceback as _tb
                st.error(f"変換エラー: {_e}")
                st.code(_tb.format_exc(), language="python")


# ── pitch drawing ──────────────────────────────────────────────────────────────

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


def _zone_boundary_traces() -> list:
    traces = []
    for x_norm in [ZONE_SAFE_MAX, ZONE_BUILD_MAX]:
        x_m = x_norm * PITCH_W
        traces.append(go.Scatter(
            x=[x_m, x_m], y=[0.0, PITCH_H], mode="lines",
            line=dict(color="rgba(255,255,255,0.38)", width=1.5, dash="dash"),
            showlegend=False, hoverinfo="skip",
        ))
    return traces


# ── animated figures ───────────────────────────────────────────────────────────

def _make_heatmap_traces(xt_map, xt_side):
    traces = []
    xc = np.arange(X_BINS) + 0.5
    yc = np.arange(Y_BINS) + 0.5
    xt_map_away = xt_map[:, ::-1]
    zmax = float(np.percentile(xt_map[xt_map > 0], 99)) if xt_map.max() > 0 else 1.0

    if xt_side in ("Home", "両方"):
        h_op = 0.65 if xt_side == "両方" else 1.0
        traces.append(go.Heatmap(
            z=xt_map.tolist(), x=xc.tolist(), y=yc.tolist(),
            colorscale=[
                [0.00, "rgba(0,20,60,0)"],
                [0.25, f"rgba(90,170,255,{0.18*h_op:.2f})"],
                [0.50, f"rgba(59,158,255,{0.38*h_op:.2f})"],
                [0.75, f"rgba(30,100,235,{0.58*h_op:.2f})"],
                [1.00, f"rgba(10,50,190,{0.82*h_op:.2f})"],
            ],
            zmin=0, zmax=zmax,
            showscale=(xt_side != "両方"),
            colorbar=dict(title=dict(text="xT (Home)", font=dict(color="white", size=11)),
                          thickness=10, len=0.55, tickfont=dict(color="white", size=9)),
            hoverinfo="skip",
        ))

    if xt_side in ("Away", "両方"):
        a_op = 0.65 if xt_side == "両方" else 1.0
        traces.append(go.Heatmap(
            z=xt_map_away.tolist(), x=xc.tolist(), y=yc.tolist(),
            colorscale=[
                [0.00, "rgba(60,0,0,0)"],
                [0.25, f"rgba(255,140,140,{0.18*a_op:.2f})"],
                [0.50, f"rgba(255,85,85,{0.38*a_op:.2f})"],
                [0.75, f"rgba(235,45,45,{0.58*a_op:.2f})"],
                [1.00, f"rgba(180,0,0,{0.82*a_op:.2f})"],
            ],
            zmin=0, zmax=zmax,
            showscale=True,
            colorbar=dict(title=dict(text="xT (Away)", font=dict(color="white", size=11)),
                          thickness=10, len=0.55, x=1.08, tickfont=dict(color="white", size=9)),
            hoverinfo="skip",
        ))
    return traces


def _make_layout(fps, n_frames, df):
    step_every = max(1, n_frames // 150)
    slider_steps = [
        {"args": [[str(i)], {"frame": {"duration": 0, "redraw": True},
                             "mode": "immediate", "transition": {"duration": 0}}],
         "label": str(int(df.iloc[i]["Frame"])), "method": "animate"}
        for i in range(0, n_frames, step_every)
    ]
    bc = {"fromcurrent": True, "transition": {"duration": 0}}
    return dict(
        plot_bgcolor=COLOR_PITCH, paper_bgcolor=COLOR_BG,
        xaxis=dict(range=[-4, PITCH_W + 4], showgrid=False, zeroline=False,
                   color="white", title="", fixedrange=True),
        yaxis=dict(range=[-4, PITCH_H + 4], showgrid=False, zeroline=False,
                   scaleanchor="x", scaleratio=1, color="white", title="", fixedrange=True),
        margin=dict(l=5, r=50, t=10, b=100),
        height=590, dragmode=False, showlegend=False,
        updatemenus=[{
            "type": "buttons", "showactive": False,
            "bgcolor": "#1e2a1e", "bordercolor": "rgba(255,255,255,0.20)",
            "font": {"color": "white", "size": 13},
            "x": 0.0, "y": -0.13, "xanchor": "left", "yanchor": "top", "direction": "right",
            "buttons": [
                {"label": "▶", "method": "animate",
                 "args": [None, {"frame": {"duration": int(1000/fps), "redraw": True}, **bc}]},
                {"label": "⏸", "method": "animate",
                 "args": [[None], {"frame": {"duration": 0, "redraw": False},
                                   "mode": "immediate", "transition": {"duration": 0}}]},
                {"label": "×0.5", "method": "animate",
                 "args": [None, {"frame": {"duration": int(2000/fps), "redraw": True}, **bc}]},
                {"label": "×1",   "method": "animate",
                 "args": [None, {"frame": {"duration": int(1000/fps), "redraw": True}, **bc}]},
                {"label": "×2",   "method": "animate",
                 "args": [None, {"frame": {"duration": int(500/fps),  "redraw": True}, **bc}]},
                {"label": "×4",   "method": "animate",
                 "args": [None, {"frame": {"duration": int(250/fps),  "redraw": True}, **bc}]},
                {"label": "⏮",   "method": "animate",
                 "args": [["0"], {"frame": {"duration": 0, "redraw": True},
                                  "mode": "immediate", "transition": {"duration": 0}}]},
            ],
        }],
        sliders=[{
            "active": 0,
            "currentvalue": {"prefix": "Frame: ", "font": {"color": "white", "size": 11},
                             "visible": True, "xanchor": "center"},
            "bgcolor": "#1e2a1e", "bordercolor": "rgba(255,255,255,0.20)",
            "font": {"color": "white", "size": 9},
            "tickcolor": "rgba(255,255,255,0.35)",
            "pad": {"t": 60, "b": 5}, "len": 1.0, "x": 0, "y": 0,
            "steps": slider_steps,
        }],
    )


@st.cache_data(show_spinner="アニメーション生成中…")
def build_animated_fig(
    xt_path, scene_path, show_xt, trail_frames,
    fps=25.0, show_home=True, show_away=True, xt_side="Home",
) -> go.Figure:
    xt_map   = load_xt_map(xt_path)
    df       = load_scene(scene_path)
    h_nums   = home_nums(df)
    a_nums   = away_nums(df)
    n_frames = len(df)

    static = []
    if show_xt:
        static.extend(_make_heatmap_traces(xt_map, xt_side))
    for tr in _pitch_traces():
        static.append(tr)

    n_static     = len(static)
    anim_indices = list(range(n_static, n_static + 6))

    def make_frame(idx):
        row = df.iloc[idx]
        t0  = max(0, idx - trail_frames)
        tdf = df.iloc[t0 : idx + 1]
        out = []

        out.append(go.Scatter(
            x=(tdf["Ball_X"].values * PITCH_W).tolist(),
            y=(tdf["Ball_Y"].values * PITCH_H).tolist(),
            mode="lines", line=dict(color="rgba(255,215,0,0.35)", width=1.5, dash="dot"),
            showlegend=False, hoverinfo="skip"))

        hx_t, hy_t = [], []
        for n in h_nums:
            hx_t.extend((tdf[f"Home_P{n}_X"].values * PITCH_W).tolist() + [None])
            hy_t.extend((tdf[f"Home_P{n}_Y"].values * PITCH_H).tolist() + [None])
        out.append(go.Scatter(x=hx_t, y=hy_t, mode="lines",
                              line=dict(color="rgba(30,144,255,0.22)", width=1),
                              showlegend=False, hoverinfo="skip"))

        ax_t, ay_t = [], []
        for n in a_nums:
            ax_t.extend((tdf[f"Away_P{n}_X"].values * PITCH_W).tolist() + [None])
            ay_t.extend((tdf[f"Away_P{n}_Y"].values * PITCH_H).tolist() + [None])
        out.append(go.Scatter(x=ax_t, y=ay_t, mode="lines",
                              line=dict(color="rgba(255,68,68,0.22)", width=1),
                              showlegend=False, hoverinfo="skip"))

        if show_home:
            hpx = [float(row.get(f"Home_P{n}_X", np.nan)) * PITCH_W for n in h_nums]
            hpy = [float(row.get(f"Home_P{n}_Y", np.nan)) * PITCH_H for n in h_nums]
            h_cd = [[n, int(row.get(f"Home_P{n}_GridID") or 0),
                     int(row.get(f"Home_P{n}_ZoneID") or 0),
                     float(row.get(f"Home_P{n}_xT") or 0.0)] for n in h_nums]
            out.append(go.Scatter(x=hpx, y=hpy, mode="markers+text",
                                  marker=dict(size=22, color=COLOR_HOME, line=dict(color="white", width=1.8)),
                                  text=[str(n) for n in h_nums],
                                  textfont=dict(color="white", size=10, family="Arial Black"),
                                  textposition="middle center",
                                  customdata=h_cd,
                                  hovertemplate="<b>Home P%{customdata[0]}</b><br>Zone : %{customdata[2]}<br>GridID : %{customdata[1]}<br>xT : %{customdata[3]:.4f}<extra></extra>",
                                  showlegend=False))
        else:
            out.append(go.Scatter(x=[], y=[], mode="markers", showlegend=False, hoverinfo="skip"))

        if show_away:
            apx = [float(row.get(f"Away_P{n}_X", np.nan)) * PITCH_W for n in a_nums]
            apy = [float(row.get(f"Away_P{n}_Y", np.nan)) * PITCH_H for n in a_nums]
            a_cd = [[n, int(row.get(f"Away_P{n}_GridID") or 0),
                     int(row.get(f"Away_P{n}_ZoneID") or 0),
                     float(row.get(f"Away_P{n}_xT") or 0.0)] for n in a_nums]
            out.append(go.Scatter(x=apx, y=apy, mode="markers+text",
                                  marker=dict(size=22, color=COLOR_AWAY, line=dict(color="white", width=1.8)),
                                  text=[str(n) for n in a_nums],
                                  textfont=dict(color="white", size=10, family="Arial Black"),
                                  textposition="middle center",
                                  customdata=a_cd,
                                  hovertemplate="<b>Away P%{customdata[0]}</b><br>Zone : %{customdata[2]}<br>GridID : %{customdata[1]}<br>xT : %{customdata[3]:.4f}<extra></extra>",
                                  showlegend=False))
        else:
            out.append(go.Scatter(x=[], y=[], mode="markers", showlegend=False, hoverinfo="skip"))

        bx  = row.get("Ball_X", np.nan)
        by  = row.get("Ball_Y", np.nan)
        bxt = float(row.get("Ball_xT", 0) or 0)
        bgd = int(row.get("Ball_GridID", 0) or 0)
        bzid = int(row.get("Ball_ZoneID", 0) or 0)
        out.append(go.Scatter(
            x=[float(bx) * PITCH_W] if pd.notna(bx) else [None],
            y=[float(by) * PITCH_H] if pd.notna(by) else [None],
            mode="markers",
            marker=dict(size=14, color="rgba(255,215,0,0.55)", line=dict(color="#aaa", width=1.5)),
            customdata=[[bxt, bgd, bzid]],
            hovertemplate="<b>Ball</b><br>Zone : %{customdata[2]}<br>GridID : %{customdata[1]}<br>xT : %{customdata[0]:.4f}<extra></extra>",
            showlegend=False))
        return out

    frames = [go.Frame(data=make_frame(i), name=str(i), traces=anim_indices) for i in range(n_frames)]
    fig = go.Figure(data=static + make_frame(0), frames=frames)
    fig.update_layout(**_make_layout(fps, n_frames, df))
    return fig


@st.cache_data(show_spinner="ゾーン別アニメーション生成中…")
def build_zone_animated_fig(
    xt_path, scene_path, show_xt, trail_frames,
    fps=25.0, show_home=True, show_away=True, xt_side="Home",
) -> go.Figure:
    xt_map   = load_xt_map(xt_path)
    df       = load_scene(scene_path)
    h_nums   = home_nums(df)
    a_nums   = away_nums(df)
    n_frames = len(df)
    df       = _compute_lbp_inapp(df, fps, h_nums, a_nums)

    lbp_flags   = df["is_line_breaking_pass"].values
    lbp_passers = df["lbp_passer"].values
    lbp_recvs   = df["lbp_receiver"].values

    static = []
    if show_xt:
        static.extend(_make_heatmap_traces(xt_map, xt_side))
    for tr in _pitch_traces():
        static.append(tr)
    for tr in _zone_boundary_traces():
        static.append(tr)

    n_static     = len(static)
    anim_indices = list(range(n_static, n_static + 9))

    def _player_pos_m(row, pid):
        if not pid:
            return None, None
        xv = row.get(f"{pid}_X", np.nan)
        yv = row.get(f"{pid}_Y", np.nan)
        if pd.isna(xv) or pd.isna(yv):
            return None, None
        return float(xv) * PITCH_W, float(yv) * PITCH_H

    def make_zone_frame(idx):
        row = df.iloc[idx]
        t0  = max(0, idx - trail_frames)
        tdf = df.iloc[t0 : idx + 1]
        out = []

        out.append(go.Scatter(x=(tdf["Ball_X"].values * PITCH_W).tolist(),
                              y=(tdf["Ball_Y"].values * PITCH_H).tolist(), mode="lines",
                              line=dict(color="rgba(255,215,0,0.35)", width=1.5, dash="dot"),
                              showlegend=False, hoverinfo="skip"))

        hx_t, hy_t = [], []
        for n in h_nums:
            hx_t.extend((tdf[f"Home_P{n}_X"].values * PITCH_W).tolist() + [None])
            hy_t.extend((tdf[f"Home_P{n}_Y"].values * PITCH_H).tolist() + [None])
        out.append(go.Scatter(x=hx_t, y=hy_t, mode="lines",
                              line=dict(color="rgba(30,144,255,0.22)", width=1),
                              showlegend=False, hoverinfo="skip"))

        ax_t, ay_t = [], []
        for n in a_nums:
            ax_t.extend((tdf[f"Away_P{n}_X"].values * PITCH_W).tolist() + [None])
            ay_t.extend((tdf[f"Away_P{n}_Y"].values * PITCH_H).tolist() + [None])
        out.append(go.Scatter(x=ax_t, y=ay_t, mode="lines",
                              line=dict(color="rgba(255,68,68,0.22)", width=1),
                              showlegend=False, hoverinfo="skip"))

        if show_home:
            hpx = [float(row.get(f"Home_P{n}_X", np.nan)) * PITCH_W for n in h_nums]
            hpy = [float(row.get(f"Home_P{n}_Y", np.nan)) * PITCH_H for n in h_nums]
            h_cd = [[n, int(row.get(f"Home_P{n}_GridID") or 0),
                     int(row.get(f"Home_P{n}_ZoneID") or 0),
                     float(row.get(f"Home_P{n}_xT") or 0.0)] for n in h_nums]
            out.append(go.Scatter(x=hpx, y=hpy, mode="markers+text",
                                  marker=dict(size=22, color=COLOR_HOME, line=dict(color="white", width=1.8)),
                                  text=[str(n) for n in h_nums],
                                  textfont=dict(color="white", size=10, family="Arial Black"),
                                  textposition="middle center", customdata=h_cd,
                                  hovertemplate="<b>Home P%{customdata[0]}</b><br>Zone : %{customdata[2]}<br>GridID : %{customdata[1]}<br>xT : %{customdata[3]:.4f}<extra></extra>",
                                  showlegend=False))
        else:
            out.append(go.Scatter(x=[], y=[], mode="markers", showlegend=False, hoverinfo="skip"))

        if show_away:
            apx = [float(row.get(f"Away_P{n}_X", np.nan)) * PITCH_W for n in a_nums]
            apy = [float(row.get(f"Away_P{n}_Y", np.nan)) * PITCH_H for n in a_nums]
            a_cd = [[n, int(row.get(f"Away_P{n}_GridID") or 0),
                     int(row.get(f"Away_P{n}_ZoneID") or 0),
                     float(row.get(f"Away_P{n}_xT") or 0.0)] for n in a_nums]
            out.append(go.Scatter(x=apx, y=apy, mode="markers+text",
                                  marker=dict(size=22, color=COLOR_AWAY, line=dict(color="white", width=1.8)),
                                  text=[str(n) for n in a_nums],
                                  textfont=dict(color="white", size=10, family="Arial Black"),
                                  textposition="middle center", customdata=a_cd,
                                  hovertemplate="<b>Away P%{customdata[0]}</b><br>Zone : %{customdata[2]}<br>GridID : %{customdata[1]}<br>xT : %{customdata[3]:.4f}<extra></extra>",
                                  showlegend=False))
        else:
            out.append(go.Scatter(x=[], y=[], mode="markers", showlegend=False, hoverinfo="skip"))

        bx  = row.get("Ball_X", np.nan)
        by  = row.get("Ball_Y", np.nan)
        bxt = float(row.get("Ball_xT", 0) or 0)
        bgd = int(row.get("Ball_GridID", 0) or 0)
        bzid = int(row.get("Ball_ZoneID", 0) or 0)
        out.append(go.Scatter(
            x=[float(bx) * PITCH_W] if pd.notna(bx) else [None],
            y=[float(by) * PITCH_H] if pd.notna(by) else [None],
            mode="markers",
            marker=dict(size=14, color="rgba(255,215,0,0.55)", line=dict(color="#aaa", width=1.5)),
            customdata=[[bxt, bgd, bzid]],
            hovertemplate="<b>Ball</b><br>Zone : %{customdata[2]}<br>GridID : %{customdata[1]}<br>xT : %{customdata[0]:.4f}<extra></extra>",
            showlegend=False))

        # LBP arrow + passer/receiver glow
        is_lbp = bool(lbp_flags[idx])
        if is_lbp:
            passer_id = lbp_passers[idx]
            recv_id   = lbp_recvs[idx]
            px_m, py_m = _player_pos_m(row, passer_id)
            rx_m, ry_m = _player_pos_m(row, recv_id)

            if px_m is not None and rx_m is not None:
                out.append(go.Scatter(x=[px_m, rx_m], y=[py_m, ry_m], mode="lines+markers",
                                      line=dict(color="rgba(0,255,120,0.85)", width=3),
                                      marker=dict(symbol="arrow", size=12, angleref="previous",
                                                  color="rgba(0,255,120,0.85)"),
                                      showlegend=False, hoverinfo="skip"))
            else:
                out.append(go.Scatter(x=[], y=[], mode="lines", showlegend=False, hoverinfo="skip"))

            if px_m is not None:
                out.append(go.Scatter(x=[px_m], y=[py_m], mode="markers",
                                      marker=dict(size=32, color="rgba(0,255,120,0.20)",
                                                  line=dict(color="rgba(0,255,120,0.70)", width=2)),
                                      showlegend=False, hoverinfo="skip"))
            else:
                out.append(go.Scatter(x=[], y=[], mode="markers", showlegend=False, hoverinfo="skip"))

            if rx_m is not None:
                out.append(go.Scatter(x=[rx_m], y=[ry_m], mode="markers",
                                      marker=dict(size=32, color="rgba(0,255,120,0.20)",
                                                  line=dict(color="rgba(0,255,120,0.70)", width=2)),
                                      showlegend=False, hoverinfo="skip"))
            else:
                out.append(go.Scatter(x=[], y=[], mode="markers", showlegend=False, hoverinfo="skip"))
        else:
            for _ in range(3):
                out.append(go.Scatter(x=[], y=[], mode="markers", showlegend=False, hoverinfo="skip"))

        return out

    frames = [go.Frame(data=make_zone_frame(i), name=str(i), traces=anim_indices) for i in range(n_frames)]
    fig = go.Figure(data=static + make_zone_frame(0), frames=frames)
    fig.update_layout(**_make_layout(fps, n_frames, df))
    return fig


# ── xT timeline ───────────────────────────────────────────────────────────────

def build_timeline_fig(df, sel_home, sel_away, h_nums, a_nums, time_offset=0.0):
    fig = go.Figure()

    if "Match_Time_sec" in df.columns and (time_offset != 0.0 or df["Match_Time_sec"].max() > 60):
        times   = (df["Match_Time_sec"] + time_offset).values
        x_label = "試合時刻 (秒)"
    else:
        times   = df["Time"].values
        x_label = "Time (sec)"

    home_xt_cols = [f"Home_P{n}_xT" for n in h_nums if f"Home_P{n}_xT" in df.columns]
    away_xt_cols = [f"Away_P{n}_xT" for n in a_nums if f"Away_P{n}_xT" in df.columns]
    home_max_xt  = df[home_xt_cols].max(axis=1).values if home_xt_cols else np.zeros(len(df))
    away_max_xt  = df[away_xt_cols].max(axis=1).values if away_xt_cols else np.zeros(len(df))

    if home_xt_cols:
        fig.add_trace(go.Scatter(x=times, y=home_max_xt, mode="lines",
                                 line=dict(color=COLOR_HOME, width=2.5), name="Home MAX xT",
                                 fill="tozeroy", fillcolor="rgba(59,158,255,0.10)",
                                 hovertemplate="Home MAX xT  t=%{x:.2f}s  xT=%{y:.4f}<extra></extra>"))
    if away_xt_cols:
        fig.add_trace(go.Scatter(x=times, y=away_max_xt, mode="lines",
                                 line=dict(color=COLOR_AWAY, width=2.5), name="Away MAX xT",
                                 fill="tozeroy", fillcolor="rgba(255,85,85,0.10)",
                                 hovertemplate="Away MAX xT  t=%{x:.2f}s  xT=%{y:.4f}<extra></extra>"))

    for n in sel_home:
        col = f"Home_P{n}_xT"
        if col in df.columns:
            fig.add_trace(go.Scatter(x=times, y=df[col].values, mode="lines",
                                     line=dict(color=COLOR_HOME, width=1, dash="dot"),
                                     name=f"H{n}", opacity=0.55))
    for n in sel_away:
        col = f"Away_P{n}_xT"
        if col in df.columns:
            fig.add_trace(go.Scatter(x=times, y=df[col].values, mode="lines",
                                     line=dict(color=COLOR_AWAY, width=1, dash="dot"),
                                     name=f"A{n}", opacity=0.55))

    fig.add_trace(go.Scatter(x=times, y=df["Ball_xT"].values, mode="lines",
                             line=dict(color=COLOR_BALL, width=2, dash="dash"),
                             name="Ball xT",
                             hovertemplate="Ball xT  t=%{x:.2f}s  xT=%{y:.4f}<extra></extra>"))

    all_max = max(float(df["Ball_xT"].max()), float(home_max_xt.max()), float(away_max_xt.max())) if len(times) else 1.0
    fig.add_vline(x=float(times[-1]), line=dict(color="rgba(255,215,0,0.65)", width=2, dash="dot"))
    fig.add_annotation(x=float(times[-1]), y=all_max, text="GOAL", showarrow=False,
                       font=dict(color="#ffd700", size=11, family="Arial Black"),
                       xanchor="right", yshift=10)

    fig.update_layout(
        title=dict(text=("<b style='color:#3b9eff'>Home MAX xT</b>  vs  "
                         "<b style='color:#ff5555'>Away MAX xT</b>  |  "
                         "<span style='color:#FFD700'>Ball xT</span>"),
                   font=dict(color="white", size=12)),
        plot_bgcolor="#0e1825", paper_bgcolor="#0e1825",
        xaxis=dict(title=x_label, color="#b0c8e0",
                   range=[float(times[0]) if len(times) else 0, float(times[-1]) if len(times) else 30],
                   showgrid=True, gridcolor="rgba(255,255,255,0.07)", zeroline=False),
        yaxis=dict(title="xT", color="#b0c8e0",
                   showgrid=True, gridcolor="rgba(255,255,255,0.07)", zeroline=False, rangemode="tozero"),
        legend=dict(font=dict(color="white", size=9), bgcolor="rgba(0,0,0,0.4)",
                    orientation="h", x=0, y=-0.30),
        margin=dict(l=10, r=10, t=40, b=75), height=310,
    )
    return fig


# ── GSA contribution panel (v22-style, kept for backward compatibility) ───────

def render_contribution_panel(causal_df, h_nums, a_nums, show):
    def _get(row, key):
        v = row.get(key); return float(v) if v is not None and not pd.isna(v) else None

    with st.expander("⚡ 因果貢献度スコア — 22名（外部システム連携）", expanded=show):
        if causal_df is None:
            st.info("貢献度スコアはまだ読み込まれていません。\n\n"
                    "サイドバーの「貢献度 CSV」に外部因果解析システムの出力CSVを指定してください。")
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
                cols[i % 6].metric(f"H{n}", f"+{s:.3f}" if s is not None else "—",
                                   f"rank {i+1}" if s is not None else None)
            st.markdown("**🔴 Away Team**")
            a_scores = {n: _get(row, f"Away_P{n}_contribution") for n in a_nums}
            a_ranked = sorted(a_nums, key=lambda n: a_scores[n] or -999, reverse=True)
            cols = st.columns(6)
            for i, n in enumerate(a_ranked):
                s = a_scores[n]
                cols[i % 6].metric(f"A{n}", f"+{s:.3f}" if s is not None else "—",
                                   f"rank {i+1}" if s is not None else None)


def render_lbp_alerts(df):
    if "is_line_breaking_pass" not in df.columns or df["is_line_breaking_pass"].sum() == 0:
        st.info("このシーンにラインブレイクパスは検出されませんでした。")
        return
    lbp_df = df[df["is_line_breaking_pass"] == 1]
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
        st.warning(f"**【Zone 2→3】ラインブレイクパスを検知**  \n"
                   f"出し手: `{passer}` → 受け手: `{recv}`  \n"
                   f"周囲 3m 以内の相手DF: **{defs}名** | 発生時刻: **{t:.2f}s**")


# ══════════════════════════════════════════════════════════════════════════════
# v23 VAEP / Off-ball / Defensive analysis panel
# ══════════════════════════════════════════════════════════════════════════════

def build_vaep_chart(contrib_df: pd.DataFrame, team_filter: str = "両チーム") -> go.Figure:
    """
    Horizontal bar chart: vaep_attack (blue) + vaep_defend (green) stacked per player.
    Sorted by vaep_total descending.
    """
    df = contrib_df.copy()
    if team_filter == "Home":
        df = df[df["team_label"] == "Home"]
    elif team_filter == "Away":
        df = df[df["team_label"] == "Away"]

    if df.empty:
        fig = go.Figure()
        fig.update_layout(plot_bgcolor="#0e1825", paper_bgcolor="#0e1825",
                          height=200, margin=dict(l=5, r=5, t=5, b=5))
        return fig

    df = df.sort_values("vaep_total", ascending=True)
    labels      = df["player_name"].tolist()
    team_labels = df["team_label"].tolist()
    vaep_atk    = df["vaep_attack"].tolist()
    vaep_def    = df["vaep_defend"].tolist()
    vaep_run    = (df["off_ball_xthreat"] * 0.1).tolist()

    # Color per team
    bar_colors = [COLOR_HOME if t == "Home" else COLOR_AWAY for t in team_labels]

    fig = go.Figure()

    # Attack VAEP
    fig.add_trace(go.Bar(
        y=labels, x=vaep_atk, orientation="h", name="Attack VAEP",
        marker=dict(color="rgba(59,158,255,0.8)"),
        hovertemplate="<b>%{y}</b><br>Attack VAEP: %{x:+.4f}<extra></extra>",
    ))

    # Defensive VAEP
    fig.add_trace(go.Bar(
        y=labels, x=vaep_def, orientation="h", name="Defensive VAEP",
        marker=dict(color="rgba(74,222,128,0.8)"),
        hovertemplate="<b>%{y}</b><br>Defensive VAEP: %{x:+.4f}<extra></extra>",
    ))

    # Off-ball contribution (weighted)
    fig.add_trace(go.Bar(
        y=labels, x=vaep_run, orientation="h", name="Off-ball (×0.1)",
        marker=dict(color="rgba(250,204,21,0.7)"),
        hovertemplate="<b>%{y}</b><br>Off-ball xT×0.1: %{x:+.4f}<extra></extra>",
    ))

    fig.update_layout(
        barmode="relative",
        plot_bgcolor="#0e1825", paper_bgcolor="#0e1825",
        xaxis=dict(title="VAEP", color="#b0c8e0",
                   showgrid=True, gridcolor="rgba(255,255,255,0.07)",
                   zeroline=True, zerolinecolor="rgba(255,255,255,0.35)"),
        yaxis=dict(color="#b0c8e0", tickfont=dict(size=11)),
        legend=dict(orientation="h", x=0, y=1.04, font=dict(color="white", size=10),
                    bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=10, r=10, t=30, b=10),
        height=max(300, len(df) * 28 + 80),
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# Δ xT timeline + Zone-based analysis (新規)
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_gsa_extended(df: pd.DataFrame, fps: float) -> pd.DataFrame:
    """Run add_gsa_features() on the fly if columns are missing."""
    if "Delta_Ball_xT" in df.columns and "Ball_Zone_Away" in df.columns:
        return df
    try:
        _p23_path = Path(__file__).parent / "xt_pipeline_23.py"
        _spec23 = _ilu.spec_from_file_location("_pipe23_ext", _p23_path)
        _pipe23 = _ilu.module_from_spec(_spec23)
        _spec23.loader.exec_module(_pipe23)
        return _pipe23.add_gsa_features(df, fps=fps)
    except Exception as e:
        st.warning(f"GSA拡張カラムの追加に失敗: {e}")
        return df


def build_delta_xt_chart(
    df: pd.DataFrame,
    side: str = "Away",
    time_offset: float = 0.0,
) -> go.Figure:
    """
    Δ Ball_xT を時系列バーで表示。背景はゾーン色で塗り分け。
    累積xT獲得量も折れ線で重ね描き。
    """
    if "Delta_Ball_xT" not in df.columns:
        return go.Figure()

    if "Match_Time_sec" in df.columns and (time_offset != 0.0 or df["Match_Time_sec"].max() > 60):
        times   = (df["Match_Time_sec"] + time_offset).values
        x_label = "試合時刻 (秒)"
    else:
        times   = df["Time"].values
        x_label = "Time (sec)"

    zone_col = f"Ball_Zone_{side}"
    fig = go.Figure()

    # ── ゾーン背景（横帯） ────────────────────────────────────────────────
    if zone_col in df.columns:
        zones = df[zone_col].fillna(2).astype(int).values
        i = 0
        n = len(zones)
        while i < n:
            j = i
            while j + 1 < n and zones[j + 1] == zones[i]:
                j += 1
            z = int(zones[i])
            fig.add_vrect(
                x0=float(times[i]), x1=float(times[j]),
                fillcolor={1: "rgba(94,196,255,0.07)",
                           2: "rgba(255,215,0,0.06)",
                           3: "rgba(255,85,85,0.09)"}.get(z, "rgba(0,0,0,0)"),
                line_width=0, layer="below",
            )
            i = j + 1

    # ── Δ Ball_xT バー ─────────────────────────────────────────────────
    dxt = df["Delta_Ball_xT"].values
    colors = ["rgba(74,222,128,0.85)" if v >= 0 else "rgba(255,99,99,0.75)" for v in dxt]
    fig.add_trace(go.Bar(
        x=times, y=dxt, name="Δ Ball_xT",
        marker=dict(color=colors),
        hovertemplate="t=%{x:.2f}s  Δ xT=%{y:+.4f}<extra></extra>",
    ))

    # ── 累積 xT 獲得量（折れ線・第2軸） ───────────────────────────────────
    cum_col = "Cumulative_Ball_xT_gain"
    if cum_col in df.columns:
        fig.add_trace(go.Scatter(
            x=times, y=df[cum_col].values, mode="lines", name="累積 xT 獲得",
            line=dict(color="#FFD700", width=2),
            yaxis="y2",
            hovertemplate="t=%{x:.2f}s  累積=%{y:.4f}<extra></extra>",
        ))

    # ── レイアウト ────────────────────────────────────────────────────────
    fig.update_layout(
        title=dict(
            text=(f"<b>Δ Ball_xT</b>（{side}視点ゾーン色） + "
                  f"<span style='color:#FFD700'>累積xT獲得</span>"),
            font=dict(color="white", size=11),
        ),
        plot_bgcolor="#0e1825", paper_bgcolor="#0e1825",
        xaxis=dict(title=x_label, color="#b0c8e0",
                   showgrid=True, gridcolor="rgba(255,255,255,0.05)"),
        yaxis=dict(title="Δ xT (per frame)", color="#b0c8e0",
                   showgrid=True, gridcolor="rgba(255,255,255,0.05)",
                   zeroline=True, zerolinecolor="rgba(255,255,255,0.25)"),
        yaxis2=dict(title="累積", overlaying="y", side="right",
                    color="#FFD700", showgrid=False),
        bargap=0.05,
        legend=dict(orientation="h", x=0, y=-0.25,
                    font=dict(color="white", size=9), bgcolor="rgba(0,0,0,0.4)"),
        margin=dict(l=10, r=40, t=35, b=70),
        height=240,
    )
    return fig


def render_zone_analysis(df: pd.DataFrame, fps: float) -> None:
    """ゾーン別（自陣/ミドル/アタッキングサード）の xT 集計を表示。"""
    st.markdown("---")
    st.markdown(
        "<h3 style='margin-bottom:0'>🎯 ゾーン別 xT 分析</h3>"
        "<p style='color:#8b949e;font-size:.82rem;margin-top:2px'>"
        "ボールがどのゾーンで脅威を生んだか — 攻撃側視点</p>",
        unsafe_allow_html=True,
    )

    if "Delta_Ball_xT" not in df.columns:
        st.warning("Δ Ball_xT カラムがありません（GSA拡張未実行）。")
        return

    try:
        _p23_path = Path(__file__).parent / "xt_pipeline_23.py"
        _spec23 = _ilu.spec_from_file_location("_pipe23_zone", _p23_path)
        _pipe23 = _ilu.module_from_spec(_spec23)
        _spec23.loader.exec_module(_pipe23)
    except Exception as e:
        st.error(f"pipeline_23 読み込みエラー: {e}")
        return

    side = st.radio("視点", ["Away", "Home"], horizontal=True, key="zone_side")

    zdf = _pipe23.aggregate_by_zone(df, side=side, fps=fps)
    if zdf.empty:
        st.info("ゾーン集計データが空です。")
        return

    # ── ゾーン凡例 ──
    st.caption(
        "🔵 自陣 (own third) | 🟡 ミドル (middle third) | 🔴 アタッキングサード (attacking third)"
    )

    # ── メトリクス（3列）──
    cols = st.columns(3)
    icons = {1: "🔵", 2: "🟡", 3: "🔴"}
    for i, row in zdf.iterrows():
        z   = int(row["zone"])
        col = cols[z - 1]
        col.markdown(
            f"**{icons[z]} {row['zone_label']}**"
        )
        col.metric(
            "滞在時間",
            f"{row['duration_sec']:.1f} 秒",
            f"{int(row['n_frames'])} frames",
        )
        col.metric(
            "Δ xT 合計（正のみ）",
            f"{row['delta_xt_positive']:+.4f}",
            f"ピーク {row['max_delta_xt']:+.4f}" if row['n_frames'] > 0 else None,
        )

    # ── 内訳テーブル ──
    with st.expander("📋 ゾーン別 内訳テーブル", expanded=False):
        display_df = zdf[["zone_label", "n_frames", "duration_sec",
                          "delta_xt_positive", "delta_xt_sum",
                          "max_delta_xt", "peak_frame"]].rename(columns={
            "zone_label":         "ゾーン",
            "n_frames":           "フレーム数",
            "duration_sec":       "滞在(秒)",
            "delta_xt_positive":  "Δ xT 獲得(正)",
            "delta_xt_sum":       "Δ xT 合計(正負)",
            "max_delta_xt":       "ピーク Δ xT",
            "peak_frame":         "ピーク発生Frame",
        })
        st.dataframe(display_df, use_container_width=True, hide_index=True,
                     column_config={
                         "Δ xT 獲得(正)":  st.column_config.NumberColumn(format="%+.4f"),
                         "Δ xT 合計(正負)": st.column_config.NumberColumn(format="%+.4f"),
                         "ピーク Δ xT":    st.column_config.NumberColumn(format="%+.4f"),
                     })

    # ── 解釈ヒント ──
    if not zdf.empty:
        max_zone = zdf.loc[zdf["delta_xt_positive"].idxmax()]
        st.info(
            f"💡 **{side}視点で最も xT を獲得したゾーン: "
            f"{max_zone['zone_label']}** "
            f"(Δ xT 合計 = {max_zone['delta_xt_positive']:+.4f})"
        )


def render_v23_panel(contrib_df: pd.DataFrame | None) -> None:
    """Full v23 player contribution analysis section."""
    st.markdown("---")
    st.markdown(
        "<h3 style='margin-bottom:0'>📊 v23 プレーヤー貢献度分析</h3>"
        "<p style='color:#8b949e;font-size:.82rem;margin-top:2px'>"
        "VAEP（Value of Actions by Estimating Probabilities）| オフボール貢献 | 守備評価</p>",
        unsafe_allow_html=True,
    )

    if contrib_df is None or contrib_df.empty:
        st.info(
            "**v23 貢献度データが読み込まれていません。**\n\n"
            "サイドバーの **「v23 設定」** から以下のいずれかを行ってください:\n\n"
            "1. `dynamic_events CSV` と `match_info.json` を指定して **「貢献度を計算する」** を実行\n"
            "2. 既存の `player_contributions_23.csv` のパスを指定\n\n"
            "**データフロー:**\n"
            "```\n"
            "dynamic_events.csv  →  xt_pipeline_23.py  →  player_contributions_23.csv\n"
            "```\n"
            "**VAEP の内訳:**\n"
            "- **Attack VAEP**: ボール保持中の攻撃価値変動（ΔP(score) − ΔP(concede)）\n"
            "- **Defensive VAEP**: 相手のボール保持を妨害した際の守備価値\n"
            "- **Off-ball xT**: オフボールランによる位置的脅威（×0.1 で加重）"
        )
        return

    with st.expander("ℹ️ VAEP 解釈ガイド", expanded=False):
        st.markdown("""
| 指標 | 意味 |
|---|---|
| **Attack VAEP** | ボール保持時に攻撃価値をどれだけ創出・維持したか |
| **Defensive VAEP** | 相手の攻撃価値をどれだけ削減したか（守備成功） |
| **Off-ball xT** | ランニングの質（ライン突破・スペース創出） |
| **vaep_total** | 上記の総合スコア（Off-ball は ×0.1 で加重） |

> 🔵 Home チーム / 🔴 Away チームで色分けされています。
> VAEP は `on_ball_engagement` イベントから計算。オフボールは `off_ball_run` イベント由来。
""")

    # ── Team filter ────────────────────────────────────────────────────────────
    team_filter = st.radio("表示チーム", ["両チーム", "Home", "Away"],
                           horizontal=True, key="v23_team_filter")

    # ── Top metrics ────────────────────────────────────────────────────────────
    view_df = contrib_df.copy()
    if team_filter == "Home":
        view_df = contrib_df[contrib_df["team_label"] == "Home"]
    elif team_filter == "Away":
        view_df = contrib_df[contrib_df["team_label"] == "Away"]

    if not view_df.empty:
        top = view_df.iloc[0]
        mc  = st.columns(5)
        mc[0].metric("Top VAEP 選手", top["player_name"])
        mc[1].metric("vaep_total",     f"{top['vaep_total']:+.4f}")
        mc[2].metric("Attack VAEP",    f"{top['vaep_attack']:+.4f}")
        mc[3].metric("Defensive VAEP", f"{top['vaep_defend']:+.4f}")
        mc[4].metric("Off-ball xT",    f"{top['off_ball_xthreat']:.4f}")

    # ── VAEP bar chart ─────────────────────────────────────────────────────────
    st.markdown("#### VAEP 内訳（Attack / Defensive / Off-ball）")
    st.caption("横軸: 総合 VAEP | 青 = 攻撃 | 緑 = 守備 | 黄 = オフボール（×0.1）")
    fig_vaep = build_vaep_chart(contrib_df, team_filter)
    st.plotly_chart(fig_vaep, use_container_width=True, config={"displayModeBar": False})

    # ── Two-column detail tables ───────────────────────────────────────────────
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown("#### 🏃 オフボール貢献")
        obr_cols = ["player_name", "team_label", "off_ball_xthreat", "n_runs",
                    "n_runs_line_break", "n_runs_behind"]
        obr_avail = [c for c in obr_cols if c in view_df.columns]
        obr_df = view_df[obr_avail].copy()
        obr_df = obr_df[obr_df["n_runs"] > 0] if "n_runs" in obr_df.columns else obr_df
        if obr_df.empty:
            st.caption("オフボールランなし")
        else:
            obr_df = obr_df.sort_values("off_ball_xthreat", ascending=False)
            rename_map = {
                "player_name":       "選手名",
                "team_label":        "チーム",
                "off_ball_xthreat":  "xT合計",
                "n_runs":            "ラン数",
                "n_runs_line_break": "ライン突破",
                "n_runs_behind":     "ランDL背後",
            }
            obr_df = obr_df.rename(columns={k: v for k, v in rename_map.items() if k in obr_df.columns})
            st.dataframe(obr_df, use_container_width=True, hide_index=True,
                         column_config={
                             "xT合計": st.column_config.NumberColumn(format="%.4f"),
                         })

    with col_b:
        st.markdown("#### 🛡️ 守備貢献")
        def_cols = ["player_name", "team_label", "vaep_defend", "n_engagements_def",
                    "stop_danger", "reduce_danger", "force_backward",
                    "beaten_possession", "beaten_movement"]
        def_avail = [c for c in def_cols if c in view_df.columns]
        def_df = view_df[def_avail].copy()
        def_df = def_df[def_df["n_engagements_def"] > 0] if "n_engagements_def" in def_df.columns else def_df
        if def_df.empty:
            st.caption("守備エンゲージメントなし")
        else:
            def_df = def_df.sort_values("vaep_defend", ascending=False)
            rename_map2 = {
                "player_name":        "選手名",
                "team_label":         "チーム",
                "vaep_defend":        "守備VAEP",
                "n_engagements_def":  "対人回数",
                "stop_danger":        "危機阻止",
                "reduce_danger":      "危機軽減",
                "force_backward":     "後退強制",
                "beaten_possession":  "突破(ボール)",
                "beaten_movement":    "突破(動き)",
            }
            def_df = def_df.rename(columns={k: v for k, v in rename_map2.items() if k in def_df.columns})
            st.dataframe(def_df, use_container_width=True, hide_index=True,
                         column_config={
                             "守備VAEP": st.column_config.NumberColumn(format="%+.4f"),
                         })

    # ── Full table ─────────────────────────────────────────────────────────────
    with st.expander("📋 全選手 スコア一覧", expanded=False):
        display_cols = ["player_name", "team_label", "vaep_total", "vaep_attack",
                        "vaep_defend", "off_ball_xthreat",
                        "n_engagements_atk", "n_engagements_def", "n_runs"]
        avail = [c for c in display_cols if c in view_df.columns]
        full_df = view_df[avail].rename(columns={
            "player_name":        "選手名",
            "team_label":         "チーム",
            "vaep_total":         "Total VAEP",
            "vaep_attack":        "Attack",
            "vaep_defend":        "Defend",
            "off_ball_xthreat":   "Off-ball xT",
            "n_engagements_atk":  "攻撃対人",
            "n_engagements_def":  "守備対人",
            "n_runs":             "ラン数",
        })
        st.dataframe(full_df, use_container_width=True, hide_index=True,
                     column_config={
                         "Total VAEP": st.column_config.NumberColumn(format="%+.4f"),
                         "Attack":     st.column_config.NumberColumn(format="%+.4f"),
                         "Defend":     st.column_config.NumberColumn(format="%+.4f"),
                         "Off-ball xT": st.column_config.NumberColumn(format="%.4f"),
                     })

    # ── Download ───────────────────────────────────────────────────────────────
    csv_bytes = contrib_df.to_csv(index=False).encode("utf-8")
    st.download_button("📥 貢献度CSV をダウンロード", data=csv_bytes,
                       file_name="player_contributions_23.csv", mime="text/csv")


# ══════════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    if "import_mode" not in st.session_state:
        st.session_state["import_mode"] = False
    if "import_step" not in st.session_state:
        st.session_state["import_step"] = 1

    # ── sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## ⚽ Pitch Log  <span style='color:#4ade80;font-size:.7em'>v23</span>",
                    unsafe_allow_html=True)
        st.markdown("**Phase 4+ | VAEP × Off-ball × Defensive**")
        st.divider()

        _in_wizard = st.session_state["import_mode"]
        if _in_wizard:
            if st.button("← ビューアに戻る", use_container_width=True):
                st.session_state["import_mode"] = False
                st.rerun()
        else:
            if st.button("📥 新しいシーンを取り込む", type="primary", use_container_width=True):
                st.session_state["import_mode"] = True
                st.session_state["import_step"] = 1
                st.rerun()
        st.divider()

        view_mode = st.radio(
            "解析モード",
            ["通常モード（全体xT一律評価）", "ゾーン別評価モード（縦パス特化）"],
            index=0,
        )
        zone_mode = view_mode.startswith("ゾーン")
        st.divider()

        with st.expander("📋 セットアップ手順", expanded=False):
            st.markdown("""
**すべて同じフォルダに置く**

---
**Step 1 — トラッキングデータ変換**
```
python convert_skillcorner_to_pipeline.py
```
→ `Sample_TrackingData_22.csv`

---
**Step 2 — GridID・xT付与**
```
python xt_pipeline_22.py
```
→ `Export_GSA_22players_30s.csv`
→ `match_info.json`

---
**Step 3 — v23 貢献度計算**
```
python xt_pipeline_23.py \\
  --events 1925299_dynamic_events.csv \\
  --match_info match_info.json
```
→ `player_contributions_23.csv`

---
**Step 4 — ダッシュボード起動**
```
streamlit run app_23.py
```
""")

        st.divider()
        st.markdown("### データファイル")
        xt_path     = st.text_input("xTベースマップ CSV", "xT_BaseMap_105x68.csv")
        scene_path  = st.text_input("シーン CSV", "Export_GSA_22players_30s.csv")
        causal_path = st.text_input("貢献度 CSV（任意・GSA）", "causal_scores_22.csv")
        match_info_path = st.text_input("試合情報 JSON（任意）", "match_info.json")
        time_offset = st.number_input("試合時刻オフセット（秒）", value=0.0, step=60.0, format="%.0f")
        st.divider()

        # ── xT display ────────────────────────────────────────────────────────
        st.markdown("### 表示設定")
        show_xt     = st.toggle("xTヒートマップ表示", value=True)
        xt_side     = st.radio("xTマップ視点", ["Home", "Away", "両方"], index=2, horizontal=True)
        trail_frames = st.slider("軌跡フレーム数", 0, 50, 10)
        show_home   = st.checkbox("Home 選手を表示", value=True)
        show_away   = st.checkbox("Away 選手を表示", value=True)
        show_causal = st.toggle("因果貢献度を展開", value=False)
        st.divider()

        # ── xT player selector placeholders ──────────────────────────────────
        st.markdown("#### xT タイムライン 選手選択")
        home_sel_ph = st.empty()
        away_sel_ph = st.empty()
        st.divider()

        # ── v23 section ────────────────────────────────────────────────────────
        st.markdown("### 🔬 v23 VAEP 分析")

        events_path  = st.text_input("dynamic_events CSV",
                                     "1925299_dynamic_events.csv",
                                     help="SkillCorner dynamic_events.csv のパス")
        contrib_path = st.text_input("選手貢献度 CSV",
                                     "player_contributions_23.csv",
                                     help="xt_pipeline_23.py の出力 CSV")

        # In-app computation
        with st.expander("🔄 貢献度を計算する（xt_pipeline_23）", expanded=False):
            st.caption("match_info.json のフレーム範囲でイベントを絞り込みます。")
            _home_id = st.number_input("Home Team ID", value=1802, step=1, key="v23_home_id")
            _away_id = st.number_input("Away Team ID", value=871,  step=1, key="v23_away_id")
            _override_frame = st.checkbox("フレーム範囲を手動指定", key="v23_override_frame")
            _raw_start_in = _raw_end_in = None
            if _override_frame:
                _raw_start_in = st.number_input("raw_frame_start", value=0, step=1, key="v23_rs")
                _raw_end_in   = st.number_input("raw_frame_end",   value=0, step=1, key="v23_re")

            if st.button("⚙️ 貢献度を計算する", type="primary", use_container_width=True):
                if not Path(events_path).exists():
                    st.error(f"events CSV が見つかりません: {events_path}")
                else:
                    try:
                        # Load xt_pipeline_23 dynamically
                        _p23_path = None
                        for _cand in [Path(__file__).parent / "xt_pipeline_23.py",
                                      Path(scene_path).parent / "xt_pipeline_23.py"]:
                            if _cand.exists():
                                _p23_path = _cand; break
                        if _p23_path is None:
                            st.error("xt_pipeline_23.py が見つかりません。"); st.stop()

                        _spec23 = _ilu.spec_from_file_location("_pipe23", _p23_path)
                        _pipe23 = _ilu.module_from_spec(_spec23)
                        _spec23.loader.exec_module(_pipe23)

                        _mi = _pipe23.load_match_info(match_info_path)

                        if _override_frame and _raw_start_in and _raw_end_in:
                            _rs, _re = int(_raw_start_in), int(_raw_end_in)
                        else:
                            _rs, _re = _pipe23.frame_window_from_match_info(_mi)

                        with st.spinner("VAEP 計算中…"):
                            _ev_df = pd.read_csv(events_path, low_memory=False)
                            _cont  = _pipe23.compute_player_contributions(
                                _ev_df, _rs, _re,
                                home_team_id=int(_home_id),
                                away_team_id=int(_away_id),
                            )

                        if not _cont.empty:
                            _cont.to_csv(contrib_path, index=False, encoding="utf-8")
                            if _rs is not None:
                                _pipe23.save_match_info(match_info_path, _mi, _rs, _re)
                            st.success(f"✅ {len(_cont)} 選手の貢献度を計算しました。")
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.warning("貢献度データが空です。フレーム範囲を確認してください。")

                    except Exception as _e:
                        import traceback as _tb
                        st.error(f"計算エラー: {_e}")
                        st.code(_tb.format_exc(), language="python")

    # ── Load data ─────────────────────────────────────────────────────────────
    causal_df   = load_causal(causal_path)
    contrib_df  = None
    if Path(contrib_path).exists():
        _cm = Path(contrib_path).stat().st_mtime
        contrib_df = load_contributions(contrib_path, _cm)

    scene_mtime = Path(scene_path).stat().st_mtime if Path(scene_path).exists() else 0.0
    df          = load_scene(scene_path, scene_mtime)
    h_nums      = home_nums(df)
    a_nums      = away_nums(df)
    n_frames    = len(df)
    fps         = detect_fps(df)

    with home_sel_ph:
        sel_home = st.multiselect("Home", options=h_nums, default=[],
                                  format_func=lambda n: f"H{n}", label_visibility="collapsed")
    with away_sel_ph:
        sel_away = st.multiselect("Away", options=a_nums, default=[],
                                  format_func=lambda n: f"A{n}", label_visibility="collapsed")

    match_info = load_match_info(match_info_path)

    # ── Sidebar: window re-cut ─────────────────────────────────────────────────
    with st.sidebar:
        st.divider()
        st.markdown("### 🎬 ウィンドウ再切り出し")
        raw_src    = st.text_input("ソースCSV", "Sample_TrackingData_22.csv")
        raw_exists = Path(raw_src).exists()
        if raw_exists:
            @st.cache_data(show_spinner=False)
            def _load_raw(path, _mt):
                return pd.read_csv(path)
            _raw_mt   = Path(raw_src).stat().st_mtime
            raw_df    = _load_raw(raw_src, _raw_mt)
            raw_fps_v = int(round(1.0 / pd.to_numeric(
                raw_df.get("time_sec", pd.Series([0.1])), errors="coerce"
            ).diff().dropna().median())) if len(raw_df) > 1 else 10
            n_raw = len(raw_df)
            st.caption(f"**{n_raw}** フレーム / **{n_raw/raw_fps_v:.0f}** 秒 @ {raw_fps_v} fps")
            if "is_goal_frame" in raw_df.columns:
                _gi = (raw_df["is_goal_frame"] == 1)
                default_end = int(raw_df.index[_gi].tolist()[-1]) if _gi.any() else n_raw - 1
            else:
                default_end = n_raw - 1
            new_end_frame   = st.slider("終端フレーム", 0, n_raw - 1, default_end)
            new_window_sec  = st.slider("ウィンドウ長（秒）", 5, 60, 30, step=5)
            new_start_frame = max(0, new_end_frame - new_window_sec * raw_fps_v + 1)
            if "time_sec" in raw_df.columns:
                t_s = float(raw_df.iloc[new_start_frame]["time_sec"]) + time_offset
                t_e = float(raw_df.iloc[new_end_frame]["time_sec"])   + time_offset
                st.caption(f"切り出し: **{_fmt_mmss(t_s)}** 〜 **{_fmt_mmss(t_e)}**")
            if st.button("再解析 🔄", type="primary", use_container_width=True):
                try:
                    _spec = _ilu.spec_from_file_location(
                        "_pipe", Path(raw_src).parent / "xt_pipeline_22.py")
                    if _spec is None:
                        _spec = _ilu.spec_from_file_location(
                            "_pipe", Path(__file__).parent / "xt_pipeline_22.py")
                    _pipe = _ilu.module_from_spec(_spec)
                    _spec.loader.exec_module(_pipe)
                    with st.spinner("xT計算中…"):
                        _xt  = _pipe.load_xt_map(xt_path)
                        _enr = _pipe.assign_grid_and_xt_22(raw_df, _xt)
                        _win = _enr.iloc[new_start_frame:new_end_frame+1].reset_index(drop=True)
                        _ws  = float(raw_df.iloc[new_start_frame]["time_sec"]) if "time_sec" in raw_df.columns else 0.0
                        _res = _pipe.reformat_to_22player_schema(_win, raw_fps_v, _ws)
                        _res = _pipe.add_zone_and_lbp_columns(_res, raw_fps_v)
                        _res.to_csv(scene_path, index=False)
                        _meta = (match_info.copy() or {})
                        _meta.update({
                            "window_start_sec": round(_ws, 3),
                            "window_end_sec":   round(float(raw_df.iloc[new_end_frame]["time_sec"]) if "time_sec" in raw_df.columns else _ws + new_window_sec, 3),
                            "window_sec":   new_window_sec,
                            "window_frames": len(_win),
                            "goal_frame_raw": int(raw_df.iloc[new_end_frame]["frame"]) if "frame" in raw_df.columns else new_end_frame,
                        })
                        with open(match_info_path, "w", encoding="utf-8") as _mf:
                            json.dump(_meta, _mf, indent=2, ensure_ascii=False)
                    st.success(f"完了: {len(_win)}フレーム"); st.rerun()
                except Exception as _e:
                    st.error(f"エラー: {_e}")
        else:
            st.caption(f"`{raw_src}` が見つかりません。")

        # GSA export
        st.divider()
        st.markdown("### 📤 GSAエクスポート")
        if n_frames > 1:
            frame_range = st.slider("エクスポート範囲 (Frame)", 1, n_frames, (1, n_frames))
        else:
            frame_range = (1, n_frames)
        f_start, f_end = frame_range
        n_export = f_end - f_start + 1
        st.caption(f"**{n_export}** フレーム / **{n_export/fps:.1f}** 秒")

        gsa_extend = st.checkbox(
            "🔬 GSA推奨カラムを追加する",
            value=True,
            help=(
                "下記カラムを自動追加します:\n"
                "・Delta_Ball_xT / Delta_Away_MAX_xT 等（目的変数候補）\n"
                "・各選手とボールの距離（22カラム）\n"
                "・各選手の速度（22カラム）\n"
                "※ X, Y, GridID は xT と重複するので GSA 側で除外推奨"
            ),
        )

        exp_df = df.iloc[f_start-1:f_end].copy().reset_index(drop=True)
        exp_df["Frame"] = range(1, len(exp_df) + 1)

        if gsa_extend:
            try:
                _p23_path = Path(__file__).parent / "xt_pipeline_23.py"
                _spec23 = _ilu.spec_from_file_location("_pipe23_gsa", _p23_path)
                _pipe23 = _ilu.module_from_spec(_spec23)
                _spec23.loader.exec_module(_pipe23)
                exp_df = _pipe23.add_gsa_features(exp_df, fps=fps)
                st.caption(f"✅ GSA拡張: **{len(exp_df.columns)}** カラム "
                           f"（Delta系 + dist_ball + speed 追加）")
            except Exception as _e:
                st.warning(f"GSA拡張エラー: {_e}")

        csv_b = exp_df.to_csv(index=False).encode("utf-8")
        suffix = "_gsa_ext" if gsa_extend else ""
        fname  = f"GSA_export_F{f_start:04d}-{f_end:04d}_{n_export}frames_{n_export/fps:.0f}s{suffix}.csv"
        st.download_button("📥 CSVをダウンロード", data=csv_b, file_name=fname,
                           mime="text/csv", use_container_width=True)

    # ── Wizard mode ───────────────────────────────────────────────────────────
    if st.session_state.get("import_mode", False):
        st.markdown(
            "<h2 style='margin-bottom:0'>📥 シーン取り込みウィザード</h2>"
            "<p style='color:#8b949e;margin-top:2px;font-size:.85rem'>"
            "生トラッキングCSVを読み込み、シーンを指定して変換します</p>",
            unsafe_allow_html=True,
        )
        render_import_wizard(xt_path, scene_path, match_info_path)
        return

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        "<h2 style='margin-bottom:0'>⚽ Pitch Log v23 — 22-Player Scene Viewer</h2>"
        "<p style='color:#8b949e;margin-top:2px;font-size:.85rem'>"
        "xT × VAEP × Off-ball × Defensive Analysis</p>",
        unsafe_allow_html=True,
    )

    # ── Scene info ────────────────────────────────────────────────────────────
    _ws  = match_info.get("window_start_sec", 0.0) + time_offset
    _we  = match_info.get("window_end_sec", _ws + n_frames / fps) + time_offset
    _mn  = match_info.get("match_name", "")
    _mr  = match_info.get("match_round", "")
    _wf  = match_info.get("window_frames", n_frames)

    if _mn:
        _t_range = (f"{_fmt_mmss(_ws)} 〜 {_fmt_mmss(_we)}"
                    if (time_offset != 0 or _ws > 60) else f"{_ws:.1f}s 〜 {_we:.1f}s")
        st.info(f"📍 **{_mn}** | {_mr}  \n"
                f"現在表示: **{_t_range}** — {_wf} フレーム @ {fps:.0f} fps")
    else:
        st.info(f"📍 **{scene_path}** | {n_frames} フレーム | 相対 0s〜{n_frames/fps:.1f}s | {fps:.0f} fps")

    # ── Metrics ───────────────────────────────────────────────────────────────
    peak_xt = float(df["Ball_xT"].max()) if "Ball_xT" in df.columns else 0.0
    mc = st.columns(6)
    mc[0].metric("総フレーム数",  f"{n_frames}")
    mc[1].metric("シーン長",      f"{n_frames / fps:.1f} 秒")
    mc[2].metric("Peak Ball xT", f"{peak_xt:.4f}")
    mc[3].metric("Home 選手数",   f"{len(h_nums)}")
    mc[4].metric("Away 選手数",   f"{len(a_nums)}")
    mc[5].metric("v23 選手数",    f"{len(contrib_df)}" if contrib_df is not None else "—",
                 help="player_contributions_23.csv の選手数")
    st.divider()

    # ── Two-panel layout ──────────────────────────────────────────────────────
    col_l, col_r = st.columns([11, 9], gap="medium")

    with col_l:
        if zone_mode:
            st.markdown("#### ゾーン別ピッチビュー  🟢 LBP検知  🔵 Home  🔴 Away")
            st.caption("Zone1: セーフ (X<33%) | Zone2: ビルド (33-66%) | Zone3: アタッキングサード (X>66%)")
            fig_pitch = build_zone_animated_fig(
                xt_path, scene_path, show_xt, trail_frames, fps,
                show_home=show_home, show_away=show_away, xt_side=xt_side,
            )
        else:
            st.markdown("#### ピッチビュー  🔵 Home  🔴 Away  🟡 Ball")
            st.caption("▶/⏸/×0.5/×1/×2/×4/⏮ で操作 | スライダーでコマ送り")
            fig_pitch = build_animated_fig(
                xt_path, scene_path, show_xt, trail_frames, fps,
                show_home=show_home, show_away=show_away, xt_side=xt_side,
            )
        st.plotly_chart(fig_pitch, use_container_width=True, config={"displayModeBar": False})

    with col_r:
        if zone_mode:
            st.markdown("#### ラインブレイクパス検知アラート")
            lbp_df = _compute_lbp_inapp(df, fps, h_nums, a_nums)
            render_lbp_alerts(lbp_df)
            st.divider()

        st.markdown("#### xT タイムライン（30秒全体）")
        fig_line = build_timeline_fig(df, sel_home, sel_away, h_nums, a_nums, time_offset)
        st.plotly_chart(fig_line, use_container_width=True, config={"displayModeBar": False})

        # ── Δ xT タイムライン（新規） ────────────────────────────────────
        st.markdown("#### Δ xT タイムライン（時間ごとの増加量）")
        st.caption(
            "🟢 増加 / 🔴 減少 | 背景色はゾーン "
            "(🔵自陣 / 🟡ミドル / 🔴アタッキングサード)"
        )
        df_ext = _ensure_gsa_extended(df, fps)
        delta_side = st.radio("ゾーン視点", ["Away", "Home"],
                              horizontal=True, key="delta_side")
        fig_delta = build_delta_xt_chart(df_ext, side=delta_side, time_offset=time_offset)
        st.plotly_chart(fig_delta, use_container_width=True,
                        config={"displayModeBar": False})

        render_contribution_panel(causal_df, h_nums, a_nums, show_causal)

    # ── Frame data table ──────────────────────────────────────────────────────
    with st.expander("フレームデータ詳細（先頭フレーム）", expanded=False):
        row = df.iloc[0]
        rows_data = [{"チーム": "—", "選手": "Ball",
                      "X": f"{row['Ball_X']:.5f}", "Y": f"{row['Ball_Y']:.5f}",
                      "GridID": row["Ball_GridID"], "xT": f"{row['Ball_xT']:.5f}"}]
        for n in h_nums:
            rows_data.append({"チーム": "Home", "選手": f"P{n}",
                               "X": f"{row.get(f'Home_P{n}_X', np.nan):.5f}",
                               "Y": f"{row.get(f'Home_P{n}_Y', np.nan):.5f}",
                               "GridID": row.get(f"Home_P{n}_GridID", pd.NA),
                               "xT": f"{row.get(f'Home_P{n}_xT', np.nan):.5f}"})
        for n in a_nums:
            rows_data.append({"チーム": "Away", "選手": f"P{n}",
                               "X": f"{row.get(f'Away_P{n}_X', np.nan):.5f}",
                               "Y": f"{row.get(f'Away_P{n}_Y', np.nan):.5f}",
                               "GridID": row.get(f"Away_P{n}_GridID", pd.NA),
                               "xT": f"{row.get(f'Away_P{n}_xT', np.nan):.5f}"})
        st.dataframe(pd.DataFrame(rows_data), use_container_width=True, hide_index=True)

    # ── ゾーン別 xT 分析（新規） ───────────────────────────────────────────────
    render_zone_analysis(_ensure_gsa_extended(df, fps), fps)

    # ── v23 VAEP panel ─────────────────────────────────────────────────────────
    render_v23_panel(contrib_df)

    # ── 試合全体モメンタム（90分・xT added）───────────────────────────────────
    st.divider()
    st.markdown("## 📈 試合全体モメンタム（90分）")
    st.caption("このシーンが試合全体のどの局面か俯瞰。ピンチ・チャンス・ゴールを時系列で確認できます。")
    try:
        import match_momentum
        match_momentum.render_momentum("match_phases_summary.csv", key_prefix="mom23")
    except Exception as _e:
        st.info(f"モメンタム表示を読み込めませんでした: {_e}")

    st.markdown(
        "<p style='text-align:center;color:#30363d;font-size:.7rem;margin-top:1rem'>"
        "Pitch Log v23 | xT × VAEP × Off-ball × Defensive Analysis</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()

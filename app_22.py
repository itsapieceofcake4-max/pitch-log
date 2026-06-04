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

import json
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

# ── Match metadata helpers ─────────────────────────────────────────────────────

def _fmt_mmss(sec: float) -> str:
    """Convert seconds to M:SS string (e.g. 4452 → '74:12')."""
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


# ── Scene import wizard helpers ───────────────────────────────────────────────

def _parse_mmss(s: str) -> float | None:
    """'M:SS' / 'MM:SS' / plain-seconds string → float seconds, None on error."""
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
    """Float seconds → 'M:SS' label (e.g. 4472 → '74:32')."""
    sec = max(0.0, float(sec))
    return f"{int(sec) // 60}:{int(sec) % 60:02d}"


def _mini_pitch_fig(row: "pd.Series", h_nums: list[int], a_nums: list[int],
                    schema: str = "raw") -> "go.Figure":
    """
    Static single-frame pitch snapshot for scene preview.
    schema='raw'  → columns like Home_1_x / ball_x
    schema='proc' → columns like Home_P1_X / Ball_X
    """
    fig = go.Figure()
    for tr in _pitch_traces():
        fig.add_trace(tr)

    def _col(raw_name: str, proc_name: str) -> float:
        v = row.get(raw_name if schema == "raw" else proc_name, np.nan)
        return float(v) if pd.notna(v) else np.nan

    # Ball
    bx = _col("ball_x", "Ball_X")
    by = _col("ball_y", "Ball_Y")
    if not np.isnan(bx):
        fig.add_trace(go.Scatter(
            x=[bx * PITCH_W], y=[by * PITCH_H], mode="markers",
            marker=dict(size=13, color="rgba(255,215,0,0.8)",
                        line=dict(color="white", width=1.5)),
            showlegend=False, hoverinfo="skip",
        ))

    # Home players
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

    # Away players
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


# ── Wizard step indicator ──────────────────────────────────────────────────────

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


# ── Full scene import wizard ───────────────────────────────────────────────────

def render_import_wizard(xt_path: str, scene_path: str, match_info_path: str) -> None:
    """4-step wizard: load full CSV → find scene → metadata → convert & save."""
    ss   = st.session_state
    step = ss.get("import_step", 1)
    _wizard_steps(step)

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 1 — Load full tracking CSV
    # ─────────────────────────────────────────────────────────────────────────
    if step == 1:
        st.markdown("### データ読み込み")
        st.caption(
            "試合全体（フルタイム）のトラッキングCSVを読み込みます。  \n"
            "30秒への切り出しは次のステップで行います。"
        )

        # ── データ取得先ガイド ────────────────────────────────────────────
        with st.expander("📡 トラッキングデータの取得先", expanded=False):
            st.markdown("""
#### 🏆 SkillCorner（本番データ）
契約クラブ・リーグのデータはこちらから入手します。

| リンク | 内容 |
|---|---|
| [SkillCorner 公式サイト](https://www.skillcorner.com/) | サービス概要・お問い合わせ |
| [SkillCorner Client Portal](https://platform.skillcorner.com/) | 試合データのダウンロード（要ログイン） |
| [SkillCorner Open Data (GitHub)](https://github.com/SkillCorner/opendata) | 無償公開サンプルデータ（実際のリーグ試合データを含む） |
| [SkillCorner API ドキュメント](https://skillcorner.com/blog/) | API連携を使う場合の参考情報 |

---

#### 📂 SkillCorner Open Data — すぐ試せるサンプル
GitHubリポジトリに実際の試合データが公開されています。

```
https://github.com/SkillCorner/opendata
```

`data/` フォルダの中の `tracking_data.csv` または `tracking_data.json` を
ダウンロードして使えます。

> **注意**: SkillCorner のネイティブ形式（JSON）の場合は、
> `convert_skillcorner_to_pipeline.py` で変換してからアップロードしてください。

---

#### 🔬 その他の公開データソース（形式変換が必要）

| ソース | 内容 | リンク |
|---|---|---|
| **StatsBomb Open Data** | イベントデータ（座標付き） | [GitHub](https://github.com/statsbomb/open-data) |
| **Metrica Sports** | トラッキングデータ（サンプル） | [GitHub](https://github.com/metrica-sports/sample-data) |
| **Tracab / TRACAB** | 放送局向けトラッキング | 要契約 |
| **Second Spectrum** | MLS等のトラッキング | 要契約 |

> StatsBomb・Metrica のデータは座標形式が異なるため、
> カラム名と正規化を合わせる変換スクリプトが別途必要です。

---

#### 📋 このアプリが期待するCSV形式

```
frame, time_sec, ball_x, ball_y, is_goal_frame,
Home_1_x, Home_1_y, Home_2_x, Home_2_y, ..., Home_11_x, Home_11_y,
Away_1_x, Away_1_y, ..., Away_11_x, Away_11_y
```

- 座標はすべて **0〜1 に正規化**（ピッチ左下原点）
- Home チームは `x=1` 方向に攻撃
- FPS は 10fps（SkillCorner 標準）を想定
""")

        st.divider()

        _src = st.radio("データソース", ["💾 ファイルアップロード", "🌐 URL指定"],
                        horizontal=True, key="wiz_src")
        _raw_bytes: bytes | None = None
        _fname = ""

        if _src == "💾 ファイルアップロード":
            _up = st.file_uploader(
                "トラッキングCSV（試合全体）", type=["csv"],
                help=(
                    "必要なカラム:\n"
                    "frame, time_sec, ball_x, ball_y,\n"
                    "Home_1_x, Home_1_y … Away_11_x, Away_11_y\n"
                    "（座標は 0〜1 に正規化）"
                ),
                key="wiz_upload",
            )
            if _up:
                _raw_bytes = _up.getvalue()
                _fname     = _up.name
                ss.pop("wiz_raw_bytes", None)

        else:
            _url = st.text_input("CSV の URL",
                                 placeholder="https://example.com/match_tracking.csv",
                                 key="wiz_url")
            if st.button("⬇️ ダウンロード", key="wiz_dl", use_container_width=True):
                if _url:
                    try:
                        import urllib.request as _ur
                        with st.spinner("ダウンロード中…"):
                            req = _ur.Request(_url, headers={"User-Agent": "PitchLog/1.0"})
                            with _ur.urlopen(req, timeout=60) as r:
                                _dl = r.read()
                        ss["wiz_raw_bytes"] = _dl
                        ss["wiz_fname"]     = _url.split("/")[-1]
                        st.success(f"ダウンロード完了  ({len(_dl) // 1024} KB)")
                    except Exception as e:
                        st.error(f"ダウンロードエラー: {e}")
                else:
                    st.warning("URLを入力してください")

            if "wiz_raw_bytes" in ss:
                _raw_bytes = ss["wiz_raw_bytes"]
                _fname     = ss.get("wiz_fname", "downloaded.csv")
                st.caption(f"✅ ダウンロード済  ({len(_raw_bytes) // 1024} KB)")

        if _raw_bytes:
            import io as _io
            with st.spinner("CSVを解析中…"):
                _raw_df = pd.read_csv(_io.BytesIO(_raw_bytes))
            _dt = pd.to_numeric(
                _raw_df["time_sec"] if "time_sec" in _raw_df.columns else pd.Series([0.1]),
                errors="coerce",
            ).diff().dropna()
            _fps = int(round(1.0 / _dt.median())) if len(_dt) > 0 and _dt.median() > 0 else 10
            _dur = len(_raw_df) / _fps

            c1, c2, c3 = st.columns(3)
            c1.metric("総フレーム数", f"{len(_raw_df):,}")
            c2.metric("試合時間",     f"{int(_dur // 60)}分 {int(_dur % 60)}秒")
            c3.metric("FPS",          str(_fps))

            _has_ball = "ball_x" in _raw_df.columns or "Ball_X" in _raw_df.columns
            if not _has_ball:
                st.error("ball_x / Ball_X カラムが見つかりません。")
                with st.expander("カラム一覧を確認"):
                    st.write(list(_raw_df.columns))
            else:
                st.success(f"✅ **{_fname}**  読み込み完了")
                if st.button("次へ → シーン特定 ▶", type="primary", use_container_width=True):
                    ss["import_raw_df"]    = _raw_df
                    ss["import_raw_fps"]   = _fps
                    ss["import_raw_dur"]   = _dur
                    ss["import_raw_fname"] = _fname
                    ss["import_step"]      = 2
                    st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 2 — Scene finder: trajectory timeline + time range picker + preview
    # ─────────────────────────────────────────────────────────────────────────
    elif step == 2:
        _raw_df = ss.get("import_raw_df")
        _fps    = ss.get("import_raw_fps", 10)
        _dur    = ss.get("import_raw_dur",  0.0)

        if _raw_df is None:
            st.error("データがありません。Step 1 からやり直してください。")
            if st.button("← Step 1 へ戻る"):
                ss["import_step"] = 1; st.rerun()
            return

        st.markdown("### シーン特定 — 切り出す場面を選ぶ")
        st.caption(
            "映像を見ながら場面の時刻を入力してください。  \n"
            "下のボールトラジェクトリで場面の大まかな位置も確認できます。"
        )

        # Ball trajectory timeline (downsampled ≤2000 pts)
        _bx_col = "ball_x" if "ball_x" in _raw_df.columns else "Ball_X"
        _t_col  = "time_sec" if "time_sec" in _raw_df.columns else "Time"
        _ds     = max(1, len(_raw_df) // 2000)
        _tl     = _raw_df.iloc[::_ds].copy()
        _tv     = (pd.to_numeric(_tl[_t_col], errors="coerce").values
                   if _t_col in _tl.columns else np.arange(len(_tl)) / _fps)
        _bxv    = pd.to_numeric(_tl[_bx_col], errors="coerce").fillna(0.5).values * PITCH_W

        _tl_fig = go.Figure()
        _tl_fig.add_trace(go.Scatter(
            x=_tv, y=_bxv, mode="lines",
            line=dict(color="rgba(255,215,0,0.75)", width=1.5),
            hovertemplate="時刻: %{x:.1f}s<br>Ball X: %{y:.1f}m<extra></extra>",
        ))
        _tl_fig.add_hline(y=PITCH_W / 2,
                          line=dict(color="rgba(255,255,255,0.25)", dash="dot", width=1))
        _tick_vals = list(range(0, int(_dur) + 60, 300))
        _tl_fig.update_layout(
            plot_bgcolor="#0e1825", paper_bgcolor="#0e1825",
            xaxis=dict(
                title="時刻",
                tickvals=_tick_vals,
                ticktext=[_tick_mmss(v) for v in _tick_vals],
                color="#b0c8e0", showgrid=True,
                gridcolor="rgba(255,255,255,0.07)",
            ),
            yaxis=dict(title="Ball X (m)", color="#b0c8e0",
                       range=[0, PITCH_W],
                       showgrid=True, gridcolor="rgba(255,255,255,0.07)"),
            margin=dict(l=10, r=10, t=8, b=40), height=200, showlegend=False,
        )
        st.plotly_chart(_tl_fig, use_container_width=True,
                        config={"displayModeBar": False})

        st.divider()
        st.markdown("#### 切り出し範囲を入力  （M:SS または 秒）")
        _ic1, _ic2 = st.columns(2)
        _ts_str = _ic1.text_input("▶ 開始時刻", value="0:00", key="wiz_tstart",
                                   help="例: 74:02  または  4442")
        _te_str = _ic2.text_input("⏹ 終了時刻", value=_tick_mmss(min(30.0, _dur)),
                                   key="wiz_tend", help="例: 74:32  または  4472")

        _ts = _parse_mmss(_ts_str)
        _te = _parse_mmss(_te_str)
        _ok = True
        if _ts is None:   _ic1.error("形式エラー  例: 74:02"); _ok = False
        if _te is None:   _ic2.error("形式エラー  例: 74:32"); _ok = False
        if _ok and _te <= _ts:
            st.error("終了時刻は開始時刻より後にしてください"); _ok = False

        if _ok:
            # Frame indices
            if _t_col in _raw_df.columns:
                _tv_full = pd.to_numeric(_raw_df[_t_col], errors="coerce").fillna(0)
                _fs = int((_tv_full - _ts).abs().idxmin())
                _fe = int((_tv_full - _te).abs().idxmin())
            else:
                _fs = max(0, int(_ts * _fps))
                _fe = min(len(_raw_df) - 1, int(_te * _fps))
            _fe = min(_fe, len(_raw_df) - 1)

            _dur_sel = (_fe - _fs) / _fps
            st.info(
                f"📍 **{_tick_mmss(_ts)}** 〜 **{_tick_mmss(_te)}** — "
                f"{_dur_sel:.1f}秒 / {_fe - _fs}フレーム"
            )

            # Detect raw player column numbers
            _hraw = sorted({int(m.group(1)) for col in _raw_df.columns
                            for m in [re.match(r"^Home_(\d+)_x$", col)] if m})
            _araw = sorted({int(m.group(1)) for col in _raw_df.columns
                            for m in [re.match(r"^Away_(\d+)_x$", col)] if m})
            if not _hraw:  # processed schema fallback
                _hraw = sorted({int(m.group(1)) for col in _raw_df.columns
                                for m in [re.match(r"^Home_P(\d+)_X$", col)] if m})
                _araw = sorted({int(m.group(1)) for col in _raw_df.columns
                                for m in [re.match(r"^Away_P(\d+)_X$", col)] if m})
            _schema = "raw" if "ball_x" in _raw_df.columns else "proc"

            # Mini pitch preview
            st.markdown("#### フレームプレビュー")
            _pc1, _pc2 = st.columns(2)
            with _pc1:
                st.caption(f"▶ 開始フレーム  {_tick_mmss(_ts)}")
                st.plotly_chart(
                    _mini_pitch_fig(_raw_df.iloc[_fs], _hraw, _araw, _schema),
                    use_container_width=True, config={"displayModeBar": False},
                )
            with _pc2:
                st.caption(f"⏹ 終了フレーム  {_tick_mmss(_te)}")
                st.plotly_chart(
                    _mini_pitch_fig(_raw_df.iloc[_fe], _hraw, _araw, _schema),
                    use_container_width=True, config={"displayModeBar": False},
                )

            st.divider()
            _n1, _n2 = st.columns(2)
            if _n1.button("← 戻る", use_container_width=True):
                ss["import_step"] = 1; st.rerun()
            if _n2.button("次へ → シーン情報 ▶", type="primary", use_container_width=True):
                ss.update({
                    "import_frame_start": _fs,
                    "import_frame_end":   _fe,
                    "import_t_start":     _ts,
                    "import_t_end":       _te,
                    "import_h_nums_raw":  _hraw,
                    "import_a_nums_raw":  _araw,
                    "import_schema":      _schema,
                    "import_step":        3,
                })
                st.rerun()
        else:
            if st.button("← 戻る", use_container_width=True):
                ss["import_step"] = 1; st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 3 — Scene metadata
    # ─────────────────────────────────────────────────────────────────────────
    elif step == 3:
        _ts = ss.get("import_t_start", 0.0)
        _te = ss.get("import_t_end",  30.0)

        st.markdown("### シーン情報を入力")
        st.info(
            f"切り出し範囲: **{_tick_mmss(_ts)}** 〜 **{_tick_mmss(_te)}**  "
            f"（{_te - _ts:.1f}秒）"
        )

        SCENE_TYPES = [
            "⚽ ゴールシーン",
            "🛡️ ディフェンスシーン",
            "🔄 プレッシング",
            "🏗️ ビルドアップ",
            "📍 セットプレー（CK/FK）",
            "⚠️ 被ゴール",
            "📝 その他",
        ]
        _stype = st.selectbox("シーンタイプ", SCENE_TYPES, key="wiz_stype")
        _sname = st.text_input(
            "シーン名（自由記述）",
            placeholder="例: 74分 左サイドからのカウンター",
            key="wiz_sname",
        )
        st.divider()
        _mname  = st.text_input("試合名",    placeholder="Brisbane Roar 0-1 Perth Glory", key="wiz_mname")
        _mround = st.text_input("ラウンド",  placeholder="Round 09 | A-League 2024-25",   key="wiz_mround")

        st.divider()
        _n1, _n2 = st.columns(2)
        if _n1.button("← 戻る", use_container_width=True):
            ss["import_step"] = 2; st.rerun()
        if _n2.button("次へ → 変換確認 ▶", type="primary", use_container_width=True):
            ss.update({
                "import_scene_type":  _stype,
                "import_scene_name":  _sname,
                "import_match_name":  _mname,
                "import_match_round": _mround,
                "import_step":        4,
            })
            st.rerun()

    # ─────────────────────────────────────────────────────────────────────────
    # STEP 4 — Convert & save
    # ─────────────────────────────────────────────────────────────────────────
    elif step == 4:
        _raw_df = ss.get("import_raw_df")
        _fps    = ss.get("import_raw_fps", 10)
        _fs     = ss.get("import_frame_start", 0)
        _fe     = ss.get("import_frame_end",   0)
        _ts     = ss.get("import_t_start", 0.0)
        _te     = ss.get("import_t_end",  30.0)
        _stype  = ss.get("import_scene_type",  "")
        _sname  = ss.get("import_scene_name",  "")
        _mname  = ss.get("import_match_name",  "Unknown Match")
        _mround = ss.get("import_match_round", "")

        st.markdown("### 変換・保存の確認")

        c1, c2 = st.columns(2)
        c1.markdown(
            f"**試合**  \n{_mname or '（未入力）'}  \n{_mround or ''}",
        )
        c2.markdown(
            f"**シーン**  \n{_stype}  \n{_sname or '（名前なし）'}",
        )
        st.info(
            f"⏱ **{_tick_mmss(_ts)}** 〜 **{_tick_mmss(_te)}**  "
            f"（{_te - _ts:.1f}秒 / {_fe - _fs}フレーム @ {_fps} fps）  \n"
            f"出力先: `{scene_path}`  /  `{match_info_path}`"
        )

        _n1, _n2 = st.columns(2)
        if _n1.button("← 戻る", use_container_width=True):
            ss["import_step"] = 3; st.rerun()

        if _n2.button("🔄 変換して読み込む", type="primary", use_container_width=True):
            try:
                import importlib.util as _ilu

                _pipe_path = Path(__file__).parent / "xt_pipeline_22.py"
                if not _pipe_path.exists():
                    _pipe_path = Path(scene_path).parent / "xt_pipeline_22.py"
                if not _pipe_path.exists():
                    st.error("xt_pipeline_22.py が見つかりません。")
                    st.stop()

                _spec = _ilu.spec_from_file_location("_pipe", _pipe_path)
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

                st.success(
                    f"✅ 変換完了！  {len(_win)} フレーム（{_te - _ts:.1f}秒）を保存しました。"
                )
                # Clear wizard state and exit
                for k in list(ss.keys()):
                    if k.startswith("import_") or k.startswith("wiz_"):
                        ss.pop(k, None)
                ss["import_mode"] = False
                st.rerun()

            except Exception as _e:
                import traceback as _tb
                st.error(f"変換エラー: {_e}")
                st.code(_tb.format_exc(), language="python")


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
    show_home: bool = True,
    show_away: bool = True,
    xt_side: str = "Home",
) -> go.Figure:
    """
    Pre-compute Plotly frames so playback runs entirely in the browser.

    Animated trace layout per frame (6 traces):
        0  ball trail
        1  home trails  (all 11 combined with None separators)
        2  away trails  (all 11 combined with None separators)
        3  home player dots  (markers+text, blue, with hover customdata)
        4  away player dots  (markers+text, red,  with hover customdata)
        5  ball dot          (marker, semi-transparent yellow, with hover)

    xt_side: "Home" | "Away" | "両方"
    """
    xt_map   = load_xt_map(xt_path)
    df       = load_scene(scene_path)
    h_nums   = home_nums(df)
    a_nums   = away_nums(df)
    n_frames = len(df)

    xt_map_away = xt_map[:, ::-1]   # mirror for Away team

    # ── static traces ─────────────────────────────────────────────────────────
    static: list = []

    if show_xt:
        xc   = np.arange(X_BINS) + 0.5
        yc   = np.arange(Y_BINS) + 0.5
        zmax = float(np.percentile(xt_map[xt_map > 0], 99)) if xt_map.max() > 0 else 1.0

        # Home xT heatmap (warm colorscale)
        if xt_side in ("Home", "両方"):
            h_opacity = 0.65 if xt_side == "両方" else 1.0
            static.append(go.Heatmap(
                z=xt_map.tolist(), x=xc.tolist(), y=yc.tolist(),
                colorscale=[
                    [0.00, "rgba(0,20,60,0)"],
                    [0.25, f"rgba(90,170,255,{0.18*h_opacity:.2f})"],
                    [0.50, f"rgba(59,158,255,{0.38*h_opacity:.2f})"],
                    [0.75, f"rgba(30,100,235,{0.58*h_opacity:.2f})"],
                    [1.00, f"rgba(10,50,190,{0.82*h_opacity:.2f})"],
                ],
                zmin=0, zmax=zmax,
                showscale=(xt_side != "両方"),
                colorbar=dict(
                    title=dict(text="xT (Home)", font=dict(color="white", size=11)),
                    thickness=10, len=0.55,
                    tickfont=dict(color="white", size=9),
                ),
                hoverinfo="skip",
            ))

        # Away xT heatmap (cool blue colorscale, mirrored)
        if xt_side in ("Away", "両方"):
            a_opacity = 0.65 if xt_side == "両方" else 1.0
            static.append(go.Heatmap(
                z=xt_map_away.tolist(), x=xc.tolist(), y=yc.tolist(),
                colorscale=[
                    [0.00, "rgba(60,0,0,0)"],
                    [0.25, f"rgba(255,140,140,{0.18*a_opacity:.2f})"],
                    [0.50, f"rgba(255,85,85,{0.38*a_opacity:.2f})"],
                    [0.75, f"rgba(235,45,45,{0.58*a_opacity:.2f})"],
                    [1.00, f"rgba(180,0,0,{0.82*a_opacity:.2f})"],
                ],
                zmin=0, zmax=zmax,
                showscale=True,
                colorbar=dict(
                    title=dict(text="xT (Away)", font=dict(color="white", size=11)),
                    thickness=10, len=0.55, x=1.08,
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

        # ④ home player dots (blue) — hidden when show_home=False
        if show_home:
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
        else:
            out.append(go.Scatter(x=[], y=[], mode="markers", showlegend=False, hoverinfo="skip"))

        # ⑤ away player dots (red) — hidden when show_away=False
        if show_away:
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
        else:
            out.append(go.Scatter(x=[], y=[], mode="markers", showlegend=False, hoverinfo="skip"))

        # ⑥ ball dot (semi-transparent yellow)
        bx  = row.get("Ball_X",      np.nan)
        by  = row.get("Ball_Y",      np.nan)
        bxt = float(row.get("Ball_xT",     0) or 0)
        bgd = int(row.get("Ball_GridID",   0) or 0)
        out.append(go.Scatter(
            x=[float(bx) * PITCH_W] if pd.notna(bx) else [None],
            y=[float(by) * PITCH_H] if pd.notna(by) else [None],
            mode="markers",
            marker=dict(size=14, color="rgba(255,215,0,0.55)",
                        line=dict(color="#aaa", width=1.5)),
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
            "showactive": False,
            "bgcolor": "#1e2a1e",
            "bordercolor": "rgba(255,255,255,0.20)",
            "font": {"color": "white", "size": 13},
            "x": 0.0, "y": -0.13,
            "xanchor": "left", "yanchor": "top",
            "direction": "right",
            "buttons": [
                {"label": "▶",
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
                {"label": "×1",
                 "method": "animate",
                 "args": [None, {"frame": {"duration": int(1000 / fps), "redraw": True},
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
    show_home: bool = True,
    show_away: bool = True,
    xt_side: str = "Home",
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

    xt_map_away = xt_map[:, ::-1]   # mirror for Away team

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

        # Home xT heatmap (warm colorscale)
        if xt_side in ("Home", "両方"):
            h_opacity = 0.65 if xt_side == "両方" else 1.0
            static.append(go.Heatmap(
                z=xt_map.tolist(), x=xc.tolist(), y=yc.tolist(),
                colorscale=[
                    [0.00, "rgba(0,20,60,0)"],
                    [0.25, f"rgba(90,170,255,{0.18*h_opacity:.2f})"],
                    [0.50, f"rgba(59,158,255,{0.38*h_opacity:.2f})"],
                    [0.75, f"rgba(30,100,235,{0.58*h_opacity:.2f})"],
                    [1.00, f"rgba(10,50,190,{0.82*h_opacity:.2f})"],
                ],
                zmin=0, zmax=zmax,
                showscale=(xt_side != "両方"),
                colorbar=dict(
                    title=dict(text="xT (Home)", font=dict(color="white", size=11)),
                    thickness=10, len=0.55,
                    tickfont=dict(color="white", size=9),
                ),
                hoverinfo="skip",
            ))

        # Away xT heatmap (cool blue colorscale, mirrored)
        if xt_side in ("Away", "両方"):
            a_opacity = 0.65 if xt_side == "両方" else 1.0
            static.append(go.Heatmap(
                z=xt_map_away.tolist(), x=xc.tolist(), y=yc.tolist(),
                colorscale=[
                    [0.00, "rgba(60,0,0,0)"],
                    [0.25, f"rgba(255,140,140,{0.18*a_opacity:.2f})"],
                    [0.50, f"rgba(255,85,85,{0.38*a_opacity:.2f})"],
                    [0.75, f"rgba(235,45,45,{0.58*a_opacity:.2f})"],
                    [1.00, f"rgba(180,0,0,{0.82*a_opacity:.2f})"],
                ],
                zmin=0, zmax=zmax,
                showscale=True,
                colorbar=dict(
                    title=dict(text="xT (Away)", font=dict(color="white", size=11)),
                    thickness=10, len=0.55, x=1.08,
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

        # ④ home player dots (blue) — hidden when show_home=False
        if show_home:
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
        else:
            out.append(go.Scatter(x=[], y=[], mode="markers", showlegend=False, hoverinfo="skip"))

        # ⑤ away player dots (red) — hidden when show_away=False
        if show_away:
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
        else:
            out.append(go.Scatter(x=[], y=[], mode="markers", showlegend=False, hoverinfo="skip"))

        # ⑥ ball dot (semi-transparent yellow)
        bx  = row.get("Ball_X",    np.nan)
        by  = row.get("Ball_Y",    np.nan)
        bxt = float(row.get("Ball_xT",   0) or 0)
        bgd = int(row.get("Ball_GridID", 0) or 0)
        out.append(go.Scatter(
            x=[float(bx) * PITCH_W] if pd.notna(bx) else [None],
            y=[float(by) * PITCH_H] if pd.notna(by) else [None],
            mode="markers",
            marker=dict(size=14, color="rgba(255,215,0,0.55)", line=dict(color="#aaa", width=1.5)),
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
            "showactive": False,
            "bgcolor": "#1e2a1e",
            "bordercolor": "rgba(255,255,255,0.20)",
            "font": {"color": "white", "size": 13},
            "x": 0.0, "y": -0.13,
            "xanchor": "left", "yanchor": "top",
            "direction": "right",
            "buttons": [
                {"label": "▶", "method": "animate",
                 "args": [None, {"frame": {"duration": int(1000 / fps), "redraw": True},
                                 **btn_common}]},
                {"label": "⏸", "method": "animate",
                 "args": [[None], {"frame": {"duration": 0, "redraw": False},
                                   "mode": "immediate", "transition": {"duration": 0}}]},
                {"label": "×0.5", "method": "animate",
                 "args": [None, {"frame": {"duration": int(2000 / fps), "redraw": True},
                                 **btn_common}]},
                {"label": "×1", "method": "animate",
                 "args": [None, {"frame": {"duration": int(1000 / fps), "redraw": True},
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
    time_offset: float = 0.0,
) -> go.Figure:
    fig = go.Figure()

    # Use Match_Time_sec + user offset when available, else relative Time
    if "Match_Time_sec" in df.columns and (time_offset != 0.0 or df["Match_Time_sec"].max() > 60):
        times    = (df["Match_Time_sec"] + time_offset).values
        x_label  = "試合時刻 (秒)"
        tick_fmt = lambda v: _fmt_mmss(v)   # noqa: E731  # for annotation only
    else:
        times   = df["Time"].values
        x_label = "Time (sec)"
        tick_fmt = lambda v: f"{v:.1f}s"   # noqa: E731

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
            title=x_label, color="#b0c8e0",
            range=[float(times[0]) if len(times) else 0, n_sec],
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

    # ── session state defaults ────────────────────────────────────────────────
    if "import_mode" not in st.session_state:
        st.session_state["import_mode"] = False
    if "import_step" not in st.session_state:
        st.session_state["import_step"] = 1

    # ── sidebar ───────────────────────────────────────────────────────────────
    with st.sidebar:
        st.markdown("## ⚽ Pitch Log")
        st.markdown("**Phase 4 Extended: 22-Player Visualization**")
        st.divider()

        # ── シーン取り込みウィザード toggle ───────────────────────────────
        _in_wizard = st.session_state["import_mode"]
        if _in_wizard:
            if st.button("← ビューアに戻る", use_container_width=True):
                st.session_state["import_mode"] = False
                st.rerun()
        else:
            if st.button("📥 新しいシーンを取り込む", type="primary",
                         use_container_width=True):
                st.session_state["import_mode"] = True
                st.session_state["import_step"] = 1
                st.rerun()
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
        match_info_path = st.text_input(
            "試合情報 JSON（任意）", "match_info.json",
            help="xt_pipeline_22.py 実行時に自動生成される match_info.json"
        )
        time_offset = st.number_input(
            "試合時刻オフセット（秒）",
            value=0.0, step=60.0, format="%.0f",
            help=(
                "ウィンドウ開始が試合の何秒目かを入力すると\n"
                "タイムラインが実際の試合時刻で表示されます。\n"
                "例: 前半45分以降 = 2700、後半74分 = 4440"
            ),
        )
        st.divider()

        # ── データ取り込み ─────────────────────────────────────────────────
        st.markdown("### 📥 新シーン取り込み")
        with st.expander("生トラッキングデータから変換", expanded=False):
            st.caption(
                "生のトラッキングCSVを読み込んでシーンCSVに変換します。\n"
                "ファイルアップロードまたはURLで指定できます。"
            )
            _src_method = st.radio(
                "データソース",
                ["💾 ファイルアップロード", "🌐 URL指定"],
                horizontal=True,
                key="ingest_method",
            )

            _raw_bytes: bytes | None = None

            if _src_method == "💾 ファイルアップロード":
                _uploaded = st.file_uploader(
                    "生トラッキングCSV",
                    type=["csv"],
                    help=(
                        "必要なカラム:\n"
                        "frame, time_sec, ball_x, ball_y, is_goal_frame,\n"
                        "Home_1_x, Home_1_y … Away_11_x, Away_11_y\n"
                        "（座標は 0〜1 に正規化）"
                    ),
                    key="ingest_upload",
                )
                if _uploaded is not None:
                    _raw_bytes = _uploaded.getvalue()
                    st.caption(f"✅ **{_uploaded.name}**  ({len(_raw_bytes)//1024} KB)")
                    # Clear old URL-downloaded bytes when new file is uploaded
                    st.session_state.pop("ingest_raw_bytes", None)

            else:  # URL指定
                _data_url = st.text_input(
                    "CSV の URL",
                    placeholder="https://example.com/tracking_data.csv",
                    key="ingest_url",
                )
                if st.button("⬇️ ダウンロード", key="ingest_dl_btn", use_container_width=True):
                    if _data_url:
                        try:
                            import urllib.request as _ur
                            with st.spinner("ダウンロード中…"):
                                req = _ur.Request(
                                    _data_url,
                                    headers={"User-Agent": "PitchLog/1.0"},
                                )
                                with _ur.urlopen(req, timeout=30) as _resp:
                                    _dl = _resp.read()
                            st.session_state["ingest_raw_bytes"] = _dl
                            st.success(f"ダウンロード完了  ({len(_dl)//1024} KB)")
                        except Exception as _e:
                            st.error(f"ダウンロードエラー: {_e}")
                    else:
                        st.warning("URLを入力してください")

                if "ingest_raw_bytes" in st.session_state:
                    _raw_bytes = st.session_state["ingest_raw_bytes"]
                    st.caption(f"✅ ダウンロード済  ({len(_raw_bytes)//1024} KB)")

            st.divider()
            # ── 試合メタ情報 ──────────────────────────────────────────────
            _new_match_name  = st.text_input(
                "試合名", placeholder="Brisbane Roar 0-1 Perth Glory",
                key="ingest_mname",
            )
            _new_match_round = st.text_input(
                "ラウンド", placeholder="Round 09 | A-League 2024-25",
                key="ingest_mround",
            )
            _window_sec_new = st.slider(
                "切り出し長（秒）", 5, 60, 30, step=5, key="ingest_window",
                help="ゴールフレームから何秒前まで切り出すか",
            )
            _goal_sec_override = st.number_input(
                "ゴール時刻を手動指定（秒）",
                value=0.0, min_value=0.0, step=1.0, format="%.1f",
                key="ingest_goal_sec",
                help=(
                    "0のままなら is_goal_frame 列 or 末尾フレームを自動検出。\n"
                    "例: ゴールが30.0秒目なら 30"
                ),
            )

            st.divider()

            # ── 変換実行ボタン ────────────────────────────────────────────
            _btn_disabled = (_raw_bytes is None)
            if st.button(
                "変換して読み込む 🔄",
                type="primary",
                use_container_width=True,
                disabled=_btn_disabled,
                key="ingest_convert_btn",
            ):
                try:
                    import io as _io
                    import importlib.util as _ilu

                    # Load raw CSV
                    _raw_df = pd.read_csv(_io.BytesIO(_raw_bytes))
                    st.info(f"読み込み完了: **{len(_raw_df)} フレーム**  /  {len(_raw_df.columns)} カラム")

                    # Load pipeline module dynamically
                    _pipe_candidates = [
                        Path(__file__).parent / "xt_pipeline_22.py",
                        Path(scene_path).parent / "xt_pipeline_22.py",
                    ]
                    _pipe_path = next((p for p in _pipe_candidates if p.exists()), None)
                    if _pipe_path is None:
                        st.error("xt_pipeline_22.py が見つかりません。アプリと同じフォルダに置いてください。")
                        st.stop()

                    _spec = _ilu.spec_from_file_location("_pipe", _pipe_path)
                    _pipe = _ilu.module_from_spec(_spec)
                    _spec.loader.exec_module(_pipe)

                    with st.spinner("xT計算・LBP検出中…"):
                        # Detect FPS
                        _dt_ser = pd.to_numeric(
                            _raw_df["time_sec"] if "time_sec" in _raw_df.columns else pd.Series([0.1]),
                            errors="coerce",
                        ).diff().dropna()
                        _raw_fps_v = int(round(1.0 / _dt_ser.median())) if len(_dt_ser) > 0 and _dt_ser.median() > 0 else 10

                        # Find goal frame
                        if _goal_sec_override > 0:
                            _goal_f = min(int(_goal_sec_override * _raw_fps_v), len(_raw_df) - 1)
                        elif "is_goal_frame" in _raw_df.columns and (_raw_df["is_goal_frame"] == 1).any():
                            _goal_f = int(_raw_df.index[_raw_df["is_goal_frame"] == 1].tolist()[-1])
                        else:
                            _goal_f = len(_raw_df) - 1

                        # Window slice
                        _win_n    = _window_sec_new * _raw_fps_v
                        _start_f  = max(0, _goal_f - _win_n + 1)
                        _xt_arr   = _pipe.load_xt_map(xt_path)
                        _enr      = _pipe.assign_grid_and_xt_22(_raw_df, _xt_arr)
                        _win      = _enr.iloc[int(_start_f): _goal_f + 1].reset_index(drop=True)
                        _ws       = float(_raw_df.iloc[int(_start_f)]["time_sec"]) if "time_sec" in _raw_df.columns else 0.0
                        _we       = float(_raw_df.iloc[_goal_f]["time_sec"])        if "time_sec" in _raw_df.columns else _ws + _window_sec_new
                        _res      = _pipe.reformat_to_22player_schema(_win, _raw_fps_v, _ws)
                        _res      = _pipe.add_zone_and_lbp_columns(_res, _raw_fps_v)
                        _res.to_csv(scene_path, index=False)

                        # Write match_info.json
                        _meta = {
                            "match_name":       _new_match_name  or "Unknown Match",
                            "match_round":      _new_match_round or "",
                            "goal_frame_raw":   _goal_f,
                            "goal_time_sec":    round(_we, 3),
                            "window_start_sec": round(_ws, 3),
                            "window_end_sec":   round(_we, 3),
                            "window_sec":       _window_sec_new,
                            "window_frames":    len(_win),
                            "fps":              _raw_fps_v,
                            "output_csv":       scene_path,
                        }
                        with open(match_info_path, "w", encoding="utf-8") as _mf:
                            json.dump(_meta, _mf, indent=2, ensure_ascii=False)

                    st.success(
                        f"✅ 変換完了！  "
                        f"{len(_win)} フレーム（{_window_sec_new}秒 / {_raw_fps_v} fps）"
                    )
                    st.session_state.pop("ingest_raw_bytes", None)
                    st.rerun()

                except Exception as _e:
                    import traceback as _tb
                    st.error(f"変換エラー: {_e}")
                    st.code(_tb.format_exc(), language="python")

            if _btn_disabled:
                st.caption("⬆️ CSVを読み込むと変換ボタンが有効になります")

        st.divider()

        st.markdown("### 表示オプション")
        show_xt      = st.toggle("xTヒートマップ",   value=True)
        xt_side = st.radio(
            "xTマップ表示チーム",
            ["Home", "Away", "両方"],
            index=2,
            horizontal=True,
            help="Home：ホーム攻撃方向(赤系) / Away：アウェイ攻撃方向(青系) / 両方：重ね表示",
            disabled=not show_xt,
        )
        show_causal  = st.toggle("貢献度パネル",     value=True)
        trail_frames = st.slider("軌跡フレーム数", 0, 100, 20, step=5)
        st.markdown("**選手表示**")
        _pcol1, _pcol2 = st.columns(2)
        show_home = _pcol1.checkbox("🔵 Home", value=True)
        show_away = _pcol2.checkbox("🔴 Away", value=True)
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
            "▶ : 再生  ⏸ : 一時停止\n"
            "×0.5 / ×1 / ×2 / ×4 : 速度\n"
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

    # ── match info load ───────────────────────────────────────────────────────
    match_info = load_match_info(match_info_path)

    # ── window re-cut section (sidebar) ───────────────────────────────────────
    with st.sidebar:
        st.divider()
        st.markdown("### 🎬 ウィンドウ再切り出し")

        raw_src = st.text_input(
            "ソースCSVパス",
            value="Sample_TrackingData_22.csv",
            help="xt_pipeline_22.py が読む元のトラッキングCSV",
        )
        raw_exists = Path(raw_src).exists()

        if raw_exists:
            @st.cache_data(show_spinner=False)
            def _load_raw(path: str, _mt: float) -> pd.DataFrame:
                return pd.read_csv(path)

            _raw_mt  = Path(raw_src).stat().st_mtime
            raw_df   = _load_raw(raw_src, _raw_mt)
            raw_fps_v = int(round(1.0 / pd.to_numeric(raw_df.get("time_sec", pd.Series([0.1])), errors="coerce").diff().dropna().median())) if len(raw_df) > 1 else 10
            n_raw    = len(raw_df)
            raw_total_sec = n_raw / raw_fps_v

            st.caption(f"検出: **{n_raw}** フレーム / **{raw_total_sec:.0f}** 秒 @ {raw_fps_v} fps")

            # Goal frame index
            if "is_goal_frame" in raw_df.columns:
                default_end = int(raw_df.index[raw_df["is_goal_frame"] == 1].tolist()[-1]) if (raw_df["is_goal_frame"] == 1).any() else n_raw - 1
            else:
                default_end = n_raw - 1

            new_end_frame = st.slider(
                "ウィンドウ終端 (フレーム番号)",
                min_value=0, max_value=n_raw - 1,
                value=default_end,
                help="この番号のフレームを「終端」として window_sec 分遡って切り出します",
            )
            new_window_sec = st.slider("ウィンドウ長（秒）", 5, 60, 30, step=5)

            # Preview
            new_start_frame = max(0, new_end_frame - new_window_sec * raw_fps_v + 1)
            if "time_sec" in raw_df.columns:
                t_start = float(raw_df.iloc[new_start_frame]["time_sec"]) + time_offset
                t_end   = float(raw_df.iloc[new_end_frame]["time_sec"])   + time_offset
                st.caption(f"切り出し範囲: **{_fmt_mmss(t_start)}** 〜 **{_fmt_mmss(t_end)}**")

            if st.button("このウィンドウで再解析 🔄", type="primary", use_container_width=True):
                try:
                    import importlib.util as _ilu
                    _spec = _ilu.spec_from_file_location("_pipe", Path(raw_src).parent / "xt_pipeline_22.py")
                    if _spec is None:
                        # fallback: same dir as app
                        _spec = _ilu.spec_from_file_location("_pipe", Path(__file__).parent / "xt_pipeline_22.py")
                    _pipe = _ilu.module_from_spec(_spec)
                    _spec.loader.exec_module(_pipe)

                    with st.spinner("xT計算中…"):
                        _xt   = _pipe.load_xt_map(xt_path)
                        _enr  = _pipe.assign_grid_and_xt_22(raw_df, _xt)
                        _win  = _enr.iloc[new_start_frame : new_end_frame + 1].reset_index(drop=True)
                        _ws   = float(raw_df.iloc[new_start_frame]["time_sec"]) if "time_sec" in raw_df.columns else 0.0
                        _res  = _pipe.reformat_to_22player_schema(_win, raw_fps_v, _ws)
                        _res  = _pipe.add_zone_and_lbp_columns(_res, raw_fps_v)
                        _res.to_csv(scene_path, index=False)

                        # Update match_info.json
                        _meta = match_info.copy() if match_info else {}
                        _meta.update({
                            "window_start_sec": round(_ws, 3),
                            "window_end_sec":   round(float(raw_df.iloc[new_end_frame]["time_sec"]) if "time_sec" in raw_df.columns else _ws + new_window_sec, 3),
                            "window_sec":       new_window_sec,
                            "window_frames":    len(_win),
                        })
                        with open(match_info_path, "w", encoding="utf-8") as _mf:
                            json.dump(_meta, _mf, indent=2, ensure_ascii=False)

                    st.success(f"完了: {len(_win)}フレーム ({new_window_sec}秒)")
                    st.rerun()
                except Exception as _e:
                    st.error(f"再解析エラー: {_e}")
        else:
            st.caption(f"`{raw_src}` が見つかりません。")
            st.caption("ローカル環境でソースCSVを指定すると再切り出しができます。")

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

    # ── wizard mode: show full-page wizard instead of viewer ─────────────────
    if st.session_state.get("import_mode", False):
        st.markdown(
            "<h2 style='margin-bottom:0'>📥 シーン取り込みウィザード</h2>"
            "<p style='color:#8b949e;margin-top:2px;font-size:.85rem'>"
            "生トラッキングCSVを読み込み、シーンを指定して変換します</p>",
            unsafe_allow_html=True,
        )
        render_import_wizard(xt_path, scene_path, match_info_path)
        return   # skip the viewer entirely while in wizard mode

    # ── header ────────────────────────────────────────────────────────────────
    st.markdown(
        "<h2 style='margin-bottom:0'>⚽ Pitch Log — 22-Player Scene Viewer</h2>"
        "<p style='color:#8b949e;margin-top:2px;font-size:.85rem'>"
        "Phase 4 Extended | Home 11 + Away 11 + Ball | xT × Causal Analysis</p>",
        unsafe_allow_html=True,
    )

    # ── scene info banner ─────────────────────────────────────────────────────
    _ws  = match_info.get("window_start_sec", 0.0) + time_offset
    _we  = match_info.get("window_end_sec",   match_info.get("window_start_sec", 0.0) + n_frames / fps) + time_offset
    _mn  = match_info.get("match_name",  "")
    _mr  = match_info.get("match_round", "")
    _wf  = match_info.get("window_frames", n_frames)

    if _mn:
        _t_range = f"{_fmt_mmss(_ws)} 〜 {_fmt_mmss(_we)}" if time_offset != 0 or _ws > 60 else f"{_ws:.1f}s 〜 {_we:.1f}s（試合時刻オフセット未設定）"
        st.info(
            f"📍 **{_mn}** | {_mr}  \n"
            f"現在表示: **{_t_range}** — {_wf} フレーム @ {fps:.0f} fps  \n"
            f"{'⚠️ サイドバーの「試合時刻オフセット」を設定すると実際の試合時刻で表示されます' if time_offset == 0 and _ws <= 60 else ''}",
        )
    else:
        _t_rel_end = n_frames / fps
        st.info(
            f"📍 **表示中**: {scene_path}  \n"
            f"フレーム 1〜{n_frames} | 相対時刻 0s〜{_t_rel_end:.1f}s | {fps:.0f} fps  \n"
            f"試合情報を表示するには `match_info.json` をパイプラインで生成してください。"
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
            fig_pitch = build_zone_animated_fig(
                xt_path, scene_path, show_xt, trail_frames, fps,
                show_home=show_home, show_away=show_away, xt_side=xt_side,
            )
        else:
            st.markdown("#### ピッチビュー  🔵 Home  🔴 Away  🟡 Ball")
            st.caption("▶/⏸/×0.5/×1/×2/×4/⏮ で操作 | スライダーでコマ送り | ホバーで詳細表示")
            fig_pitch = build_animated_fig(
                xt_path, scene_path, show_xt, trail_frames, fps,
                show_home=show_home, show_away=show_away, xt_side=xt_side,
            )
        st.plotly_chart(fig_pitch, use_container_width=True,
                        config={"displayModeBar": False})

    with col_r:
        if zone_mode:
            st.markdown("#### ラインブレイクパス検知アラート")
            lbp_df = _compute_lbp_inapp(df, fps, h_nums, a_nums)
            render_lbp_alerts(lbp_df)
            st.divider()

        st.markdown("#### xT タイムライン（30秒全体）")
        fig_line = build_timeline_fig(df, sel_home, sel_away, h_nums, a_nums, time_offset)
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

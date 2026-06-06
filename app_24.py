"""
app_24.py
=========
Pitch Log v24 — 試合全体ビュー（Match Momentum & Key Moments）

90分（前後半）を1枚で俯瞰する。
  - インタラクティブ モメンタムチャート（5分ローリング + 累積）
  - キーモーメント自動抽出：⚽ゴール / 🔵チャンス(Homeシュート) / 🔴ピンチ(Awayシュート)
  - キーモーメント一覧テーブル（フィルタ可）

入力: match_phases_summary.csv  (build_match_phases.py が生成・リポジトリ同梱)

Run
---
  streamlit run app_24.py
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Pitch Log — 試合全体", page_icon="⚽",
                   layout="wide", initial_sidebar_state="expanded")

# ── colors ──
C_HOME = "#3b9eff"
C_AWAY = "#ff5555"
C_GOAL = "#FFD700"
BG     = "#0e1825"
PANEL  = "#13202f"
HALF_LEN = 45.0

st.markdown("""
<style>
.stApp, body { background:#0e1825 !important; color:#dde8f4 !important; }
h1,h2,h3,h4 { color:#fff !important; }
section[data-testid="stSidebar"] { background:#13202f !important; }
div[data-testid="stMetric"] { background:#1a2e42 !important; border:1px solid #234060 !important;
  border-radius:10px !important; padding:12px 16px !important; }
div[data-testid="stMetricValue"] { color:#5ec4ff !important; }
div[data-testid="stMetricLabel"] p { color:#7aaac8 !important; font-size:.72rem !important;
  text-transform:uppercase; letter-spacing:.06em; }
</style>
""", unsafe_allow_html=True)


@st.cache_data(show_spinner="フェーズデータ読み込み中…")
def load_phases(path: str) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p)


def rolling_and_cumulative(df: pd.DataFrame, win: float = 5.0,
                           positive_only: bool = False, step: float = 0.25):
    grid = np.arange(0, float(df["t_min"].max()) + 1, step)
    gain = df["xt_gain"].values if "xt_gain" in df else np.abs(df["signed"].values)
    sign = np.sign(df["signed"].values)            # Home=+ / Away=-
    if positive_only:
        # 攻撃側が稼いだ正のΔxTだけを各チームに加点（gross 脅威創出）
        contrib = np.clip(gain, 0, None) * sign
    else:
        contrib = df["signed"].values              # net（正負あり）
    t = df["t_min"].values
    roll = np.array([contrib[(t > g - win) & (t <= g)].sum() for g in grid])
    cum  = np.array([contrib[t <= g].sum() for g in grid])
    return grid, roll, cum


def build_momentum_fig(df: pd.DataFrame, win: float = 5.0,
                       positive_only: bool = False) -> go.Figure:
    grid, roll, cum = rolling_and_cumulative(df, win=win, positive_only=positive_only)

    fig = go.Figure()
    # rolling (filled)
    fig.add_trace(go.Scatter(x=grid, y=np.clip(roll, 0, None), mode="lines",
                  line=dict(color=C_HOME, width=0.5), fill="tozeroy",
                  fillcolor="rgba(59,158,255,0.45)", name="Home優勢", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=grid, y=np.clip(roll, None, 0), mode="lines",
                  line=dict(color=C_AWAY, width=0.5), fill="tozeroy",
                  fillcolor="rgba(255,85,85,0.45)", name="Away優勢", hoverinfo="skip"))
    # cumulative (scaled to overlay, on secondary look via thin line)
    cmax = max(1.0, np.abs(cum).max())
    rmax = max(1.0, np.abs(roll).max())
    cum_scaled = cum / cmax * rmax
    fig.add_trace(go.Scatter(x=grid, y=cum_scaled, mode="lines",
                  line=dict(color="white", width=1.6, dash="dot"),
                  name="累積(正規化)",
                  hovertemplate="累積 net xT %{customdata:+.3f}<extra></extra>",
                  customdata=cum))

    # key moments
    sym = {"chance": ("circle", C_HOME, "🔵チャンス"),
           "pinch":  ("circle", C_AWAY, "🔴ピンチ"),
           "goal_home": ("star", C_GOAL, "⚽ゴール(Home)"),
           "goal_away": ("star", C_GOAL, "⚽ゴール(Away)")}
    for key, (mk, col, lbl) in sym.items():
        sub = df[df["moment"] == key]
        if sub.empty:
            continue
        ymax = max(np.abs(roll).max(), 1)
        yv = np.where(sub["team"].values == "Home", ymax * 0.9, -ymax * 0.9)
        fig.add_trace(go.Scatter(
            x=sub["t_min"], y=yv, mode="markers", name=lbl,
            marker=dict(symbol=mk, size=16 if "goal" in key else 10,
                        color=col, line=dict(color="white", width=1)),
            customdata=np.stack([sub["team_name"], sub["phase_type"],
                                 sub["third_end"], sub["t_min"]], axis=-1),
            hovertemplate=(f"<b>{lbl}</b><br>"
                           "%{customdata[0]} | %{customdata[1]}<br>"
                           "終了ゾーン: %{customdata[2]}<br>"
                           "時刻: %{customdata[3]:.1f}分<extra></extra>"),
        ))

    fig.add_vline(x=HALF_LEN, line=dict(color="#ffd700", width=1.2, dash="dash"))
    fig.add_hline(y=0, line=dict(color="white", width=0.8))
    fig.add_annotation(x=HALF_LEN, y=1, yref="paper", text="HT", showarrow=False,
                       font=dict(color="#ffd700", size=11), yshift=8)

    fig.update_layout(
        plot_bgcolor=PANEL, paper_bgcolor=BG,
        height=460, margin=dict(l=10, r=10, t=30, b=40),
        xaxis=dict(title="試合時間（分）", color="#b0c8e0",
                   gridcolor="rgba(255,255,255,0.06)", zeroline=False),
        yaxis=dict(title=f"モメンタム = xT added（{win:.0f}分窓 / 点線=累積）", color="#b0c8e0",
                   gridcolor="rgba(255,255,255,0.06)", zeroline=False),
        legend=dict(orientation="h", y=-0.18, font=dict(color="white", size=10),
                    bgcolor="rgba(0,0,0,0.3)"),
        hovermode="closest",
    )
    return fig


def main():
    with st.sidebar:
        st.markdown("## ⚽ Pitch Log — 試合全体")
        st.markdown("**v24 | Match Momentum & Key Moments**")
        st.divider()
        path = st.text_input("フェーズ サマリーCSV", "match_phases_summary.csv")
        st.divider()
        st.markdown("### モメンタム設定")
        mode = st.radio(
            "ΔxT の数え方",
            ["net（正負あり）", "正の増加だけ"],
            index=0,
            help="net=territoryの押し引き / 正のみ=攻撃の脅威創出（チャンス志向）",
        )
        positive_only = mode == "正の増加だけ"
        win = st.slider("ローリング窓（分）", 1, 15, 5,
                        help="短い=瞬間の勢いの振れに敏感 / 長い=持続的な支配が滑らかに")
        st.divider()
        st.markdown("### キーモーメント フィルタ")
        show_goal   = st.checkbox("⚽ ゴール", value=True)
        show_chance = st.checkbox("🔵 チャンス（Homeシュート）", value=True)
        show_pinch  = st.checkbox("🔴 ピンチ（Awayシュート）", value=True)
        st.divider()
        st.caption("Home = Brisbane（青） / Away = Perth（赤）\n\n"
                   "モメンタム = **xT added**（各フェーズの ΔxT = xT終了位置 − xT開始位置）。"
                   "xTは標準の Expected Threat 指標で、恣意的な重みを使わない一般的なモメンタムです。")

    df = load_phases(path)
    if df.empty:
        st.error(f"`{path}` が見つかりません。`python build_match_phases.py` で生成してください。")
        st.stop()

    st.markdown("<h2 style='margin-bottom:0'>⚽ 試合モメンタム — Brisbane 0-1 Perth</h2>"
                "<p style='color:#8b949e;margin-top:2px;font-size:.85rem'>"
                "Isuzu UTE A-League 2024-25 R09 | 90分を1枚で俯瞰</p>", unsafe_allow_html=True)

    # metrics
    n_chance = int((df["moment"] == "chance").sum())
    n_pinch  = int((df["moment"] == "pinch").sum())
    n_goal_h = int((df["moment"] == "goal_home").sum())
    n_goal_a = int((df["moment"] == "goal_away").sum())
    home_xt = df.loc[df["team"] == "Home", "xt_gain"].sum() if "xt_gain" in df else 0
    away_xt = df.loc[df["team"] == "Away", "xt_gain"].sum() if "xt_gain" in df else 0
    final_cum = df["signed"].sum()
    mc = st.columns(5)
    mc[0].metric("Home 総xT added", f"{home_xt:.2f}")
    mc[1].metric("Away 総xT added", f"{away_xt:.2f}")
    mc[2].metric("🔵チャンス / 🔴ピンチ", f"{n_chance} / {n_pinch}")
    mc[3].metric("⚽ スコア", f"{n_goal_h} - {n_goal_a}")
    mc[4].metric("累積 net xT", f"{final_cum:+.2f}",
                 "Home優勢" if final_cum > 0 else "Away優勢")
    st.divider()

    st.plotly_chart(build_momentum_fig(df, win=win, positive_only=positive_only),
                    use_container_width=True, config={"displayModeBar": False})

    # key moments table
    st.markdown("#### 🔑 キーモーメント一覧")
    wanted = []
    if show_goal:   wanted += ["goal_home", "goal_away"]
    if show_chance: wanted += ["chance"]
    if show_pinch:  wanted += ["pinch"]
    km = df[df["moment"].isin(wanted)].copy()
    label = {"goal_home": "⚽ゴール(Home)", "goal_away": "⚽ゴール(Away)",
             "chance": "🔵チャンス", "pinch": "🔴ピンチ"}
    km["種別"] = km["moment"].map(label)
    km["時刻"] = km.apply(lambda r: f"{'前半' if r['period']==1 else '後半'} "
                          f"{int(r['minute'])}:{int(r['second']):02d}", axis=1)
    view = km[["時刻", "種別", "team_name", "phase_type", "third_start", "third_end"]].rename(
        columns={"team_name": "チーム", "phase_type": "フェーズ種別",
                 "third_start": "開始ゾーン", "third_end": "終了ゾーン"})
    st.dataframe(view, use_container_width=True, hide_index=True, height=360)

    st.caption(f"表示: {len(view)} 件 / 全 {len(df)} フェーズ")


if __name__ == "__main__":
    main()

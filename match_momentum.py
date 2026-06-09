"""
match_momentum.py
=================
試合全体モメンタム（xT added）チャート + キーモーメント抽出 の共有モジュール。
app_22 / app_23 / app_24 から `render_momentum()` を呼んで同じ機能を埋め込む。

入力: match_phases_summary.csv  (build_match_phases.py が生成)
"""
from __future__ import annotations
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

C_HOME = "#3b9eff"
C_AWAY = "#ff5555"
C_GOAL = "#FFD700"
BG     = "#0e1825"
PANEL  = "#13202f"
HALF_LEN = 45.0


@st.cache_data(show_spinner="フェーズデータ読み込み中…")
def load_phases(path: str) -> pd.DataFrame:
    p = Path(path)
    return pd.read_csv(p) if p.exists() else pd.DataFrame()


def rolling_and_cumulative(df: pd.DataFrame, win: float = 5.0,
                           positive_only: bool = False, step: float = 0.25,
                           use_abs_xt: bool = False):
    grid = np.arange(0, float(df["t_min"].max()) + 1, step)
    if use_abs_xt and "xt_end" in df.columns:
        # 絶対位置脅威モード: xt_end × 符号（Home=+ / Away=-）
        sign = np.where(df["team"].values == "Home", 1.0, -1.0)
        base = df["xt_end"].values * sign
    else:
        base = df["signed"].values
    gain = np.abs(base)
    sign_v = np.sign(base)
    contrib = np.clip(gain, 0, None) * sign_v if positive_only else base
    t = df["t_min"].values
    roll = np.array([contrib[(t > g - win) & (t <= g)].sum() for g in grid])
    cum  = np.array([contrib[t <= g].sum() for g in grid])
    return grid, roll, cum


def build_momentum_fig(df: pd.DataFrame, win: float = 5.0,
                       positive_only: bool = False,
                       use_abs_xt: bool = False) -> go.Figure:
    grid, roll, cum = rolling_and_cumulative(df, win=win, positive_only=positive_only,
                                             use_abs_xt=use_abs_xt)
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=grid, y=np.clip(roll, 0, None), mode="lines",
                  line=dict(color=C_HOME, width=0.5), fill="tozeroy",
                  fillcolor="rgba(59,158,255,0.45)", name="Home優勢", hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=grid, y=np.clip(roll, None, 0), mode="lines",
                  line=dict(color=C_AWAY, width=0.5), fill="tozeroy",
                  fillcolor="rgba(255,85,85,0.45)", name="Away優勢", hoverinfo="skip"))
    cmax = max(1e-9, np.abs(cum).max()); rmax = max(1e-9, np.abs(roll).max())
    fig.add_trace(go.Scatter(x=grid, y=cum / cmax * rmax, mode="lines",
                  line=dict(color="white", width=1.6, dash="dot"), name="累積(正規化)",
                  hovertemplate="累積 net xT %{customdata:+.3f}<extra></extra>", customdata=cum))

    sym = {"chance": ("circle", C_HOME, "🔵チャンス"),
           "pinch":  ("circle", C_AWAY, "🔴ピンチ"),
           "goal_home": ("star", C_GOAL, "⚽ゴール(Home)"),
           "goal_away": ("star", C_GOAL, "⚽ゴール(Away)")}
    for key, (mk, col, lbl) in sym.items():
        sub = df[df["moment"] == key]
        if sub.empty:
            continue
        ymax = max(np.abs(roll).max(), 1e-9)
        yv = np.where(sub["team"].values == "Home", ymax * 0.9, -ymax * 0.9)
        fig.add_trace(go.Scatter(
            x=sub["t_min"], y=yv, mode="markers", name=lbl,
            marker=dict(symbol=mk, size=16 if "goal" in key else 10,
                        color=col, line=dict(color="white", width=1)),
            customdata=np.stack([sub["team_name"], sub["phase_type"],
                                 sub["third_end"], sub["t_min"]], axis=-1),
            hovertemplate=(f"<b>{lbl}</b><br>%{{customdata[0]}} | %{{customdata[1]}}<br>"
                           "終了ゾーン: %{customdata[2]}<br>時刻: %{customdata[3]:.1f}分<extra></extra>"),
        ))
    fig.add_vline(x=HALF_LEN, line=dict(color="#ffd700", width=1.2, dash="dash"))
    fig.add_hline(y=0, line=dict(color="white", width=0.8))
    fig.add_annotation(x=HALF_LEN, y=1, yref="paper", text="HT", showarrow=False,
                       font=dict(color="#ffd700", size=11), yshift=8)
    fig.update_layout(
        plot_bgcolor=PANEL, paper_bgcolor=BG, height=440,
        margin=dict(l=10, r=10, t=20, b=40),
        xaxis=dict(title="試合時間（分）", color="#b0c8e0",
                   gridcolor="rgba(255,255,255,0.06)", zeroline=False),
        yaxis=dict(title=f"{'xT位置' if use_abs_xt else 'ΔxT'}（{win:.0f}分窓 / 点線=累積）", color="#b0c8e0",
                   gridcolor="rgba(255,255,255,0.06)", zeroline=False),
        legend=dict(orientation="h", y=-0.2, font=dict(color="white", size=10),
                    bgcolor="rgba(0,0,0,0.3)"),
        hovermode="closest")
    return fig


def render_momentum(path: str = "match_phases_summary.csv", key_prefix: str = "mom"):
    """モメンタムUI一式（操作＋チャート＋区間抽出＋一覧）を描画する。"""
    df = load_phases(path)
    if df.empty:
        st.info(f"試合モメンタムを表示するには `{path}` が必要です。\n\n"
                "`python build_match_phases.py` で生成してください。")
        return

    # ── inline controls ──
    c1, c2, c3 = st.columns([2, 2, 3])
    metric_mode = c1.radio(
        "モメンタム指標",
        ["ΔxT（移動量）", "xT位置（絶対脅威）"],
        horizontal=True, key=f"{key_prefix}_metric",
        help="ΔxT=どれだけ危険ゾーンへ移動したか / xT位置=どれだけ危険な場所にいるか（ゴール前の膠着を正しく評価）")
    use_abs_xt = metric_mode == "xT位置（絶対脅威）"
    mode = c2.radio("符号の扱い", ["net（正負あり）", "正の増加だけ"],
                    horizontal=True, key=f"{key_prefix}_mode",
                    help="net=territoryの押し引き / 正のみ=攻撃の脅威創出")
    positive_only = mode == "正の増加だけ"
    win = c3.slider("ローリング窓（分）", 1, 15, 5, key=f"{key_prefix}_win",
                    help="短い=瞬間の振れに敏感 / 長い=持続的支配が滑らか")
    kc1, kc2, kc3, kc4 = st.columns(4)
    kc1.caption("キーモーメント表示")
    show_goal   = kc2.checkbox("⚽", value=True, key=f"{key_prefix}_g")
    show_chance = kc3.checkbox("🔵", value=True, key=f"{key_prefix}_c")
    show_pinch  = kc4.checkbox("🔴", value=True, key=f"{key_prefix}_p")

    # ── metrics ──
    home_xt = df.loc[df["team"] == "Home", "xt_gain"].sum() if "xt_gain" in df else 0
    away_xt = df.loc[df["team"] == "Away", "xt_gain"].sum() if "xt_gain" in df else 0
    n_chance = int((df["moment"] == "chance").sum())
    n_pinch  = int((df["moment"] == "pinch").sum())
    n_gh = int((df["moment"] == "goal_home").sum())
    n_ga = int((df["moment"] == "goal_away").sum())
    mc = st.columns(5)
    mc[0].metric("Home 総xT added", f"{home_xt:.2f}")
    mc[1].metric("Away 総xT added", f"{away_xt:.2f}")
    mc[2].metric("🔵チャンス / 🔴ピンチ", f"{n_chance} / {n_pinch}")
    mc[3].metric("⚽ スコア", f"{n_gh} - {n_ga}")
    mc[4].metric("累積 net xT", f"{df['signed'].sum():+.2f}",
                 "Home優勢" if df["signed"].sum() > 0 else "Away優勢")

    st.caption("💡 ドラッグで拡大ズーム ／ モードバーの ⬚ ボックス選択 で区間抽出 ／ "
               "ダブルクリック（🏠）でズーム解除")
    ev = st.plotly_chart(
        build_momentum_fig(df, win=win, positive_only=positive_only, use_abs_xt=use_abs_xt),
        use_container_width=True, key=f"{key_prefix}_chart",
        on_select="rerun", selection_mode=["box", "lasso"],
        config={"displayModeBar": True, "displaylogo": False,
                "modeBarButtonsToRemove": ["toImage", "autoScale2d"], "scrollZoom": False})

    # ── 区間抽出 ──
    try:
        sel = ev["selection"]["points"]
    except Exception:
        sel = []
    xs = [p["x"] for p in sel if isinstance(p.get("x"), (int, float))]
    if xs:
        t0, t1 = float(min(xs)), float(max(xs))
        sub = df[(df["t_min"] >= t0) & (df["t_min"] <= t1)].copy()
        st.markdown(f"#### 🔲 選択区間：{t0:.1f}〜{t1:.1f} 分（{len(sub)} フェーズ）")
        if not sub.empty:
            ec = st.columns(5)
            ec[0].metric("Home xT added", f"{sub.loc[sub.team=='Home','xt_gain'].sum():.3f}")
            ec[1].metric("Away xT added", f"{sub.loc[sub.team=='Away','xt_gain'].sum():.3f}")
            ec[2].metric("🔵チャンス", f"{int((sub.moment=='chance').sum())}")
            ec[3].metric("🔴ピンチ", f"{int((sub.moment=='pinch').sum())}")
            ec[4].metric("⚽ゴール", f"{int(sub.moment.str.startswith('goal').sum())}")
            st.download_button("📥 選択区間CSV", sub.to_csv(index=False).encode("utf-8"),
                               file_name=f"phases_{t0:.0f}-{t1:.0f}min.csv", mime="text/csv",
                               use_container_width=True, key=f"{key_prefix}_dl")
            with st.expander("選択区間のフェーズ明細", expanded=True):
                st.dataframe(sub, use_container_width=True, hide_index=True, height=280)

    # ── キーモーメント一覧 ──
    wanted = (["goal_home", "goal_away"] if show_goal else []) \
        + (["chance"] if show_chance else []) + (["pinch"] if show_pinch else [])
    km = df[df["moment"].isin(wanted)].copy()
    lab = {"goal_home": "⚽ゴール(Home)", "goal_away": "⚽ゴール(Away)",
           "chance": "🔵チャンス", "pinch": "🔴ピンチ"}
    km["種別"] = km["moment"].map(lab)
    km["時刻"] = km.apply(lambda r: f"{'前半' if r['period']==1 else '後半'} "
                          f"{int(r['minute'])}:{int(r['second']):02d}", axis=1)
    view = km[["時刻", "種別", "team_name", "phase_type", "third_start", "third_end"]].rename(
        columns={"team_name": "チーム", "phase_type": "フェーズ種別",
                 "third_start": "開始ゾーン", "third_end": "終了ゾーン"})
    with st.expander(f"🔑 キーモーメント一覧（{len(view)}件）", expanded=False):
        st.dataframe(view, use_container_width=True, hide_index=True, height=320)

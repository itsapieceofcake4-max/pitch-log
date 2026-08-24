"""
app_26.py
=========
Pitch Log v26 — PFF FC（FIFA World Cup 2022）シーンブラウザ

PFF のイベント／トラッキングから、解析したいシーンを **一覧から選び**、
俯瞰の 2D ピッチで動きを確認し、Export_GSA 形式（126列）で書き出す。

    ① シーンを選ぶ   … ゴール・決定機・シュート・ライン突破の一覧から
    ② 俯瞰で確認する … 2D ピッチ上で 22 人＋ボールを再生
    ③ 書き出す       … app_22 / app_23 がそのまま読める CSV

Run
---
    streamlit run app_26.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pff import JAPAN_GAMES, available_games, load_meta, load_roster, locate
from pff.convert import ball_coverage, build_export_gsa
from pff.enrich import enrich, feature_catalog
from pff.scenes import build_all, build_catalog
from rugby import theme
from rugby.theme import COLORS

# マルチページ（app_home.py）から呼ばれる場合、ページ設定は親が済ませている。
# 二重に呼ぶと例外になるので、単体起動のときだけ設定する。
try:
    st.set_page_config(
        page_title="Pitch Log v26 — PFF",
        page_icon="⚽",
        layout="wide",
        initial_sidebar_state="expanded",
    )
except st.errors.StreamlitAPIException:
    pass
theme.inject()

PITCH_L, PITCH_W = 105.0, 68.0
COLOR_HOME = COLORS["team_a"]
COLOR_AWAY = COLORS["team_b"]
COLOR_BALL = COLORS["ball"]

for _k, _v in {
    "scene": None,        # 選択中のシーン（dict）
    "export": None,       # (df, legend, info)
    "enriched": None,     # 全指標を付けた DataFrame
}.items():
    st.session_state.setdefault(_k, _v)


def _rgba(hex_color: str, a: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{a})"


@st.cache_data(show_spinner="シーン一覧を作成中…")
def _catalog(game_ids: tuple[int, ...]) -> pd.DataFrame:
    return build_all(list(game_ids))


@st.cache_data(show_spinner=False)
def _meta(game_id: int):
    m = load_meta(game_id)
    return {"home": m.home_name, "away": m.away_name, "fps": m.fps,
            "stadium": m.stadium, "video": m.video_url}


# ── 2D ピッチ描画 ─────────────────────────────────────────────────────────────

def _pitch_shapes() -> list[dict]:
    """サッカーピッチのライン。芝のストライプを敷いてから線を重ねる。"""
    shapes = []
    for x0, x1, light in theme.turf_stripes(0.0, PITCH_L):
        shapes.append(dict(type="rect", x0=x0, x1=x1, y0=0, y1=PITCH_W,
                           fillcolor=COLORS["turf_light"] if light else COLORS["turf_dark"],
                           line=dict(width=0), layer="below"))
    line = dict(color=_rgba(COLORS["pitch_line"], 0.72), width=1.4)
    cy = PITCH_W / 2
    segs = [
        [(0, 0), (PITCH_L, 0), (PITCH_L, PITCH_W), (0, PITCH_W), (0, 0)],
        [(PITCH_L / 2, 0), (PITCH_L / 2, PITCH_W)],
    ]
    for side, sgn in ((0.0, 1.0), (PITCH_L, -1.0)):
        segs.append([(side, cy - 20.16), (side + sgn * 16.5, cy - 20.16),
                     (side + sgn * 16.5, cy + 20.16), (side, cy + 20.16)])
        segs.append([(side, cy - 9.16), (side + sgn * 5.5, cy - 9.16),
                     (side + sgn * 5.5, cy + 9.16), (side, cy + 9.16)])
    for pts in segs:
        for a, b in zip(pts[:-1], pts[1:]):
            shapes.append(dict(type="line", x0=a[0], y0=a[1], x1=b[0], y1=b[1],
                               line=line, layer="below"))
    # センターサークル
    shapes.append(dict(type="circle", x0=PITCH_L / 2 - 9.15, x1=PITCH_L / 2 + 9.15,
                       y0=cy - 9.15, y1=cy + 9.15, line=line, layer="below"))
    return shapes


def pitch_figure(df: pd.DataFrame, legend: pd.DataFrame | None = None,
                 trail: int = 0) -> go.Figure:
    """Export_GSA の DataFrame を俯瞰 2D でアニメーション表示する。

    正規化 [0,1] をメートルへ戻して描く（105×68）。
    `legend` が無くても（CSV だけ渡された場合でも）スロット番号で描ける。
    """
    frames = df["Frame"].tolist()
    name_of = (
        {r["slot"]: (r["name"] or f'#{r["shirt"]}') for _, r in legend.iterrows()}
        if legend is not None and not legend.empty else {}
    )

    def slots(prefix: str) -> list[str]:
        return sorted({c.rsplit("_", 1)[0] for c in df.columns
                       if c.startswith(prefix) and c.endswith("_X")},
                      key=lambda s: int(s.split("_P")[1]))

    h_slots, a_slots = slots("Home_P"), slots("Away_P")

    def _trail_xy(i: int, sl_list: list[str]):
        """複数選手の軌跡を 1 本のトレースにまとめる（None で区切る）。

        選手ごとにトレースを分けると **フレームごとにトレース数が変わり**、
        Plotly のアニメーションは先頭から順に差し替えるだけなので、
        選手マーカーが軌跡の線に置き換わって消える。トレース構成は
        全フレームで固定にしなければならない。
        """
        if trail <= 0 or i == 0:
            return [], []
        lo = max(0, i - trail)
        seg = df.iloc[lo:i + 1]
        xs: list = []
        ys: list = []
        for sl in sl_list:
            xs.extend((seg[f"{sl}_X"] * PITCH_L).tolist())
            ys.extend((seg[f"{sl}_Y"] * PITCH_W).tolist())
            xs.append(None)
            ys.append(None)
        return xs, ys

    def traces(i: int):
        """1 フレーム分のトレース。**順番と本数は常に同じ**（下記の 5 本）。

        [0] Home の軌跡  [1] Away の軌跡  [2] 影  [3] Home  [4] Away  [5] ボール
        """
        row = df.iloc[i]
        out = []

        for sl_list, col in ((h_slots, COLOR_HOME), (a_slots, COLOR_AWAY)):
            tx, ty = _trail_xy(i, sl_list)
            out.append(go.Scatter(
                x=tx, y=ty, mode="lines",
                line=dict(color=_rgba(col, 0.35), width=1.5),
                hoverinfo="skip", showlegend=False,
            ))

        allx = [row[f"{s}_X"] * PITCH_L for s in h_slots + a_slots]
        ally = [row[f"{s}_Y"] * PITCH_W for s in h_slots + a_slots]
        out.append(go.Scatter(x=[v + 0.5 for v in allx], y=[v - 0.5 for v in ally],
                              mode="markers", marker=dict(size=17, color="rgba(0,0,0,0.42)"),
                              hoverinfo="skip", showlegend=False))

        for sl_list, color, label in ((h_slots, COLOR_HOME, "Home"),
                                      (a_slots, COLOR_AWAY, "Away")):
            xs = [row[f"{s}_X"] * PITCH_L for s in sl_list]
            ys = [row[f"{s}_Y"] * PITCH_W for s in sl_list]
            txt = [str(name_of.get(s, s)).split()[-1][:6] for s in sl_list]
            out.append(go.Scatter(
                x=xs, y=ys, mode="markers+text",
                marker=dict(size=16, color=color,
                            line=dict(color=_rgba(COLORS["bg"], 0.85), width=1.6)),
                text=[s.split("_P")[1] for s in sl_list],
                textposition="middle center",
                textfont=dict(size=8, color=COLORS["bg"]),
                name=label, customdata=txt,
                hovertemplate="%{customdata}<br>(%{x:.1f}, %{y:.1f}) m<extra></extra>",
            ))

        bx, by = row.get("Ball_X"), row.get("Ball_Y")
        out.append(go.Scatter(
            x=[bx * PITCH_L] if pd.notna(bx) else [],
            y=[by * PITCH_W] if pd.notna(by) else [],
            mode="markers",
            marker=dict(size=11, color=COLOR_BALL, symbol="diamond",
                        line=dict(color=_rgba(COLORS["bg"], 0.8), width=1.2)),
            name="ボール",
            hovertemplate="ボール (%{x:.1f}, %{y:.1f}) m<extra></extra>",
        ))
        return out

    fig = go.Figure(data=traces(0))
    # 全フレームだと重いので間引く（見た目は十分滑らか）
    step = max(len(frames) // 300, 1)
    keep = list(range(0, len(frames), step))
    fig.frames = [go.Frame(data=traces(i), name=str(frames[i])) for i in keep]

    fig.update_layout(**theme.plotly_layout(
        plot_bgcolor=COLORS["bg"], shapes=_pitch_shapes(),
        xaxis=dict(range=[-3, PITCH_L + 3], showgrid=False, zeroline=False,
                   visible=False, constrain="domain"),
        yaxis=dict(range=[-3, PITCH_W + 3], showgrid=False, zeroline=False,
                   visible=False, scaleanchor="x", scaleratio=1),
        height=560, margin=dict(l=8, r=8, t=46, b=8),
        updatemenus=[dict(
            type="buttons", showactive=False, x=0.01, y=1.12, xanchor="left",
            bgcolor=COLORS["surface_2"], bordercolor=COLORS["border"],
            font=dict(color=COLORS["text"], size=11),
            buttons=[
                dict(label="▶ 再生", method="animate",
                     args=[None, dict(frame=dict(duration=33, redraw=True),
                                      fromcurrent=True, mode="immediate")]),
                dict(label="⏸ 停止", method="animate",
                     args=[[None], dict(frame=dict(duration=0, redraw=False),
                                        mode="immediate")]),
            ])],
        sliders=[dict(
            active=0, y=0, x=0.06, len=0.92,
            currentvalue=dict(prefix="フレーム ",
                              font=dict(color=COLORS["text_muted"], size=11)),
            bgcolor=COLORS["border"], activebgcolor=COLORS["accent"],
            bordercolor=COLORS["border"], tickcolor=COLORS["border"],
            font=dict(color=COLORS["text_dim"], size=9),
            steps=[dict(method="animate", label=str(frames[i]),
                        args=[[str(frames[i])], dict(frame=dict(duration=0, redraw=True),
                                                     mode="immediate")])
                   for i in keep])],
        legend=dict(orientation="h", y=1.12, x=0.3, bgcolor="rgba(0,0,0,0)"),
    ))
    return fig


# ── サイドバー ────────────────────────────────────────────────────────────────

# PFF の実データは数GBあり、権利の都合でクラウドには置けない。
# データが無い環境（会社PC・クラウド）では、書き出した CSV を読むモードで動かす。
HAS_PFF = bool(available_games())

mode = st.sidebar.radio(
    "データ元",
    ["PFF データから抽出", "書き出した CSV を読む"],
    index=0 if HAS_PFF else 1,
    disabled=not HAS_PFF,
    help="PFF の実データがある環境（自宅PC）では抽出から、"
         "無い環境（会社PC・クラウド）では書き出した CSV を読み込みます。",
)
CSV_MODE = mode.startswith("書き出した") or not HAS_PFF

if not HAS_PFF:
    st.sidebar.warning(
        "PFF のデータセットが見つかりません。**CSV 読み込みモード**で動作します。"
    )

st.sidebar.divider()

if CSV_MODE:
    st.sidebar.markdown("**CSV を読み込む**")
    up_csv = st.sidebar.file_uploader(
        "書き出した CSV", type=["csv"],
        help="app_26 の③タブで書き出した `_enriched.csv`（425列）または "
             "Export_GSA（127列）。",
    )
    up_legend = st.sidebar.file_uploader(
        "スロット対応表（任意）", type=["csv"],
        help="P1〜P11 が誰かの対応表。無くても番号で表示できます。",
    )
    if up_csv is not None:
        try:
            _df = pd.read_csv(up_csv)
            _lg = pd.read_csv(up_legend) if up_legend is not None else None
            _info = {
                "game_id": "-", "home": "Home", "away": "Away",
                "center_time": 0.0, "fps": 1.0 / max(
                    pd.to_numeric(_df["Time"], errors="coerce").diff().median(), 1e-9),
                "frames": len(_df), "columns": _df.shape[1], "video_url": None,
            }
            base_cols = [c for c in _df.columns
                         if not c.startswith(("X1_", "X2_", "X3_", "X4_",
                                              "Y1_", "Y2_", "Y3_", "Z_", "Q_"))]
            st.session_state["export"] = (_df[base_cols], _lg, _info)
            st.session_state["enriched"] = _df if len(base_cols) < _df.shape[1] else None
            st.sidebar.success(f"読み込みました（{_df.shape[0]} 行 × {_df.shape[1]} 列）")
        except Exception as e:
            st.sidebar.error(f"読み込めませんでした: {e}")

    games, kinds = [], []
    window_sec, target_fps, smoothed = 30, "そのまま (29.97)", True
else:
    st.sidebar.markdown("**対象試合**")
    games = st.sidebar.multiselect(
        "試合", list(JAPAN_GAMES), default=list(JAPAN_GAMES),
        format_func=lambda g: f"{g} {JAPAN_GAMES[g]}",
    )
    kinds = st.sidebar.multiselect(
        "シーン種別",
        ["ゴール", "決定機", "シュート", "ハーフチャンス", "ライン突破", "危険な位置"],
        default=["ゴール", "決定機"],
    )
    window_sec = st.sidebar.slider("切り出す長さ（秒）", 10, 60, 30, 5,
                                   help="ゴール／基準時刻で終わる窓を取ります。")
    target_fps = st.sidebar.selectbox(
        "fps", ["そのまま (29.97)", "10 に間引く"], index=0,
        help="アプリは fps を自動判定するので通常は「そのまま」で構いません。"
             "既存 GSA 実績（10fps・300フレーム）に揃えたい場合のみ間引きます。",
    )
    smoothed = st.sidebar.checkbox("平滑化済み座標を使う", value=True)

st.sidebar.divider()
st.sidebar.caption(
    "品質: PFF は放送映像由来のため、ボールから離れた選手は推定値になります。"
    "20m 以内は実測率 83% 以上、30m 超は 45% 未満です。"
)

theme.header(
    "PFF FC · FIFA World Cup 2022  ·  シーンブラウザ",
    chips=[("DATA", HAS_PFF), ("SCENE", st.session_state["export"] is not None),
           ("INDICATORS", st.session_state.get("enriched") is not None)],
)

tab1, tab2, tab3 = st.tabs(
    ["① CSV を読み込む" if CSV_MODE else "① シーンを選ぶ", "② 俯瞰で確認", "③ 書き出す"]
)


# ── ① シーン選択 ─────────────────────────────────────────────────────────────

with tab1:
    if CSV_MODE:
        theme.section("書き出した CSV を読み込む",
                      "PFF の実データが無い環境ではこちら")
        st.markdown(
            "PFF のデータセットは数 GB あり、権利の都合でクラウドには置けません。"
            "**自宅 PC で書き出した CSV（1 シーンで 1MB 未満）** を"
            "サイドバーからアップロードすれば、俯瞰表示も指標の確認もできます。"
        )
        st.info(
            "**手順**\n\n"
            "1. PFF データのある PC で app_26 を開き、シーンを選ぶ\n"
            "2. ③タブで `_enriched.csv`（425列）をダウンロード\n"
            "3. そのファイルをこの画面のサイドバーからアップロード"
        )
        exp = st.session_state["export"]
        if exp is not None:
            df0, lg0, info0 = exp
            rich0 = st.session_state.get("enriched")
            m1, m2, m3 = st.columns(3)
            m1.metric("フレーム数", info0["frames"])
            m2.metric("列数", (rich0 if rich0 is not None else df0).shape[1])
            m3.metric("推定 fps", f"{info0['fps']:.2f}")
            st.success("読み込み済みです。②タブで俯瞰表示、③タブで書き出しができます。")
        else:
            st.caption("まだ読み込まれていません。サイドバーで CSV を選んでください。")

    elif not games:
        theme.section("解析候補シーン", "PFF アナリストの評価を元に抽出")
        st.info("サイドバーで試合を選んでください。")
    else:
        theme.section("解析候補シーン", "PFF アナリストの評価を元に抽出")
        cat = _catalog(tuple(sorted(games)))
        if cat.empty:
            st.warning("シーンが見つかりませんでした。")
        else:
            view = cat[cat["kind"].isin(kinds)] if kinds else cat
            st.caption(
                f"{len(view)} 件（全 {len(cat)} 件中）。"
                "行を選んでから下のボタンを押してください。"
            )
            show = view[["game_id", "kind", "detail", "clock", "period",
                         "team", "player", "event_time"]].reset_index(drop=True)
            sel = st.dataframe(
                show, width="stretch", hide_index=True, height=420,
                on_select="rerun", selection_mode="single-row",
                column_config={
                    "game_id": st.column_config.NumberColumn("試合", format="%d"),
                    "kind": "種別", "detail": "内容", "clock": "時計",
                    "period": "P", "team": "チーム", "player": "選手",
                    "event_time": st.column_config.NumberColumn("動画時刻(秒)", format="%.2f"),
                },
            )
            rows = sel.selection.rows if sel and sel.selection else []
            if rows:
                r = view.iloc[rows[0]]
                st.session_state["scene"] = r.to_dict()

            sc = st.session_state["scene"]
            if sc:
                st.divider()
                c1, c2 = st.columns([3, 2])
                with c1:
                    theme.section("選択中のシーン")
                    st.markdown(
                        f"**{sc['match']}** — {sc['kind']}（{sc['detail']}）  \n"
                        f"{sc['team']} / **{sc['player']}** — "
                        f"P{sc['period']} {sc['clock']}（動画 {sc['event_time']:.2f} 秒）"
                    )
                    if sc.get("video_url"):
                        st.markdown(f"[PFF 公式の該当映像を開く]({sc['video_url']})")

                    # 窓の長さごとにボールがどれだけ記録されているかを先に見せる。
                    # PFF はボールがデッドの間は追跡しないため、長い窓を機械的に
                    # 取ると大半がデッドタイムということが起こる。
                    with st.spinner("ボール捕捉率を確認中…"):
                        try:
                            cov = ball_coverage(int(sc["game_id"]),
                                                float(sc["event_time"]))
                        except Exception:
                            cov = None
                    if cov is not None and not cov.empty:
                        best = cov[cov["ボール捕捉率"] >= 0.95]
                        st.dataframe(
                            cov, width="stretch", hide_index=True,
                            column_config={"ボール捕捉率": st.column_config.ProgressColumn(
                                "ボール捕捉率", min_value=0.0, max_value=1.0,
                                format="%.0f%%")},
                        )
                        if not best.empty:
                            rec = int(best["窓(秒)"].max())
                            st.info(
                                f"**{rec} 秒**までならボールがほぼ全フレームで記録されています。"
                                "これより長い窓はデッドタイムを含みます。"
                            )
                with c2:
                    if st.button("このシーンを読み込む", type="primary", width="stretch"):
                        bar = st.progress(0.0, text="準備中…")
                        try:
                            res = build_export_gsa(
                                int(sc["game_id"]), float(sc["event_time"]),
                                window_sec=float(window_sec),
                                target_fps=10.0 if target_fps.startswith("10") else None,
                                smoothed=smoothed,
                                progress=lambda f, m: bar.progress(min(f, 1.0), text=m),
                            )
                        except Exception as e:
                            bar.empty()
                            st.error(f"読み込みに失敗しました: {e}")
                        else:
                            st.session_state["export"] = res
                            # 全指標はここで一緒に作ってしまう。③で毎回
                            # ボタンを押させるより、最初から入っているほうが
                            # 取りこぼしがない。
                            try:
                                st.session_state["enriched"] = enrich(
                                    res[0], res[2]["fps"],
                                    progress=lambda f, m: bar.progress(
                                        0.5 + 0.5 * min(f, 1.0), text=m),
                                )
                            except Exception as e:
                                st.session_state["enriched"] = None
                                st.warning(f"全指標の計算は失敗しました（座標のみ出力できます）: {e}")
                            bar.empty()
                            st.success("読み込みました。②タブで確認できます。")
                            st.rerun()


# ── ② 俯瞰確認 ───────────────────────────────────────────────────────────────

with tab2:
    exp = st.session_state["export"]
    if exp is None:
        st.info("①でシーンを選び、「このシーンを読み込む」を押してください。")
    else:
        df, legend, info = exp
        theme.section("俯瞰 2D ピッチ",
                      f"{info['home']} vs {info['away']} — {info['frames']} フレーム")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("フレーム数", info["frames"])
        m2.metric("fps", f"{info['fps']:.2f}")
        m3.metric("列数", info["columns"])
        m4.metric("欠損率", f"{df.isna().mean().mean()*100:.1f}%")

        trail = st.slider("軌跡の長さ（フレーム）", 0, 90, 30, 10,
                          help="0 で軌跡なし。30fps なら 30 フレーム＝約1秒。")
        st.caption(
            f"青 = {info['home']}（x=105 方向へ攻撃）　赤 = {info['away']}　"
            "◆ = ボール。数字はスロット番号です。"
        )
        st.plotly_chart(pitch_figure(df, legend, trail),
                        width="stretch", config={"displayModeBar": False})

        st.divider()
        theme.section("スロットと選手の対応")
        if legend is not None and not legend.empty:
            st.dataframe(legend, width="stretch", hide_index=True)
        else:
            st.caption(
                "スロット対応表がありません（CSV のみ読み込んだ場合）。"
                "ピッチ上は P 番号で表示されます。"
            )


# ── ③ 書き出し ───────────────────────────────────────────────────────────────

with tab3:
    exp = st.session_state["export"]
    if exp is None:
        st.info("①でシーンを選び、「このシーンを読み込む」を押してください。")
    else:
        df, legend, info = exp
        rich = st.session_state.get("enriched")
        sc = st.session_state["scene"] or {}
        out_df = rich if rich is not None else df

        theme.section("CSV を書き出す",
                      f"{out_df.shape[0]} 行 × {out_df.shape[1]} 列")
        st.caption(
            "列名・座標系（正規化 0–1）・攻撃方向（Home が x=1 へ）は既存の "
            "Export_GSA と同一です。app_22 / app_23 のサイドバーから読み込めます。"
        )

        stem = st.text_input(
            "ファイル名",
            f"PFF_{info['game_id']}_{sc.get('player','scene')}_{int(info['center_time'])}s"
            .replace(" ", "_"),
        )

        # ── 主たる出力：全指標つき ──
        if rich is not None:
            cat = feature_catalog(rich)
            summary = cat.groupby(["層", "カテゴリ"]).size().reset_index(name="列数")

            m1, m2, m3 = st.columns(3)
            m1.metric("総列数", rich.shape[1])
            m2.metric("うち特徴量", rich.shape[1] - df.shape[1])
            m3.metric("フレーム数", rich.shape[0])

            c1, c2 = st.columns([2, 3])
            with c1:
                st.dataframe(summary, width="stretch", hide_index=True)
                st.caption(
                    "**X** は物理量（走り・位置・プレッシャー）。"
                    "**中間Y** は xT・空間支配・前進。"
                    "**最終Y** はゴールまでの時間。"
                    "中間Y の計算元は X に入れていません。"
                )
            with c2:
                st.caption("列の一覧（層・カテゴリ・欠損率・値域）")
                st.dataframe(cat, width="stretch", hide_index=True, height=300)

            d1, d2, d3 = st.columns(3)
            d1.download_button(
                f"全指標つき CSV（{rich.shape[1]} 列）",
                data=rich.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{stem}_enriched.csv", mime="text/csv",
                type="primary", width="stretch",
                help="GSA に投入する主たる出力。X / 中間Y / 最終Y をすべて含みます。",
            )
            d2.download_button(
                "指標の一覧（データ辞書）",
                data=cat.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{stem}_features.csv", mime="text/csv", width="stretch",
                help="どの列がどの層かの対応表。指標選定に使います。",
            )
            if legend is not None and not legend.empty:
                d3.download_button(
                    "スロット対応表",
                    data=legend.to_csv(index=False).encode("utf-8-sig"),
                    file_name=f"{stem}_legend.csv", mime="text/csv",
                    width="stretch", help="P1〜P11 が誰かの対応。",
                )
        else:
            st.warning(
                "全指標が未計算です。①でシーンを読み込み直すと自動で計算されます。"
            )

        # ── 補助：座標のみ / 生データ ──
        with st.expander("座標のみの出力（既存 Export_GSA と同じ 127 列）"):
            st.caption(
                "特徴量を含まない素の出力です。app_22 / app_23 で見るだけなら"
                "こちらでも足ります。"
            )
            coords = st.radio(
                "座標系", ["meters", "normalized"], horizontal=True,
                format_func=lambda v: "正規化 0–1（Pitch Log 標準）"
                if v == "normalized" else "そのまま",
                index=1,
            )
            st.dataframe(df.head(6), width="stretch")
            e1, e2 = st.columns(2)
            e1.download_button(
                "Export_GSA CSV（127 列）",
                data=df.to_csv(index=False).encode("utf-8-sig"),
                file_name=f"{stem}.csv", mime="text/csv", width="stretch",
            )
            if e2.button("作業フォルダに保存（app_22 から読める場所）",
                         width="stretch"):
                out = ROOT / f"{stem}.csv"
                df.to_csv(out, index=False, encoding="utf-8-sig")
                if legend is not None and not legend.empty:
                    legend.to_csv(ROOT / f"{stem}_legend.csv", index=False,
                                  encoding="utf-8-sig")
                if rich is not None:
                    rich.to_csv(ROOT / f"{stem}_enriched.csv", index=False,
                                encoding="utf-8-sig")
                st.success(
                    f"保存しました: `{out.name}`"
                    + ("（全指標つきも同時に保存）" if rich is not None else "")
                )

        with st.expander("先頭 20 行を確認する"):
            st.dataframe(out_df.head(20), width="stretch")

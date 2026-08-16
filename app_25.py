"""
app_25.py
=========
Pitch Log v25 — ラグビー上空映像トラッキング

トラッキングデータが無い競技（ラグビー部）向けに、上空から撮影した映像だけから
選手・ボールの位置情報を復元し、フレームごとの時系列 CSV として書き出す。

    ① 動画を読み込む
    ② ピッチを 4 本の線で囲んで、映像↔ピッチ(m) を対応づける
    ③ 長い試合映像から任意の 30 秒を指定して解析する
    ④ 追跡結果を 2D マップで確認し、背番号を割り当てる
    ⑤ 走行距離・速度・スプリントを算出する
    ⑥ 2D タクティカルマップ動画を書き出す
    ⑦ 縦=時間 / 横=選手 の CSV を書き出す

Run
---
    streamlit run app_25.py

実装メモ
--------
- 各タブの中身は関数にしてある。タブ内で `st.stop()` を呼ぶとスクリプト全体が
  止まり、他のタブが描画されなくなるため、ガードは `return` で行うこと。
- 画面に出す説明文は `rugby/tutorial.py` に分離してある。文言だけ直したいときは
  そちらを編集する。
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from rugby import (
    Calibration,
    MIN_POINTS,
    PRESETS,
    PhysicalConfig,
    build_landmarks,
    build_pitch_line_defs,
    calibrate,
    calibrate_from_lines,
    calibrate_from_quad,
    cells_for_frame,
    dominance_series,
    draw_pitch_overlay,
    extract_clip,
    grab_frame,
    has_ffmpeg,
    landmark_index,
    physical_report,
    pitch_lines,
    probe_video,
    process_window,
    quad_from_enclosing_lines,
    render_animation,
    to_spec_schema,
    to_wide,
    track_summary,
)
from rugby import theme
from rugby.theme import COLORS
from rugby.tutorial import GLOSSARY, OVERVIEW, STEPS, TAB_HELP, TROUBLE

st.set_page_config(
    page_title="Pitch Log v25 — ラグビー",
    page_icon="🏉",
    layout="wide",
    initial_sidebar_state="expanded",
)
theme.inject()

COLOR_TEAM = {0: COLORS["team_a"], 1: COLORS["team_b"]}
COLOR_UNKNOWN = COLORS["unknown"]
COLOR_BALL = COLORS["ball"]
COLOR_LINE = COLORS["pitch_line"]


# ── session state ─────────────────────────────────────────────────────────────

for _k, _v in {
    "video_path": "",
    "clicks": {},          # landmark_key -> (x, y)
    "calib": None,
    "tracks": None,
    "jersey_map": {},      # track_id -> {"team": int|None, "jersey": str|None}
    "window": (0.0, 30.0),
    "dt": None,            # フレーム間隔（秒）。解析時に確定する
    "anim_path": None,
}.items():
    st.session_state.setdefault(_k, _v)


def _rgb(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2RGB)


def _fmt_time(sec: float) -> str:
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def _help(key: str) -> None:
    """タブ冒頭の折りたたみヘルプ。初回は開いた状態で出す。"""
    seen = st.session_state.setdefault("help_seen", set())
    with st.expander("📖 このタブの使い方", expanded=key not in seen):
        st.markdown(TAB_HELP[key])
    seen.add(key)


@st.cache_data(show_spinner=False)
def _probe(path: str):
    return probe_video(path)


# ── sidebar ───────────────────────────────────────────────────────────────────

preset_name = st.sidebar.selectbox("ピッチ規格", list(PRESETS.keys()), index=0)
SPEC = PRESETS[preset_name]
st.sidebar.caption(
    f"{SPEC.length:.0f}m × {SPEC.width:.0f}m ／ インゴール {SPEC.in_goal:.0f}m ／ "
    f"{SPEC.n_players}人制"
)

_has_video = bool(st.session_state["video_path"])
_has_calib = st.session_state["calib"] is not None
_has_tracks = st.session_state["tracks"] is not None

st.sidebar.divider()
st.sidebar.markdown("**進行状況**")
theme.step_list([
    ("① 動画を読み込む", _has_video, not _has_video),
    ("② ピッチの範囲を教える", _has_calib, _has_video and not _has_calib),
    ("③ 区間を解析する", _has_tracks, _has_calib and not _has_tracks),
])

if not _has_video:
    st.sidebar.info("次にやること：①タブで動画を読み込みます。")
elif not _has_calib:
    st.sidebar.info("次にやること：②タブでピッチを4本の線で囲みます。")
elif not _has_tracks:
    st.sidebar.info("次にやること：③タブで解析したい区間を選んで実行します。")
else:
    st.sidebar.success(
        f"解析済み — {st.session_state['tracks']['track_id'].nunique()} トラック。"
        "④〜⑦で結果を確認・出力できます。"
    )

st.sidebar.caption("操作に迷ったら「📖 使い方」タブをご覧ください。")

# ── ヘッダー ──────────────────────────────────────────────────────────────────

theme.header(
    "Aerial Video Tracking  ·  上空映像 → トラッキングデータ",
    chips=[
        ("VIDEO", _has_video),
        ("CALIBRATED", _has_calib),
        ("TRACKED", _has_tracks),
    ],
)


# ── ① 動画 ────────────────────────────────────────────────────────────────────

def tab_video() -> None:
    st.subheader("動画を読み込む")
    _help("video")

    col_a, col_b = st.columns([3, 2])
    with col_a:
        path_in = st.text_input(
            "動画ファイルのパス",
            value=st.session_state["video_path"],
            placeholder=r"C:\rugby\match_20260801.mp4",
            help="長時間の試合映像でも可。解析は指定した時間窓だけ行います。",
        )
        up = st.file_uploader("またはアップロード", type=["mp4", "mov", "avi", "mkv"])
        if up is not None:
            tmp = Path(tempfile.gettempdir()) / f"pitchlog_{up.name}"
            tmp.write_bytes(up.getbuffer())
            path_in = str(tmp)
            st.caption(f"一時保存: {tmp}")

        if path_in and path_in != st.session_state["video_path"]:
            st.session_state.update(
                video_path=path_in, clicks={}, calib=None, tracks=None, jersey_map={}
            )
            st.rerun()

    vp = st.session_state["video_path"]
    if not vp:
        st.info("動画のパスを入力するか、ファイルをアップロードしてください。")
        return

    try:
        info = _probe(vp)
    except Exception as e:
        st.error(f"動画を開けませんでした: {e}")
        return

    with col_b:
        st.metric("長さ", _fmt_time(info.duration_sec))
        st.metric("フレームレート", f"{info.fps:.1f} fps")
        st.metric("解像度", f"{info.width} × {info.height}")

    st.divider()
    t_prev = st.slider("プレビュー位置（秒）", 0.0,
                       max(info.duration_sec - 0.1, 0.1), 0.0, 0.5)
    try:
        st.image(_rgb(grab_frame(vp, t_prev)), width="stretch",
                 caption=f"{_fmt_time(t_prev)} 時点")
    except Exception as e:
        st.error(f"フレームを取得できませんでした: {e}")

    # ── 長い試合映像からの切り出し ──
    size_mb = Path(vp).stat().st_size / 1e6 if Path(vp).exists() else 0.0
    if info.duration_sec > 120 or size_mb > 300:
        st.divider()
        theme.section("この試合から切り出す", "長い映像はここで短くしてから使う")
        st.caption(
            f"この映像は {info.duration_sec / 60:.0f} 分 / {size_mb:.0f} MB あります。"
            "解析するのは 30 秒だけなので、先に切り出しておくと軽く扱えます。"
            "クラウドで使う場合は特に必要です（大きいファイルはアップロードできません）。"
        )
        c1, c2 = st.columns([3, 2])
        with c1:
            cs = st.number_input("切り出し開始（秒）", 0.0,
                                 max(info.duration_sec - 1.0, 1.0),
                                 float(t_prev), 1.0,
                                 help="上のプレビュー位置がそのまま入ります。")
            cd = st.number_input("長さ（秒）", 5.0, 300.0, 40.0, 5.0,
                                 help="解析窓（30秒）より少し長めにしておくと、"
                                      "あとで位置を微調整できます。")
            st.caption(f"切り出し範囲： {_fmt_time(cs)} 〜 {_fmt_time(cs + cd)}")
        with c2:
            st.caption(
                "ffmpeg があれば再エンコードせずほぼ一瞬で終わります"
                f"（現在: {'利用可' if has_ffmpeg() else '未検出 — OpenCVで再エンコード'}）。"
            )
            if st.button("切り出して、これを解析対象にする", type="primary",
                         width="stretch"):
                out = Path(tempfile.gettempdir()) / f"pitchlog_clip_{int(cs)}s.mp4"
                bar = st.progress(0.0, text="切り出し中…")
                try:
                    p, how = extract_clip(
                        vp, cs, cd, out,
                        progress=lambda f, m: bar.progress(min(max(f, 0.0), 1.0), text=m),
                    )
                except Exception as e:
                    bar.empty()
                    st.error(f"切り出しに失敗しました: {e}")
                    return
                bar.empty()
                st.session_state.update(
                    video_path=str(p), clicks={}, calib=None, tracks=None, jersey_map={}
                )
                st.success(
                    f"{p.stat().st_size / 1e6:.1f} MB に切り出しました（{how}）。"
                    "解析対象をこのクリップに切り替えます。"
                )
                st.rerun()


# ── ② キャリブレーション ──────────────────────────────────────────────────────

def _canvas_lines(json_data: dict | None, scale: float) -> list[tuple[tuple[float, float],
                                                                    tuple[float, float]]]:
    """描画キャンバスの JSON から線分の端点（元解像度）を取り出す。

    fabric.js の line オブジェクトは x1/y1/x2/y2 が中心相対なので、
    バウンディングボックス(left/top/width/height)と向きの符号から実座標を組む。
    """
    out = []
    for o in (json_data or {}).get("objects", []):
        if o.get("type") != "line":
            continue
        left, top = float(o.get("left", 0)), float(o.get("top", 0))
        w = float(o.get("width", 0)) * float(o.get("scaleX", 1) or 1)
        h = float(o.get("height", 0)) * float(o.get("scaleY", 1) or 1)
        if abs(w) < 3 and abs(h) < 3:
            continue                      # クリックしただけの点は無視
        rev_x = float(o.get("x2", 0)) < float(o.get("x1", 0))
        rev_y = float(o.get("y2", 0)) < float(o.get("y1", 0))
        xa, xb = (left + w, left) if rev_x else (left, left + w)
        ya, yb = (top + h, top) if rev_y else (top, top + h)
        out.append(((xa * scale, ya * scale), (xb * scale, yb * scale)))
    return out


def _guess_axis(seg) -> str:
    """画像上の傾きから、縦断(x=const)か横断(y=const)かを推測する。"""
    (x1, y1), (x2, y2) = seg
    return "x" if abs(x2 - x1) < abs(y2 - y1) else "y"


def tab_calibration() -> None:
    st.subheader("ピッチラインをなぞって対応づける")
    _help("calibration")

    vp = st.session_state["video_path"]
    if not vp:
        st.info("先に①で動画を読み込んでください。")
        return

    try:
        info = _probe(vp)
    except Exception as e:
        st.error(f"動画を開けませんでした: {e}")
        return

    mode = st.radio(
        "指定方法",
        ["ピッチを4本の線で囲む（かんたん）", "ラインを個別に指定", "点をクリック"],
        horizontal=True,
        help="通常は「4本の線で囲む」で十分です。ピッチが部分的にしか写っていない"
             "場合だけ、他の方法でラインを個別に指定してください。",
    )
    if mode.startswith("ピッチを4本"):
        _calibration_by_quad(vp, info)
    elif mode == "ラインを個別に指定":
        _calibration_by_lines(vp, info)
    else:
        _calibration_by_points(vp, info)


def _draw_canvas(vp: str, info, key: str, help_text: str):
    """線を引くキャンバスを描画し、(線分リスト, フレーム, 時刻) を返す。"""
    from rugby._canvas_compat import get_canvas

    st_canvas = get_canvas()
    if st_canvas is None:
        st.error(
            "線を引く機能を利用できません。"
            "`pip install streamlit-drawable-canvas` を実行するか、"
            "「点をクリック」に切り替えてください。"
        )
        return None, None, 0.0

    from PIL import Image

    top1, top2 = st.columns([1, 3])
    with top1:
        t_cal = st.number_input(
            "使用フレーム（秒）", 0.0, max(info.duration_sec - 0.1, 0.1), 0.0, 0.5,
            key=f"{key}_t",
        )
    with top2:
        disp_w = st.select_slider(
            "表示サイズ（px）", [640, 820, 1000, 1200], value=820,
            key=f"{key}_w",
            help="画面に収まる範囲で大きいほど、線を正確に引けます。",
        )
        st.caption(help_text)

    try:
        frame = grab_frame(vp, t_cal)
    except Exception as e:
        st.error(f"フレームを取得できませんでした: {e}")
        return None, None, 0.0

    scale = info.width / disp_w
    disp_h = int(info.height / scale)
    bg = Image.fromarray(_rgb(cv2.resize(frame, (disp_w, disp_h))))

    # このコンポーネントは自身の寸法を Streamlit へ伝えられず、iframe が
    # height=0 / width=300（HTML 既定値）に潰れてキャンバスが見切れる。
    # 実寸を px で明示して回避する。% ではなく px なのは、iframe を伸縮させても
    # 中のキャンバスは実寸のままで、比率がずれると見た目と座標が食い違うため。
    st.markdown(
        "<style>iframe[title='streamlit_drawable_canvas.st_canvas']"
        f"{{height:{disp_h + 60}px!important;width:{disp_w + 4}px!important;"
        "max-width:none!important;}</style>",
        unsafe_allow_html=True,
    )
    canvas = st_canvas(
        background_image=bg, drawing_mode="line",
        stroke_width=3, stroke_color="#00e5ff",
        fill_color="rgba(0,0,0,0)",
        height=disp_h, width=disp_w,
        update_streamlit=True, key=key,
    )
    st.caption("ドラッグで線を引きます。引き直すときは左下のゴミ箱で全消去できます。")

    return _canvas_lines(canvas.json_data if canvas else None, scale), frame, t_cal


def _calibration_by_quad(vp: str, info) -> None:
    st.caption(
        "ピッチの外周に沿って **4 本の線**を引いて囲んでください"
        "（左右のライン 2 本＋上下のライン 2 本）。"
        "どの線がどれかは自動で判別するので、名前を選ぶ必要はありません。"
    )

    segs, frame, t_cal = _draw_canvas(
        vp, info, "cal_quad",
        "ピッチ全体がよく見えるフレームを選んでください。",
    )
    if segs is None:
        return

    st.divider()
    c1, c2 = st.columns([2, 3])

    with c1:
        theme.section("引いた線", f"{len(segs)} 本")
        if len(segs) < 4:
            st.info(f"あと {4 - len(segs)} 本引いてください。")
            return
        if len(segs) > 4:
            st.warning("4 本を超えています。ゴミ箱で消してから引き直してください。")
            return

        if SPEC.in_goal > 0:
            scope = st.radio(
                "囲んだ範囲",
                ["デッドボールラインまで（外周全体）", "ゴールライン間（インゴールを除く）"],
                help="ラグビーはインゴールがあるため、どこを囲んだかで縮尺が変わります。",
            )
            include_in_goal = scope.startswith("デッドボール")
        else:
            include_in_goal = False

        fx = st.checkbox("左右を反転", value=False,
                         help="復元した枠が実際と左右逆に出たときに使います。")
        fy = st.checkbox("上下を反転", value=False)

        if st.button("この4本でキャリブレーション", type="primary", width="stretch"):
            try:
                corners = quad_from_enclosing_lines(segs)
                cal = calibrate_from_quad(
                    corners, SPEC, (info.width, info.height),
                    include_in_goal=include_in_goal, flip_x=fx, flip_y=fy,
                    ref_time_sec=float(t_cal),
                )
                st.session_state["calib"] = cal
                st.success("完了しました。右の重ね描きで確認してください。")
            except Exception as e:
                st.error(str(e))

        cal = st.session_state["calib"]
        if cal is not None:
            st.download_button(
                "キャリブレーションを保存 (JSON)",
                data=json.dumps(cal.to_dict(), ensure_ascii=False, indent=2),
                file_name="calibration.json", mime="application/json",
                width="stretch", help="カメラ位置が同じなら別の映像でも再利用できます。",
            )

    with c2:
        cal = st.session_state["calib"]
        if cal is None:
            st.caption("キャリブレーション後、ここに復元したピッチ枠が表示されます。")
        else:
            theme.section("確認", "重ね描きで合っているか見る")
            st.image(_rgb(draw_pitch_overlay(frame, cal)), width="stretch")
            st.caption(
                "黄色の線が実際のピッチラインと重なっていれば成功です。"
                "22m ラインやハーフウェイの位置がずれている場合は「囲んだ範囲」の"
                "選択を、左右・上下が逆なら反転チェックを切り替えてください。"
                "※この方式は 4 点ちょうどのため数値上の誤差は必ず 0 になります。"
                "見た目で判断してください。"
            )


def _calibration_by_lines(vp: str, info) -> None:
    st.caption(
        "映像の上でピッチラインをドラッグしてなぞってください。"
        "**縦断ライン（ゴールライン・22m など）2 本以上**と"
        "**横断ライン（タッチラインなど）2 本以上**が必要です。"
    )

    segs, frame, t_cal = _draw_canvas(
        vp, info, "cal_lines",
        "ピッチが部分的にしか写っていない場合に使います。全体が見えているなら"
        "「4本の線で囲む」のほうが簡単です。",
    )
    if segs is None:
        return

    st.divider()
    c1, c2 = st.columns([3, 2])

    with c1:
        theme.section("なぞった線の割当")
        if not segs:
            st.caption("まだ線がありません。上の映像をドラッグしてください。")
            return

        defs = build_pitch_line_defs(SPEC)
        by_axis = {"x": [d for d in defs if d.axis == "x"],
                   "y": [d for d in defs if d.axis == "y"]}
        axis_of = {d.key: d.axis for d in defs}

        drawn: dict[str, tuple] = {}
        used: set[str] = set()
        for i, seg in enumerate(segs):
            axis = _guess_axis(seg)
            opts = [d for d in by_axis[axis] if d.key not in used]
            if not opts:
                continue
            sel = st.selectbox(
                f"線 {i + 1}（{'縦断' if axis == 'x' else '横断'}）", opts,
                format_func=lambda d: d.label_ja, key=f"cal_line_sel_{i}",
            )
            used.add(sel.key)
            drawn[sel.key] = seg

        n_x = sum(1 for k in drawn if axis_of[k] == "x")
        n_y = len(drawn) - n_x
        st.caption(f"縦断 {n_x} 本 ／ 横断 {n_y} 本")

        if n_x < 2 or n_y < 2:
            st.info("縦断・横断ともに 2 本以上なぞってください。")
        elif st.button("この線でキャリブレーション", type="primary", width="stretch"):
            try:
                cal = calibrate_from_lines(
                    drawn, SPEC, (info.width, info.height), ref_time_sec=float(t_cal),
                )
                st.session_state["calib"] = cal
                n_pt = len(cal.image_points)
                if n_pt <= MIN_POINTS:
                    st.success(
                        f"完了（交点 {n_pt} 点）。※4点ちょうどでは誤差は必ず 0 になり、"
                        "品質の目安になりません。線を 1 本足すと実際のずれが分かります。"
                    )
                else:
                    st.success(
                        f"完了 — 交点 {n_pt} 点 ／ 再投影誤差 {cal.reproj_error_m:.3f} m"
                    )
            except Exception as e:
                st.error(str(e))

    with c2:
        cal = st.session_state["calib"]
        if cal is None:
            st.caption("キャリブレーション後、ここに復元したピッチ枠が表示されます。")
        else:
            theme.section("確認", "重ね描きで合っているか見る")
            st.image(_rgb(draw_pitch_overlay(frame, cal)), width="stretch")
            st.caption(
                "黄色の枠が実際のラインと重なっていれば成功です。"
                "ずれている場合は線を引き直してください。"
            )
            st.download_button(
                "キャリブレーションを保存 (JSON)",
                data=json.dumps(cal.to_dict(), ensure_ascii=False, indent=2),
                file_name="calibration.json", mime="application/json",
                width="stretch", help="カメラ位置が同じなら別の映像でも再利用できます。",
            )


def _calibration_by_points(vp: str, info) -> None:
    st.caption(
        "映像上でピッチラインの交点をクリックし、それがピッチ上のどこかを指定します。"
        f"最低 {MIN_POINTS} 点（同一直線上に並ばないように）。"
    )

    lms = build_landmarks(SPEC)
    idx = landmark_index(SPEC)
    c1, c2 = st.columns([5, 3])

    with c2:
        t_cal = st.number_input("キャリブレーションに使うフレーム（秒）",
                                0.0, max(info.duration_sec - 0.1, 0.1), 0.0, 0.5,
                                key="cal_pt_t")

        groups = list(dict.fromkeys(lm.group for lm in lms))
        grp = st.selectbox("ライン", groups)
        opts = [lm for lm in lms if lm.group == grp]
        lm_sel = st.selectbox(
            "交点", opts,
            format_func=lambda l: f"{l.label_ja}  ({l.x:.0f}, {l.y:.0f})m",
        )

        theme.section("登録済みの点")
        clicks = st.session_state["clicks"]
        if clicks:
            st.dataframe(
                pd.DataFrame([
                    {"ランドマーク": idx[k].label_ja,
                     "ピッチ(m)": f"({idx[k].x:.0f}, {idx[k].y:.0f})",
                     "画像(px)": f"({v[0]:.0f}, {v[1]:.0f})"}
                    for k, v in clicks.items()
                ]),
                width="stretch", hide_index=True,
            )
            cc1, cc2 = st.columns(2)
            if cc1.button("最後の点を取消", width="stretch"):
                clicks.pop(list(clicks)[-1], None)
                st.rerun()
            if cc2.button("すべて消去", width="stretch"):
                st.session_state.update(clicks={}, calib=None)
                st.rerun()
        else:
            st.caption("まだありません。左の映像をクリックしてください。")

        st.divider()
        enough = len(clicks) >= MIN_POINTS
        if st.button("この点でキャリブレーション", type="primary",
                     disabled=not enough, width="stretch"):
            try:
                cal = calibrate(list(clicks.values()), list(clicks.keys()),
                                SPEC, (info.width, info.height),
                                ref_time_sec=float(t_cal))
                st.session_state["calib"] = cal
                st.success(f"完了 — 再投影誤差 {cal.reproj_error_m:.3f} m")
            except Exception as e:
                st.error(str(e))
        if not enough:
            st.caption(f"あと {MIN_POINTS - len(clicks)} 点必要です。")

        cal = st.session_state["calib"]
        if cal is not None:
            st.download_button(
                "キャリブレーションを保存 (JSON)",
                data=json.dumps(cal.to_dict(), ensure_ascii=False, indent=2),
                file_name="calibration.json", mime="application/json",
                width="stretch",
                help="カメラ位置が同じなら別の映像でも再利用できます。",
            )
        up_cal = st.file_uploader("保存済みキャリブレーションを読み込む", type=["json"])
        if up_cal is not None:
            try:
                tmp = Path(tempfile.gettempdir()) / "pitchlog_calib_up.json"
                tmp.write_bytes(up_cal.getbuffer())
                st.session_state["calib"] = Calibration.load(tmp)
                st.success("読み込みました。")
            except Exception as e:
                st.error(f"読み込めませんでした: {e}")

    with c1:
        try:
            frame = grab_frame(vp, t_cal)
        except Exception as e:
            st.error(f"フレームを取得できませんでした: {e}")
            return

        cal = st.session_state["calib"]
        shown = draw_pitch_overlay(frame, cal) if cal is not None else frame.copy()
        for px, py in st.session_state["clicks"].values():
            cv2.circle(shown, (int(px), int(py)), 7, (0, 0, 255), -1, cv2.LINE_AA)
            cv2.circle(shown, (int(px), int(py)), 7, (255, 255, 255), 2, cv2.LINE_AA)

        disp_w = 900
        scale = info.width / disp_w
        small = cv2.resize(shown, (disp_w, int(info.height / scale)))

        try:
            from streamlit_image_coordinates import streamlit_image_coordinates

            pt = streamlit_image_coordinates(_rgb(small), key="calib_img")
            st.caption(f"クリックすると「{lm_sel.label_ja}」として登録されます。")
            if pt is not None:
                px, py = pt["x"] * scale, pt["y"] * scale
                prev = st.session_state["clicks"].get(lm_sel.key)
                if prev is None or abs(prev[0] - px) > 1 or abs(prev[1] - py) > 1:
                    st.session_state["clicks"][lm_sel.key] = (px, py)
                    st.rerun()
        except ImportError:
            st.image(_rgb(small), width="stretch")
            st.warning(
                "クリック取得には `pip install streamlit-image-coordinates` が必要です。"
                "下の数値入力でも指定できます。"
            )
            m1, m2, m3 = st.columns([2, 2, 1])
            mx = m1.number_input("X (px)", 0, info.width, 0)
            my = m2.number_input("Y (px)", 0, info.height, 0)
            if m3.button("登録"):
                st.session_state["clicks"][lm_sel.key] = (float(mx), float(my))
                st.rerun()

        if cal is not None:
            st.caption(
                "黄色の線が復元したピッチ枠です。実際のラインと重なっていれば成功。"
                "ずれている場合は点を取り消して取り直してください。"
            )


# ── ③ 区間解析 ────────────────────────────────────────────────────────────────

def tab_analyze() -> None:
    st.subheader("解析する 30 秒を指定する")
    _help("analyze")

    vp = st.session_state["video_path"]
    cal = st.session_state["calib"]
    if not vp:
        st.info("先に①で動画を読み込んでください。")
        return
    if cal is None:
        st.info("先に②でキャリブレーションしてください。")
        return

    info = _probe(vp)
    c1, c2 = st.columns([3, 2])

    with c1:
        start = st.slider("開始位置（秒）", 0.0, max(info.duration_sec - 1.0, 1.0),
                          float(st.session_state["window"][0]), 0.5, format="%.1f")
        dur = st.number_input("長さ（秒）", 1.0, 300.0,
                              float(st.session_state["window"][1]), 1.0)
        st.session_state["window"] = (start, dur)
        st.caption(f"解析区間： {_fmt_time(start)} 〜 {_fmt_time(start + dur)}")
        try:
            st.image(_rgb(draw_pitch_overlay(grab_frame(vp, start), cal)),
                     width="stretch", caption="開始フレーム")
        except Exception as e:
            st.error(f"フレームを取得できませんでした: {e}")

    with c2:
        theme.section("解析設定", "迷ったら既定のまま")
        backend = st.selectbox(
            "検出方式", ["bgsub", "yolo"],
            help="bgsub=背景差分（固定カメラ向き・追加インストール不要）／"
                 "yolo=物体検出（要 ultralytics・静止した選手にも強い）",
        )
        stabilize = st.checkbox(
            "手ブレ補正", value=False,
            help="ドローンなどカメラが動く場合に有効化。処理時間は約2倍。",
        )
        stride = st.select_slider("処理間隔（フレーム）", [1, 2, 3, 5], value=1,
                                  help="2 にすると半分のフレームだけ処理し約2倍速くなります。")
        player_size = st.slider("選手の想定サイズ（m）", 0.4, 1.6, 0.85, 0.05,
                                help="俯瞰で1人が占める大きさ。検出の大小フィルタに使います。")
        min_track = st.slider("最短トラック長（秒）", 0.0, 5.0, 1.0, 0.5,
                              help="これより短いトラックは誤検出とみなして除外します。")
        detect_ball = st.checkbox(
            "ボールも検出する（実験的）", value=False,
            help="上空映像のボールは数ピクセルしかなく、背景差分では芝のノイズと"
                 "区別できません。検証では位置誤差が中央値15m超で実用になりませんでした。"
                 "有効にする場合は結果を必ず目視確認してください。",
        )
        if detect_ball:
            st.caption(
                "⚠ ボール座標は信頼性が低いため、そのまま分析に使わないでください。"
            )
        with st.expander("追従性の詳細設定"):
            meas_noise = st.slider("観測ノイズ（m）", 0.05, 0.60, 0.12, 0.01,
                                   help="小さいほど検出位置に忠実。映像が鮮明なら小さく。")
            accel = st.slider("想定加速度（m/s²）", 3.0, 20.0, 12.0, 1.0,
                              help="大きいほど急な方向転換に追従します。")
        run = st.button("この区間を解析", type="primary", width="stretch")

    if not run:
        return

    bar = st.progress(0.0, text="準備中…")
    try:
        df = process_window(
            vp, cal, start_sec=start, duration_sec=dur,
            stride=stride, backend=backend, stabilize=stabilize,
            min_track_seconds=min_track,
            tracker_kw={"meas_noise_m": meas_noise, "process_accel": accel},
            progress=lambda f, m: bar.progress(min(max(f, 0.0), 1.0), text=m),
            player_size_m=player_size,
            detect_ball=detect_ball,
        )
    except Exception as e:
        bar.empty()
        st.error(f"解析に失敗しました: {e}")
        return

    bar.empty()
    if df.empty:
        st.warning("何も検出できませんでした。キャリブレーションや検出設定を見直してください。")
        return

    # フィジカル算出はフレーム間隔に依存するので、解析時の実効値を保存しておく
    st.session_state.update(tracks=df, jersey_map={}, anim_path=None,
                            dt=stride / info.fps)
    st.success(
        f"完了 — {int(df['frame'].max())} フレーム / "
        f"{df[df['kind'] == 'player']['track_id'].nunique()} トラックを検出しました。"
        "④で確認してください。"
    )


# ── ④ 結果・背番号 ────────────────────────────────────────────────────────────

def _pitch_figure(df: pd.DataFrame, spec, jersey_map: dict,
                  show_voronoi: bool = False) -> go.Figure:
    """2D ピッチ上に追跡結果をアニメーション表示する。"""
    frame_ids = sorted(df["frame"].unique())

    shapes = []
    # 芝の刈り込みストライプ。最背面に敷いて質感を出す。
    for x0, x1, light in theme.turf_stripes(spec.x_min, spec.x_max):
        shapes.append(dict(
            type="rect", x0=x0, x1=x1, y0=0, y1=spec.width,
            fillcolor=COLORS["turf_light"] if light else COLORS["turf_dark"],
            line=dict(width=0), layer="below",
        ))
    # ピッチライン（少し透過させたクリーンな白）
    for kind, verts in pitch_lines(spec):
        for a, b in zip(verts[:-1], verts[1:]):
            shapes.append(dict(
                type="line", x0=a[0], y0=a[1], x1=b[0], y1=b[1],
                line=dict(color=_rgba(COLOR_LINE, 0.72), width=1.4,
                          dash="dash" if kind == "dashed" else "solid"),
                layer="below",
            ))

    def traces(f: int):
        d = df[df["frame"] == f]
        pl = d[d["kind"] == "player"]
        out = []

        if show_voronoi:
            # 支配領域は背面に。芝のストライプが透けて見える程度の淡さに保つ。
            for cell in cells_for_frame(d, spec):
                col = COLOR_TEAM.get(cell.team, COLOR_UNKNOWN)
                out.append(go.Scatter(
                    x=cell.polygon[:, 0], y=cell.polygon[:, 1],
                    fill="toself", fillcolor=_rgba(col, 0.25),
                    line=dict(color=_rgba(col, 0.55), width=1),
                    mode="lines", hoverinfo="skip", showlegend=False,
                ))

        # ドロップシャドウ層。ドットをわずかに右下へずらした黒で、
        # 選手がピッチから浮いて見えるようにする。
        out.append(go.Scatter(
            x=pl["x_m"] + 0.55, y=pl["y_m"] - 0.55, mode="markers",
            marker=dict(size=17, color="rgba(0,0,0,0.42)"),
            hoverinfo="skip", showlegend=False,
        ))

        for team, label in [(0, "チームA"), (1, "チームB"), (None, "未判別")]:
            sub = pl[pl["team"].isna()] if team is None else pl[pl["team"] == team]
            color = COLOR_TEAM.get(team, COLOR_UNKNOWN)
            out.append(go.Scatter(
                x=sub["x_m"], y=sub["y_m"], mode="markers+text",
                marker=dict(size=16, color=color,
                            line=dict(color=_rgba(COLORS["bg"], 0.85), width=1.6)),
                text=[str(jersey_map.get(int(t), {}).get("jersey") or int(t))
                      for t in sub["track_id"]],
                textposition="middle center",
                textfont=dict(size=8, color=COLORS["bg"], family=theme.FONT_SANS),
                name=label, customdata=sub["track_id"],
                hovertemplate="ID %{customdata}<br>(%{x:.1f}, %{y:.1f}) m<extra></extra>",
            ))
        b = d[d["kind"] == "ball"]
        out.append(go.Scatter(
            x=b["x_m"], y=b["y_m"], mode="markers",
            marker=dict(size=11, color=COLOR_BALL, symbol="diamond",
                        line=dict(color=_rgba(COLORS["bg"], 0.8), width=1.2)),
            name="ボール",
            hovertemplate="ボール (%{x:.1f}, %{y:.1f}) m<extra></extra>",
        ))
        return out

    fig = go.Figure(data=traces(frame_ids[0]))
    fig.frames = [go.Frame(data=traces(f), name=str(f)) for f in frame_ids]
    fig.update_layout(**theme.plotly_layout(
        plot_bgcolor=COLORS["bg"], shapes=shapes,
        xaxis=dict(range=[spec.x_min - 3, spec.x_max + 3], showgrid=False,
                   zeroline=False, constrain="domain", visible=False),
        yaxis=dict(range=[-3, spec.width + 3], showgrid=False, zeroline=False,
                   scaleanchor="x", scaleratio=1, visible=False),
        height=520, margin=dict(l=8, r=8, t=44, b=8),
        updatemenus=[dict(
            type="buttons", showactive=False, x=0.01, y=1.13, xanchor="left",
            bgcolor=COLORS["surface_2"], bordercolor=COLORS["border"],
            font=dict(color=COLORS["text"], size=11),
            buttons=[
                dict(label="▶ 再生", method="animate",
                     args=[None, dict(frame=dict(duration=40, redraw=True),
                                      fromcurrent=True, mode="immediate")]),
                dict(label="⏸ 停止", method="animate",
                     args=[[None], dict(frame=dict(duration=0, redraw=False),
                                        mode="immediate")]),
            ],
        )],
        sliders=[dict(
            active=0, y=0, x=0.06, len=0.92,
            currentvalue=dict(prefix="フレーム ",
                              font=dict(color=COLORS["text_muted"], size=11)),
            bgcolor=COLORS["border"], activebgcolor=COLORS["accent"],
            bordercolor=COLORS["border"], tickcolor=COLORS["border"],
            font=dict(color=COLORS["text_dim"], size=9),
            steps=[dict(method="animate", label=str(f),
                        args=[[str(f)], dict(frame=dict(duration=0, redraw=True),
                                             mode="immediate")])
                   for f in frame_ids],
        )],
        legend=dict(orientation="h", y=1.13, x=0.28, bgcolor="rgba(0,0,0,0)"),
    ))
    return fig


def tab_results() -> None:
    st.subheader("追跡結果を確認して背番号を割り当てる")
    _help("results")

    df = st.session_state["tracks"]
    if df is None:
        st.info("先に③で解析を実行してください。")
        return

    summary = track_summary(df, SPEC.n_players)
    n_players = int(df[df["kind"] == "player"]["track_id"].nunique())

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("フレーム数", int(df["frame"].max()))
    m2.metric("選手トラック", n_players)
    m3.metric("想定人数", SPEC.n_players * 2)
    n_ball = int((df["kind"] == "ball").sum())
    m4.metric(
        "ボール",
        f"{n_ball / max(df['frame'].nunique(), 1) * 100:.0f}%" if n_ball else "無効",
        help="上空映像でのボール検出は信頼性が低いため既定では無効です。",
    )

    if n_players > SPEC.n_players * 2:
        st.warning(
            f"トラック数（{n_players}）が想定人数（{SPEC.n_players * 2}）を超えています。"
            "③の「最短トラック長」を伸ばすか「選手の想定サイズ」を調整すると減ります。"
        )

    st.divider()
    left, right = st.columns([3, 2])

    with right:
        theme.section("背番号の割当")
        st.caption(
            "追跡 ID に背番号とチームを割り当てると、CSV の列名がその番号になります。"
            "空欄のままでも出力できます（出現の長い順に P1, P2… を自動採番）。"
        )
        base = summary[["track_id", "出現フレーム数", "チーム", "カバー率"]].copy()
        base["チーム"] = base["チーム"].map({0.0: "A", 1.0: "B"}).fillna("未判別")
        base["背番号"] = [
            st.session_state["jersey_map"].get(int(t), {}).get("jersey") or ""
            for t in base["track_id"]
        ]
        edited = st.data_editor(
            base, hide_index=True, width="stretch", height=360,
            column_config={
                "track_id": st.column_config.NumberColumn("ID", disabled=True),
                "出現フレーム数": st.column_config.NumberColumn(disabled=True),
                "カバー率": st.column_config.NumberColumn(format="%.2f", disabled=True),
                "チーム": st.column_config.SelectboxColumn(options=["A", "B", "未判別"]),
                "背番号": st.column_config.TextColumn(help="例: 10"),
            },
            key="jersey_editor",
        )
        if st.button("割当を反映", type="primary", width="stretch"):
            jm = {
                int(r["track_id"]): {
                    "team": {"A": 0, "B": 1}.get(r["チーム"]),
                    "jersey": str(r["背番号"]).strip() or None,
                }
                for _, r in edited.iterrows()
            }
            d = st.session_state["tracks"].copy()
            is_p = d["kind"] == "player"
            d.loc[is_p, "jersey"] = d.loc[is_p, "track_id"].map(
                lambda t: jm.get(int(t), {}).get("jersey"))
            d.loc[is_p, "team"] = d.loc[is_p, "track_id"].map(
                lambda t: jm.get(int(t), {}).get("team"))
            st.session_state.update(tracks=d, jersey_map=jm)
            st.success("反映しました。")
            st.rerun()

    with left:
        head, opt = st.columns([2, 3])
        with head:
            theme.section("2D マッピング")
        show_vor = opt.checkbox(
            "ボロノイ図（空間支配）を重ねる", value=False,
            help="各選手が最も早く到達できる領域でピッチを分割します。"
                 "チーム未判別の選手は計算から除外されます。",
        )
        st.plotly_chart(
            _pitch_figure(df, SPEC, st.session_state["jersey_map"], show_vor),
            width="stretch", config={"displayModeBar": False},
        )

    st.divider()
    theme.section("トラック一覧")
    st.dataframe(summary, width="stretch", hide_index=True)


# ── ⑤ フィジカル ──────────────────────────────────────────────────────────────

def tab_physical() -> None:
    st.subheader("フィジカルデータ（走行距離・速度・スプリント）")
    _help("physical")

    df = st.session_state["tracks"]
    if df is None:
        st.info("先に③で解析を実行してください。")
        return

    info = _probe(st.session_state["video_path"])
    dt = st.session_state.get("dt") or 1.0 / info.fps

    c1, c2 = st.columns([2, 3])
    with c1:
        theme.section("算出パラメータ")
        sprint_kmh = st.slider("スプリント速度閾値（km/h）", 12.0, 30.0, 24.0, 0.5,
                               help="サッカーの一般基準は24km/h。ラグビーでは"
                                    "ポジションにより20km/h前後で運用することもあります。")
        sprint_sec = st.slider("スプリント継続時間（秒）", 0.2, 3.0, 1.0, 0.1)
        deadband = st.slider("静止とみなす速度（m/s）", 0.0, 2.0, 0.5, 0.1,
                             help="これ未満は検出枠のブレとみなし走行距離に加算しません。")
        spd_win = st.slider("速度の平滑窓（秒）", 0.2, 3.0, 1.0, 0.1,
                            help="1〜2秒推奨。長いほど滑らかですが加減速の山が鈍ります。")
        use_savgol = st.checkbox("Savitzky-Golayフィルタを使う", value=True,
                                 help="オフにすると移動平均になります。")

    cfg = PhysicalConfig(
        speed_smooth_sec=spd_win, deadband_mps=deadband,
        sprint_kmh=sprint_kmh, sprint_min_sec=sprint_sec, use_savgol=use_savgol,
    )
    rep = physical_report(df, dt, cfg)
    if rep.empty:
        st.warning("集計できるトラックがありません。")
        return

    with c2:
        theme.section("サマリ")
        m1, m2, m3 = st.columns(3)
        m1.metric("平均走行距離", f"{rep['total_distance_m'].mean():.1f} m")
        m2.metric("最高速度", f"{rep['top_speed_kmh'].max():.1f} km/h")
        m3.metric("スプリント総数", int(rep["sprint_count"].sum()))
        st.caption(
            f"解析時間 {rep['duration_sec'].max():.1f} 秒ぶん。"
            "30秒窓なので、試合全体の値ではなく当該シーンの値です。"
        )
        if (rep["discontinuities"] > 0).any():
            n = int((rep["discontinuities"] > 0).sum())
            st.warning(
                f"{n} 本のトラックに断絶（物理的にありえない飛び／欠測）があります。"
                "ID の取り違えが起きている可能性があり、その選手の数値は過大になりがちです。"
            )

    st.divider()
    st.dataframe(rep, width="stretch", hide_index=True)
    st.download_button(
        "フィジカルレポートをダウンロード (CSV)",
        data=rep.to_csv(index=False).encode("utf-8-sig"),
        file_name="physical_report.csv", mime="text/csv", type="primary",
    )


# ── ⑥ 2Dアニメーション ────────────────────────────────────────────────────────

def tab_animation() -> None:
    st.subheader("2Dピッチアニメーション（MP4）を書き出す")
    _help("animation")
    st.caption(
        "抽出した座標が正しいかの目視確認にも、戦術分析用のタクティカルマップ映像"
        "としても使えます。"
    )

    df = st.session_state["tracks"]
    if df is None:
        st.info("先に③で解析を実行してください。")
        return

    info = _probe(st.session_state["video_path"])
    c1, c2 = st.columns([2, 3])

    with c1:
        trail = st.slider("軌跡の長さ（フレーム）", 0, 90, 30, 5,
                          help="0 で軌跡なし。25fpsなら30フレーム＝約1秒ぶん。")
        vor = st.checkbox("ボロノイ図を重ねる", value=False)
        ids = st.checkbox("ID / 背番号を表示", value=True)
        width = st.select_slider("横幅（px）", [854, 1280, 1920], value=1280)
        fps_out = st.number_input("フレームレート", 1.0, 60.0, float(info.fps), 1.0,
                                  help="既定は元動画と同じです。")
        go_render = st.button("MP4 を生成", type="primary", width="stretch")

    with c2:
        if st.session_state.get("anim_path") and Path(st.session_state["anim_path"]).exists():
            st.video(st.session_state["anim_path"])
            st.download_button(
                "動画をダウンロード (MP4)",
                data=Path(st.session_state["anim_path"]).read_bytes(),
                file_name="tactical_map.mp4", mime="video/mp4", width="stretch",
            )
        else:
            st.info("左の設定で「MP4 を生成」を押してください。")

    if go_render:
        bar = st.progress(0.0, text="準備中…")
        out = Path(tempfile.gettempdir()) / "pitchlog_tactical.mp4"
        try:
            render_animation(
                df, out, SPEC, fps=fps_out, width_px=width,
                trail_frames=trail, show_voronoi=vor, show_ids=ids,
                progress=lambda f, m: bar.progress(min(max(f, 0.0), 1.0), text=m),
            )
        except Exception as e:
            bar.empty()
            st.error(f"生成に失敗しました: {e}")
            return
        bar.empty()
        st.session_state["anim_path"] = str(out)
        st.rerun()

    st.divider()
    theme.section("空間支配率の推移", "ボロノイ面積の割合")
    ds = dominance_series(df, SPEC)
    if ds.empty:
        st.caption("チーム判別済みの選手が3人未満のフレームが多く、計算できません。")
    else:
        fig = go.Figure()
        for col, name, color in [("team0_share", "チームA", COLOR_TEAM[0]),
                                 ("team1_share", "チームB", COLOR_TEAM[1])]:
            fig.add_trace(go.Scatter(
                x=ds["time_sec"], y=ds[col], name=name, mode="lines",
                line=dict(color=color, width=1.5), stackgroup="one",
                fillcolor=_rgba(color, 0.45),
            ))
        fig.update_layout(**theme.plotly_layout(
            height=260, margin=dict(l=10, r=10, t=28, b=10),
            yaxis=dict(title="支配率", range=[0, 1], tickformat=".0%",
                       gridcolor=COLORS["border_soft"], zeroline=False),
            xaxis=dict(title="時刻（秒）", gridcolor=COLORS["border_soft"],
                       zeroline=False),
            legend=dict(orientation="h", y=1.18, bgcolor="rgba(0,0,0,0)"),
        ))
        st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


# ── ⑦ CSV出力 ────────────────────────────────────────────────────────────────

def tab_export() -> None:
    st.subheader("CSV を書き出す")
    _help("export")

    df = st.session_state["tracks"]
    if df is None:
        st.info("先に③で解析を実行してください。")
        return

    st.caption(
        "縦軸が時間、横軸が選手の形式です。列名は既存 Pitch Log の Export_GSA と"
        "同じ規約（Home_P1_X / Away_P3_Y / Ball_X …）なので、そのまま既存の"
        "可視化・特徴量付与パイプラインに載せられます。"
    )

    coords = st.radio(
        "座標系", ["meters", "normalized"],
        format_func=lambda v: "メートル（実寸・分析向き）" if v == "meters"
        else "正規化 0–1（既存 Pitch Log 互換）",
        horizontal=True,
    )

    wide = to_wide(df, SPEC.n_players, coords)
    st.dataframe(wide.head(12), width="stretch")
    st.caption(f"{wide.shape[0]} 行 × {wide.shape[1]} 列")

    stem = st.text_input("ファイル名の接頭辞", "rugby_scene")
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        f"ワイド形式（{coords}）",
        data=wide.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{stem}_wide_{coords}.csv", mime="text/csv",
        type="primary", width="stretch",
        help="縦=時間 / 横=選手。既存 Export_GSA と同じ列名規約。",
    )
    c2.download_button(
        "長形式（1行=1選手1フレーム）",
        data=df.to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{stem}_tracks_long.csv", mime="text/csv", width="stretch",
    )
    c3.download_button(
        "仕様書スキーマ",
        data=to_spec_schema(df).to_csv(index=False).encode("utf-8-sig"),
        file_name=f"{stem}_spec_schema.csv", mime="text/csv", width="stretch",
        help="frame_idx / timestamp / track_id / x_pitch / y_pitch / team_id",
    )


# ── ⓪ 使い方 ─────────────────────────────────────────────────────────────────

def tab_guide() -> None:
    st.subheader("はじめての方へ")
    st.markdown(OVERVIEW)

    st.divider()
    theme.section("手順", "上から順に進めます")
    for i, step in enumerate(STEPS):
        with st.expander(step["title"], expanded=(i == 0)):
            st.markdown(step["body"])
            if step.get("tip"):
                st.info(f"💡 {step['tip']}")

    st.divider()
    theme.section("うまくいかないとき", "症状から探す")
    st.caption("症状から探してください。")
    for t in TROUBLE:
        with st.expander(f"❓ {t['symptom']}"):
            st.markdown(f"**考えられる原因**：{t['cause']}")
            st.markdown(f"**対処**：{t['fix']}")

    st.divider()
    theme.section("用語集")
    for term, desc in GLOSSARY:
        st.markdown(f"**{term}** — {desc}")

    st.divider()
    theme.section("精度の目安", "合成映像での実測値")
    st.caption(
        "正解が既知の合成映像（30人・25fps・8秒窓）で測定した値です。"
        "実写ではこれより悪化します。実際の映像で再測定して設定を調整してください。"
    )
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("位置誤差（中央値）", "0.09 m")
    m2.metric("検出率", "97.7%")
    m3.metric("単一IDで追えた割合", "98.3%")
    m4.metric("1人あたりトラック数", "1.13", help="理想は 1.00")
    st.caption(
        "80物体まで実用的に動作し、密な交錯でもほぼ悪化しません。"
        "ただし**手ブレを補正しないと破綻します**（トラック数が34→676本）。"
        "詳細は `docs/RUGBY_TRACKING.md` を参照してください。"
    )


# ── レイアウト ────────────────────────────────────────────────────────────────

t0, t1, t2, t3, t4, t5, t6, t7 = st.tabs([
    "📖 使い方", "① 動画", "② キャリブレーション", "③ 区間解析", "④ 結果・背番号",
    "⑤ フィジカル", "⑥ 2Dアニメーション", "⑦ CSV出力",
])
with t0:
    tab_guide()
with t1:
    tab_video()
with t2:
    tab_calibration()
with t3:
    tab_analyze()
with t4:
    tab_results()
with t5:
    tab_physical()
with t6:
    tab_animation()
with t7:
    tab_export()

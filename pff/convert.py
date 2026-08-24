"""
pff/convert.py
==============
PFF のトラッキングを、Pitch Log の Export_GSA 形式（126列）へ変換する。

設計方針
--------
**xT / GridID / ZoneID / LBP は自前で計算しない。** 既存の `xt_pipeline_22` が
すべて持っているので、その手前の「中間形式」を作るところだけを担当する。
既存資産と計算が食い違うのを避けるため。

    PFF (30fps, 中心原点メートル)
      → normalize()      … 正規化 [0,1] ＋ 攻撃方向を Home→x=1 に統一
      → to_intermediate() … frame/time_sec/ball_x/ball_y/Home_n_x/... の横持ち
      → xt_pipeline_22   … assign_grid_and_xt_22 → reformat → add_zone_and_lbp
      → Export_GSA CSV (126列) → app_22 / app_23 が読める

fps について
-----------
アプリ側は `Time` 列の差分から fps を自動判定するので、**30fps のまま投入できる**。
`target_fps` を指定したときだけ間引く（既存の GSA 実績 10fps に揃えたい場合など）。
"""

from __future__ import annotations

import importlib.util as _ilu
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from .loader import MatchMeta, filter_quality, load_meta, load_tracking_window, normalize
from .paths import GameFiles, locate

PITCH_ROOT = Path(__file__).resolve().parent.parent
N_SLOTS = 11


def _load_pipeline():
    """`xt_pipeline_22` を読み込む（パッケージ外のトップレベルモジュール）。"""
    if str(PITCH_ROOT) not in sys.path:
        sys.path.insert(0, str(PITCH_ROOT))
    spec = _ilu.find_spec("xt_pipeline_22")
    if spec is None:
        raise ImportError(f"xt_pipeline_22 が見つかりません（{PITCH_ROOT}）")
    return _ilu.module_from_spec(spec) if spec.loader is None else __import__("xt_pipeline_22")


# ── スロット割当 ──────────────────────────────────────────────────────────────

def assign_slots(df: pd.DataFrame, n_slots: int = N_SLOTS) -> dict[tuple[str, str], int]:
    """(side, shirt) → スロット番号 1..n の対応を決める。

    窓のあいだで一貫している必要があるため、**出現フレーム数の多い順**に
    割り当てる。交代で 12 人以上写る場合は、出番の長い 11 人が優先される。
    """
    mapping: dict[tuple[str, str], int] = {}
    for side in ("home", "away"):
        sub = df[df["side"] == side]
        if sub.empty:
            continue
        order = (sub.groupby("shirt")["frame"].nunique()
                 .sort_values(ascending=False).index.tolist())
        for i, shirt in enumerate(order[:n_slots], start=1):
            mapping[(side, str(shirt))] = i
    return mapping


def slot_legend(df: pd.DataFrame, roster: pd.DataFrame | None,
                meta: MatchMeta, n_slots: int = N_SLOTS) -> pd.DataFrame:
    """スロットと実選手の対応表。どの P 番号が誰かを後から追えるようにする。"""
    slots = assign_slots(df, n_slots)
    rows = []
    for (side, shirt), i in sorted(slots.items(), key=lambda kv: (kv[0][0], kv[1])):
        name, pos = "", ""
        if roster is not None and not roster.empty:
            team = meta.home_name if side == "home" else meta.away_name
            hit = roster[(roster["team_name"] == team) & (roster["shirt"] == str(shirt))]
            if not hit.empty:
                name = hit.iloc[0]["name"]
                pos = hit.iloc[0]["position"]
        rows.append({
            "slot": f"{'Home' if side == 'home' else 'Away'}_P{i}",
            "team": meta.home_name if side == "home" else meta.away_name,
            "shirt": shirt,
            "name": name,
            "position": pos,
            "frames": int(df[(df["side"] == side) & (df["shirt"] == shirt)]["frame"].nunique()),
        })
    return pd.DataFrame(rows).sort_values("slot").reset_index(drop=True)


# ── 中間形式 ──────────────────────────────────────────────────────────────────

def ball_coverage(game_id: int, center_time: float,
                  candidates=(5, 10, 15, 20, 30, 45),
                  files: GameFiles | None = None) -> pd.DataFrame:
    """基準時刻で終わる窓ごとに、ボールが記録されている割合を返す。

    PFF は放送映像由来なので、**ボールがデッドの間は追跡されない**。
    30 秒窓を機械的に取ると、その多くがデッドタイムということが起こる
    （田中のゴールでは直近 12 秒は 100% だが、30 秒窓では 40% だった）。

    シーンを選ぶ前にこれを見て、**プレーが途切れていない長さ**を選ぶ。
    """
    f = files or locate(game_id)
    meta = load_meta(game_id, f)
    longest = max(candidates)
    raw = load_tracking_window(game_id, center_time - longest, center_time + 1.0, f)
    if raw.empty:
        return pd.DataFrame()

    per = raw.groupby("frame").agg(t=("video_time", "first"),
                                   bx=("ball_x_m", "first"))
    rows = []
    for w in candidates:
        m = (per["t"] >= center_time - w) & (per["t"] <= center_time)
        n = int(m.sum())
        if n == 0:
            continue
        ok = int(per.loc[m, "bx"].notna().sum())
        rows.append({"窓(秒)": w, "フレーム数": n,
                     "ボール捕捉率": round(ok / n, 3),
                     "捕捉フレーム": ok})
    return pd.DataFrame(rows)


def interpolate_ball(x: pd.Series, y: pd.Series, fps: float,
                     max_gap_sec: float = 1.0) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ボールの短い欠損を線形補間する。

    PFF は放送映像由来なので、ボールは記録されないフレームが多い
    （田中のゴール前 30 秒では 56% が欠損）。ボールは連続的に動くため、
    **短い欠損なら補間して差し支えない**。ただし長い欠損は「どこにあったか
    分からない」ので埋めない（埋めると存在しない軌跡を作ってしまう）。

    Returns
    -------
    (補間後 x, 補間後 y, 由来フラグ)  由来は "measured" / "interp" / ""
    """
    limit = max(int(round(max_gap_sec * fps)), 1)
    src = pd.Series(np.where(x.notna(), "measured", ""), index=x.index)

    xi = x.interpolate(limit=limit, limit_area="inside")
    yi = y.interpolate(limit=limit, limit_area="inside")
    src[(x.isna()) & (xi.notna())] = "interp"
    return xi, yi, src


def to_intermediate(df_norm: pd.DataFrame, fps: float,
                    goal_time: float | None = None,
                    n_slots: int = N_SLOTS,
                    ball_gap_sec: float = 1.0) -> pd.DataFrame:
    """正規化済みの長形式 → `xt_pipeline_22` が受け取る横持ち中間形式。

    columns = frame, time_sec, ball_x, ball_y, is_goal_frame, ball_possession,
              Home_1_x, Home_1_y … Away_11_x, Away_11_y
    """
    if df_norm.empty:
        return pd.DataFrame()

    frames = np.sort(df_norm["frame"].unique())
    idx = {f: i for i, f in enumerate(frames)}
    t0 = float(df_norm["video_time"].min())

    out = pd.DataFrame({
        "frame": np.arange(1, len(frames) + 1),
        "time_sec": [round((f - frames[0]) / fps, 4) for f in frames],
    })

    # ボールはフレームごとに 1 つ。短い欠損だけ補間する。
    ball = (df_norm.groupby("frame")[["ball_x_norm", "ball_y_norm"]]
            .first().reindex(frames))
    bx, by, bsrc = interpolate_ball(
        ball["ball_x_norm"].reset_index(drop=True),
        ball["ball_y_norm"].reset_index(drop=True),
        fps, ball_gap_sec,
    )
    out["ball_x"] = bx.values
    out["ball_y"] = by.values
    out["ball_source"] = bsrc.values

    # ゴール時刻に最も近いフレームへ印を付ける（extract_goal_window が使う）
    out["is_goal_frame"] = 0
    if goal_time is not None:
        vt = df_norm.groupby("frame")["video_time"].first().reindex(frames).values
        out.loc[int(np.argmin(np.abs(vt - goal_time))), "is_goal_frame"] = 1
    else:
        out.loc[len(out) - 1, "is_goal_frame"] = 1

    out["ball_possession"] = ""

    slots = assign_slots(df_norm, n_slots)
    for side, prefix in (("home", "Home"), ("away", "Away")):
        for i in range(1, n_slots + 1):
            xs = np.full(len(frames), np.nan)
            ys = np.full(len(frames), np.nan)
            shirt = next((s for (sd, s), n in slots.items() if sd == side and n == i), None)
            if shirt is not None:
                sub = df_norm[(df_norm["side"] == side) & (df_norm["shirt"] == shirt)]
                for f, x, y in zip(sub["frame"], sub["x_norm"], sub["y_norm"]):
                    j = idx.get(f)
                    if j is not None:
                        xs[j], ys[j] = x, y
            out[f"{prefix}_{i}_x"] = xs
            out[f"{prefix}_{i}_y"] = ys

    return out


def downsample(df: pd.DataFrame, src_fps: float, target_fps: float) -> tuple[pd.DataFrame, float]:
    """フレームを間引いて目標 fps に近づける。(結果, 実効fps) を返す。

    アプリは fps を自動判定するので通常は不要。既存 GSA 実績（10fps）に
    揃えたいときだけ使う。
    """
    if target_fps <= 0 or target_fps >= src_fps:
        return df.reset_index(drop=True), src_fps
    step = max(int(round(src_fps / target_fps)), 1)
    out = df.iloc[::step].copy().reset_index(drop=True)
    out["frame"] = np.arange(1, len(out) + 1)
    eff = src_fps / step
    out["time_sec"] = (out["frame"] - 1) / eff
    return out, eff


# ── まとめ ────────────────────────────────────────────────────────────────────

def build_export_gsa(
    game_id: int,
    center_time: float,
    window_sec: float = 30.0,
    lead_sec: float | None = None,
    target_fps: float | None = None,
    smoothed: bool = True,
    min_visibility: str | None = None,
    min_confidence: str | None = None,
    xt_map_path: str | Path | None = None,
    files: GameFiles | None = None,
    progress=None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """1 シーンを Export_GSA 形式（126列）にして返す。

    Parameters
    ----------
    center_time : シーンの基準となる動画時刻（秒）。ゴールならその瞬間。
    window_sec  : 切り出す長さ。既定 30 秒。
    lead_sec    : 基準時刻より前を何秒読むか。既定は window_sec + 2 秒。
        `xt_pipeline_22.extract_goal_window` は **基準フレームで終わる窓**を
        取る仕様なので、基準時刻より前を窓長ぶん確保しておく必要がある。
        余分の 2 秒は端でフレームが欠けたときの余裕。
    target_fps  : 指定すると間引く。None なら 29.97 のまま。

    Returns
    -------
    (Export_GSA の DataFrame, スロット対応表, 情報 dict)
    """
    f = files or locate(game_id)
    meta = load_meta(game_id, f)
    lead = window_sec + 2.0 if lead_sec is None else lead_sec
    t0, t1 = center_time - lead, center_time + 1.0

    if progress:
        progress(0.1, f"トラッキング読み込み中… {t0:.0f}〜{t1:.0f} 秒")
    raw = load_tracking_window(game_id, t0, t1, f, smoothed=smoothed)
    if raw.empty:
        # トラッキングが試合の一部しか収録していないことがある。
        # 10506（日本vsクロアチア）は延長までで、PK戦は入っていない。
        raise ValueError(
            f"指定区間（{t0:.1f}〜{t1:.1f} 秒）にトラッキングがありません。"
            "この試合のトラッキングが収録している範囲外の可能性があります"
            "（PK戦などは収録されていないことがあります）。"
        )

    if min_visibility or min_confidence:
        raw = filter_quality(raw, min_visibility, min_confidence)

    if progress:
        progress(0.6, "座標を正規化中…")
    nm = normalize(raw, meta)

    from .loader import load_roster
    try:
        roster = load_roster(game_id, f)
    except Exception:
        roster = None
    legend = slot_legend(nm, roster, meta)

    inter = to_intermediate(nm, meta.fps, goal_time=center_time)
    eff_fps = meta.fps
    if target_fps:
        inter, eff_fps = downsample(inter, meta.fps, target_fps)

    if progress:
        progress(0.8, "xT・ゾーンを付与中…")
    pipe = _load_pipeline()
    xt_path = Path(xt_map_path) if xt_map_path else PITCH_ROOT / "xT_BaseMap_105x68.csv"
    xt_map = pipe.load_xt_map(str(xt_path))

    enriched = pipe.assign_grid_and_xt_22(inter, xt_map)
    window, wmeta = pipe.extract_goal_window(enriched, eff_fps, window_sec=window_sec)
    result = pipe.reformat_to_22player_schema(window, eff_fps, wmeta["window_start_sec"])
    result = pipe.add_zone_and_lbp_columns(result, eff_fps)

    # ボールが実測か補間かを出力にも残す（品質フィルタや重み付けに使う）
    if "ball_source" in window.columns:
        result["Ball_Source"] = window["ball_source"].to_numpy()[:len(result)]

    info = {
        "game_id": game_id,
        "home": meta.home_name,
        "away": meta.away_name,
        "center_time": center_time,
        "window": (t0, t1),
        "fps": eff_fps,
        "frames": len(result),
        "columns": len(result.columns),
        "video_url": meta.video_url,
    }
    if progress:
        progress(1.0, "完了")
    return result, legend, info

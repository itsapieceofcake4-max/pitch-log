"""
pff/enrich.py
=============
Export_GSA（126列）に、GSA へ食わせる特徴量を総ざらいで付与する。

設計 — 3層構造を崩さないこと
----------------------------
    X（物理量）  →  中間Y（xT / 空間支配など）  →  最終Y（実得点）

> **中間Y の計算元になった特徴を X 側に入れてはならない。**
> 入れると中間Y がその特徴の算術関数になり、行動→結果の因果ではなく
> 恒等式を学習してしまう。

そこで本モジュールは列を **カテゴリで明示的に分ける**。

| 接頭辞 | 層 | 中身 |
|---|---|---|
| `X1_` | X | 速度・加速度・走行距離 |
| `X2_` | X | 距離・プレッシャー（ボール/ゴール/相手） |
| `X3_` | X | 陣形（重心・幅・深さ・コンパクトネス・凸包・最終ライン） |
| `X4_` | X | 局所的な数的優位 |
| `Y1_` | 中間Y | xT 由来（**X には入れないこと**） |
| `Y2_` | 中間Y | 空間支配（ボロノイ）— オフボールの寄与が乗りやすい |
| `Y3_` | 中間Y | 前進・侵入（アタッキングサード/ペナルティエリア） |
| `Z_`  | 最終Y | ゴールまでの時間・得点フラグ |
| `Q_`  | 品質 | 実測/推定の割合など。足切りや重み付けに使う |

    from pff.enrich import enrich, feature_catalog
    df2 = enrich(df, fps=29.97)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

PITCH_ROOT = Path(__file__).resolve().parent.parent
if str(PITCH_ROOT) not in sys.path:
    sys.path.insert(0, str(PITCH_ROOT))

PITCH_L, PITCH_W = 105.0, 68.0
SPRINT_MPS = 7.0                    # スプリント判定（サッカー基準 25km/h ≒ 7m/s）
PRESS_RADII = (3.0, 5.0, 10.0)      # プレッシャー判定の半径（m）
ATTACK_THIRD_X = 2.0 / 3.0          # 正規化X。ここより先がアタッキングサード
PENALTY_X = 1.0 - 16.5 / PITCH_L    # ペナルティエリアの外辺
PENALTY_Y_HALF = 20.16 / PITCH_W


# ── 補助 ──────────────────────────────────────────────────────────────────────

def _slots(df: pd.DataFrame, team: str) -> list[str]:
    """"Home_P1" のようなスロット接頭辞を、番号順に返す。"""
    out = {c.rsplit("_", 1)[0] for c in df.columns
           if c.startswith(f"{team}_P") and c.endswith("_X")}
    return sorted(out, key=lambda s: int(s.split("_P")[1]))


def _xy(df: pd.DataFrame, slot: str) -> tuple[np.ndarray, np.ndarray]:
    """スロットの座標をメートルで返す。"""
    return (df[f"{slot}_X"].to_numpy(float) * PITCH_L,
            df[f"{slot}_Y"].to_numpy(float) * PITCH_W)


def _eff_x(x_m: np.ndarray, team: str) -> np.ndarray:
    """そのチームの攻撃方向を基準にした X（0=自陣ゴール, 105=敵陣ゴール）。"""
    return (PITCH_L - x_m) if team == "Away" else x_m


def _smooth(a: np.ndarray, w: int) -> np.ndarray:
    if w < 3 or len(a) < 3:
        return a
    return pd.Series(a).rolling(w, center=True, min_periods=1).mean().to_numpy()


# ── X1: 速度 ──────────────────────────────────────────────────────────────────

def add_kinematics(df: pd.DataFrame, fps: float, smooth_frames: int = 5) -> None:
    """選手ごとの速度・加速度・走行距離を付ける（X1）。

    座標を微分するため、平滑窓は **GSA で読みたい因果ラグより短く**保つこと。
    既定 5 フレーム（29.97fps で 0.17 秒）。
    """
    dt = 1.0 / fps
    t = np.arange(len(df)) * dt
    for team in ("Home", "Away"):
        for slot in _slots(df, team):
            x, y = _xy(df, slot)
            xs, ys = _smooth(x, smooth_frames), _smooth(y, smooth_frames)
            with np.errstate(invalid="ignore"):
                vx = np.gradient(xs, t)
                vy = np.gradient(ys, t)
            sp = np.hypot(vx, vy)
            sp = np.clip(sp, 0, 12.0)                 # 人の上限で頭打ち
            ac = np.gradient(_smooth(sp, smooth_frames), t)
            step = np.zeros(len(df))
            step[1:] = np.hypot(np.diff(xs), np.diff(ys))
            step = np.where(sp >= 0.5, step, 0.0)     # 静止はブレとみなす

            df[f"X1_{slot}_speed"] = np.round(sp, 3)
            df[f"X1_{slot}_accel"] = np.round(np.clip(ac, -8, 8), 3)
            df[f"X1_{slot}_is_sprint"] = (sp >= SPRINT_MPS).astype(int)
            df[f"X1_{slot}_dist_cum"] = np.round(np.nancumsum(step), 2)


# ── X2: 距離・プレッシャー ────────────────────────────────────────────────────

def add_distances(df: pd.DataFrame) -> None:
    """ボール・ゴール・相手との距離、プレッシャー強度を付ける（X2）。"""
    bx = df["Ball_X"].to_numpy(float) * PITCH_L
    by = df["Ball_Y"].to_numpy(float) * PITCH_W

    coords = {t: {s: _xy(df, s) for s in _slots(df, t)} for t in ("Home", "Away")}

    for team, opp in (("Home", "Away"), ("Away", "Home")):
        # 攻撃ゴールの位置（正規化 X の 1 側 / 0 側）
        gx = PITCH_L if team == "Home" else 0.0
        gy = PITCH_W / 2
        for slot in _slots(df, team):
            x, y = coords[team][slot]
            df[f"X2_{slot}_dist_ball"] = np.round(np.hypot(x - bx, y - by), 2)
            df[f"X2_{slot}_dist_goal"] = np.round(np.hypot(x - gx, y - gy), 2)

            # 相手全員との距離行列（この選手 × 相手）
            od = np.vstack([np.hypot(x - ox, y - oy)
                            for ox, oy in coords[opp].values()])
            df[f"X2_{slot}_dist_nearest_opp"] = np.round(np.nanmin(od, axis=0), 2)
            for r in PRESS_RADII:
                df[f"X2_{slot}_opp_within_{int(r)}m"] = np.nansum(od <= r, axis=0)

    # ボール保持者（最も近い選手）とそのプレッシャー
    all_slots = [(t, s) for t in ("Home", "Away") for s in _slots(df, t)]
    dmat = np.vstack([np.hypot(coords[t][s][0] - bx, coords[t][s][1] - by)
                      for t, s in all_slots])
    idx = np.nanargmin(np.where(np.isnan(dmat), np.inf, dmat), axis=0)
    carrier = [all_slots[i][1] for i in idx]
    df["X2_carrier_slot"] = carrier
    df["X2_carrier_team"] = [s.split("_")[0] for s in carrier]
    df["X2_carrier_dist_ball"] = np.round(dmat[idx, np.arange(len(df))], 2)
    df["X2_pressure_on_carrier"] = [
        int(df.iloc[i].get(f"X2_{carrier[i]}_opp_within_3m", 0)) for i in range(len(df))
    ]


# ── X3: 陣形 ──────────────────────────────────────────────────────────────────

def _hull_area(px: np.ndarray, py: np.ndarray) -> float:
    """凸包面積（m²）。3 点未満なら 0。"""
    pts = np.column_stack([px, py])
    pts = pts[~np.isnan(pts).any(axis=1)]
    if len(pts) < 3:
        return 0.0
    try:
        from scipy.spatial import ConvexHull

        return float(ConvexHull(pts).volume)          # 2D では volume が面積
    except Exception:
        return 0.0


def add_shape(df: pd.DataFrame) -> None:
    """チームの重心・幅・深さ・コンパクトネス・凸包・最終ラインを付ける（X3）。"""
    for team in ("Home", "Away"):
        slots = _slots(df, team)
        X = np.vstack([_xy(df, s)[0] for s in slots])   # (n_players, n_frames)
        Y = np.vstack([_xy(df, s)[1] for s in slots])

        df[f"X3_{team}_centroid_x"] = np.round(np.nanmean(X, axis=0), 2)
        df[f"X3_{team}_centroid_y"] = np.round(np.nanmean(Y, axis=0), 2)
        df[f"X3_{team}_width"] = np.round(np.nanmax(Y, axis=0) - np.nanmin(Y, axis=0), 2)
        df[f"X3_{team}_depth"] = np.round(np.nanmax(X, axis=0) - np.nanmin(X, axis=0), 2)

        # コンパクトネス = 重心からの平均距離（小さいほど密集）
        cx, cy = np.nanmean(X, axis=0), np.nanmean(Y, axis=0)
        df[f"X3_{team}_compactness"] = np.round(
            np.nanmean(np.hypot(X - cx, Y - cy), axis=0), 2)

        df[f"X3_{team}_hull_area"] = [
            round(_hull_area(X[:, i], Y[:, i]), 1) for i in range(len(df))
        ]

        # 最終ライン = 自陣ゴールに最も近いフィールドプレーヤー（GK を除くため2番目）
        ex = _eff_x(X, team)
        srt = np.sort(np.where(np.isnan(ex), np.inf, ex), axis=0)
        df[f"X3_{team}_last_line_x"] = np.round(
            np.where(np.isinf(srt[1]), np.nan, srt[1]), 2)

    df["X3_line_gap"] = np.round(
        df["X3_Home_centroid_x"] - df["X3_Away_centroid_x"], 2)


# ── X4: 数的優位 ──────────────────────────────────────────────────────────────

def add_numerical(df: pd.DataFrame, radius: float = 15.0) -> None:
    """ボール周辺の局所的な数的差を付ける（X4）。"""
    bx = df["Ball_X"].to_numpy(float) * PITCH_L
    by = df["Ball_Y"].to_numpy(float) * PITCH_W
    counts = {}
    for team in ("Home", "Away"):
        d = np.vstack([np.hypot(_xy(df, s)[0] - bx, _xy(df, s)[1] - by)
                       for s in _slots(df, team)])
        counts[team] = np.nansum(d <= radius, axis=0)
        df[f"X4_{team}_near_ball_{int(radius)}m"] = counts[team]
    df["X4_numerical_advantage"] = counts["Home"] - counts["Away"]

    # アタッキングサードにいる人数
    for team in ("Home", "Away"):
        ex = np.vstack([_eff_x(_xy(df, s)[0], team) for s in _slots(df, team)])
        df[f"X4_{team}_in_attacking_third"] = np.nansum(
            ex >= ATTACK_THIRD_X * PITCH_L, axis=0)


# ── Y1: xT 由来（中間Y） ──────────────────────────────────────────────────────

def add_xt_targets(df: pd.DataFrame, fps: float) -> None:
    """xT の変化・累積を付ける（Y1）。**X 側には入れないこと。**"""
    for col, name in (("Ball_xT", "ball"), ("Home_MAX_xT", "home_max"),
                      ("Away_MAX_xT", "away_max"), ("Home_SUM_xT", "home_sum"),
                      ("Away_SUM_xT", "away_sum")):
        if col not in df.columns:
            continue
        v = pd.to_numeric(df[col], errors="coerce")
        df[f"Y1_{name}_xT"] = v.round(5)
        df[f"Y1_{name}_xT_delta"] = v.diff().round(5)
        df[f"Y1_{name}_xT_cumgain"] = v.diff().clip(lower=0).cumsum().round(5)

    w = max(int(round(0.5 * fps)), 3)
    if "Ball_xT" in df.columns:
        s = pd.to_numeric(df["Ball_xT"], errors="coerce")
        df["Y1_ball_xT_smooth"] = s.rolling(w, center=True, min_periods=1).mean().round(5)
        df["Y1_ball_xT_peak_so_far"] = s.cummax().round(5)


# ── Y2: 空間支配（中間Y） ────────────────────────────────────────────────────

def add_space_control(df: pd.DataFrame) -> None:
    """ボロノイ分割による支配面積を付ける（Y2）。

    オフボールの動きが最も素直に効く指標。走って空間を作れば面積が増える。
    ラグビー側で実装済みの `rugby.voronoi` をサッカーピッチで使い回す。
    """
    from rugby.pitch_model import SOCCER
    from rugby.voronoi import compute_cells

    home, away = _slots(df, "Home"), _slots(df, "Away")
    hx = np.vstack([_xy(df, s)[0] for s in home])
    hy = np.vstack([_xy(df, s)[1] for s in home])
    ax = np.vstack([_xy(df, s)[0] for s in away])
    ay = np.vstack([_xy(df, s)[1] for s in away])

    n = len(df)
    share_h = np.full(n, np.nan)
    per_slot = {s: np.full(n, np.nan) for s in home + away}
    total = PITCH_L * PITCH_W

    for i in range(n):
        pts, ids, teams = [], [], []
        for j, s in enumerate(home):
            if np.isfinite(hx[j, i]) and np.isfinite(hy[j, i]):
                pts.append((hx[j, i], hy[j, i])); ids.append(s); teams.append(0)
        for j, s in enumerate(away):
            if np.isfinite(ax[j, i]) and np.isfinite(ay[j, i]):
                pts.append((ax[j, i], ay[j, i])); ids.append(s); teams.append(1)
        if len(pts) < 3:
            continue
        cells = compute_cells(np.array(pts), list(range(len(pts))), teams, SOCCER)
        h_area = 0.0
        for c in cells:
            slot = ids[c.track_id]
            per_slot[slot][i] = c.area_m2
            if c.team == 0:
                h_area += c.area_m2
        share_h[i] = h_area / total

    df["Y2_home_space_share"] = np.round(share_h, 4)
    df["Y2_away_space_share"] = np.round(1.0 - share_h, 4)
    for s, v in per_slot.items():
        df[f"Y2_{s}_space_m2"] = np.round(v, 1)


# ── Y3: 前進・侵入（中間Y） ──────────────────────────────────────────────────

def add_progression(df: pd.DataFrame, fps: float) -> None:
    """ボールの前進とエリア侵入を付ける（Y3）。"""
    bx = df["Ball_X"].to_numpy(float)
    by = df["Ball_Y"].to_numpy(float)
    dt = 1.0 / fps

    fwd = np.zeros(len(df))
    fwd[1:] = np.diff(bx) * PITCH_L / dt
    df["Y3_ball_forward_mps"] = np.round(np.clip(fwd, -40, 40), 2)

    # 基準は「最初に観測できた位置」。bx[0] が欠損だと全部 NaN になるため。
    valid = np.flatnonzero(np.isfinite(bx))
    base = bx[valid[0]] if len(valid) else np.nan
    df["Y3_ball_progress_m"] = np.round((bx - base) * PITCH_L, 2)

    in_at = bx >= ATTACK_THIRD_X
    in_pa = (bx >= PENALTY_X) & (np.abs(by - 0.5) <= PENALTY_Y_HALF)
    df["Y3_ball_in_attacking_third"] = in_at.astype(int)
    df["Y3_ball_in_penalty_area"] = in_pa.astype(int)
    df["Y3_attacking_third_entry"] = (in_at & ~np.roll(in_at, 1)).astype(int)
    df["Y3_penalty_area_entry"] = (in_pa & ~np.roll(in_pa, 1)).astype(int)
    df.loc[0, ["Y3_attacking_third_entry", "Y3_penalty_area_entry"]] = 0


# ── Z: 最終Y ─────────────────────────────────────────────────────────────────

def add_outcome(df: pd.DataFrame, fps: float) -> None:
    """ゴールまでの残り時間など、最終Y を付ける（Z）。

    窓は基準フレーム（ゴール等）で終わるので、末尾が 0 秒になる。
    """
    n = len(df)
    df["Z_time_to_goal_sec"] = np.round((np.arange(n) - (n - 1)) / fps * -1, 3)
    df["Z_is_goal_frame"] = 0
    df.loc[n - 1, "Z_is_goal_frame"] = 1
    df["Z_frames_to_goal"] = (n - 1) - np.arange(n)


# ── Q: 品質 ──────────────────────────────────────────────────────────────────

def add_quality(df: pd.DataFrame) -> None:
    """このフレームがどれだけ信用できるかの目安（Q）。"""
    for team in ("Home", "Away"):
        slots = _slots(df, team)
        X = np.vstack([df[f"{s}_X"].to_numpy(float) for s in slots])
        df[f"Q_{team}_tracked"] = np.sum(np.isfinite(X), axis=0)
    df["Q_players_tracked"] = df["Q_Home_tracked"] + df["Q_Away_tracked"]
    if "Ball_Source" in df.columns:
        df["Q_ball_measured"] = (df["Ball_Source"] == "measured").astype(int)
    else:
        df["Q_ball_measured"] = df["Ball_X"].notna().astype(int)


# ── まとめ ────────────────────────────────────────────────────────────────────

def enrich(df: pd.DataFrame, fps: float, space_control: bool = True,
           smooth_frames: int = 5, progress=None) -> pd.DataFrame:
    """Export_GSA に全カテゴリの特徴量を付けて返す。

    `space_control=False` にするとボロノイ計算を省く（フレーム数が多いと重い）。
    """
    # 列を 1 本ずつ足すと DataFrame が断片化して警告が出る。ここでは
    # 可読性を優先して素直に代入し、最後にまとめて作り直す。
    import warnings

    warnings.filterwarnings("ignore", message=".*highly fragmented.*")

    out = df.copy()
    steps = [
        ("X1 速度", lambda: add_kinematics(out, fps, smooth_frames)),
        ("X2 距離・プレッシャー", lambda: add_distances(out)),
        ("X3 陣形", lambda: add_shape(out)),
        ("X4 数的優位", lambda: add_numerical(out)),
        ("Y1 xT由来", lambda: add_xt_targets(out, fps)),
        ("Y3 前進・侵入", lambda: add_progression(out, fps)),
        ("Z 最終Y", lambda: add_outcome(out, fps)),
        ("Q 品質", lambda: add_quality(out)),
    ]
    if space_control:
        steps.insert(5, ("Y2 空間支配", lambda: add_space_control(out)))

    for i, (label, fn) in enumerate(steps):
        if progress:
            progress(i / len(steps), f"{label} を計算中…")
        fn()
    if progress:
        progress(1.0, "完了")
    return out.copy()          # 断片化を解消してから返す


CATEGORY_INFO = [
    ("X1_", "X 物理量", "速度・加速度・スプリント判定・累積走行距離"),
    ("X2_", "X 物理量", "ボール/ゴール/最近接相手との距離、半径内の相手数（プレッシャー）"),
    ("X3_", "X 物理量", "陣形：重心・幅・深さ・コンパクトネス・凸包面積・最終ライン"),
    ("X4_", "X 物理量", "局所的な数的優位、アタッキングサードの人数"),
    ("Y1_", "中間Y", "xT とその変化・累積・平滑・ピーク（**X には入れない**）"),
    ("Y2_", "中間Y", "ボロノイによる空間支配（面積・支配率）。オフボールが効く指標"),
    ("Y3_", "中間Y", "ボールの前進速度・進行距離、アタッキングサード/PA 侵入"),
    ("Z_", "最終Y", "ゴールまでの残り時間・フレーム数、得点フラグ"),
    ("Q_", "品質", "追跡できた人数、ボールが実測か補間か"),
]

# 列名の末尾（サフィックス）ごとの意味と単位。1 列ずつ引けるようにする。
COLUMN_DESC: dict[str, tuple[str, str]] = {
    # X1 速度
    "speed": ("その選手の速さ", "m/s"),
    "accel": ("その選手の加速度。正なら加速、負なら減速", "m/s²"),
    "is_sprint": ("スプリント中か（7m/s＝25km/h 以上）", "0/1"),
    "dist_cum": ("窓の開始からの累積走行距離。静止のブレは加算しない", "m"),
    # X2 距離・プレッシャー
    "dist_ball": ("ボールまでの距離", "m"),
    "dist_goal": ("そのチームが攻めるゴールまでの距離", "m"),
    "dist_nearest_opp": ("最も近い相手選手までの距離。小さいほど密着されている", "m"),
    "opp_within_3m": ("半径3m以内の相手の数。直接的なプレッシャー", "人"),
    "opp_within_5m": ("半径5m以内の相手の数", "人"),
    "opp_within_10m": ("半径10m以内の相手の数。周辺の混雑度", "人"),
    "carrier_slot": ("ボールに最も近い選手のスロット（保持者の推定）", "—"),
    "carrier_team": ("その保持者のチーム", "Home/Away"),
    "carrier_dist_ball": ("保持者とボールの距離。大きいとルーズボール", "m"),
    "pressure_on_carrier": ("保持者の3m以内にいる相手の数", "人"),
    # X3 陣形
    "centroid_x": ("チーム重心のX。前進しているほど大きい", "m"),
    "centroid_y": ("チーム重心のY。左右どちらに寄っているか", "m"),
    "width": ("チームの横幅（最上端と最下端の差）。広いほど幅を使っている", "m"),
    "depth": ("チームの縦幅（最前と最後の差）。大きいほど間延びしている", "m"),
    "compactness": ("重心からの平均距離。小さいほど密集している", "m"),
    "hull_area": ("11人が囲む凸包の面積。陣形が占める面積", "m²"),
    "last_line_x": ("最終ラインの位置（GKを除く最後方）", "m"),
    "line_gap": ("両チーム重心のX差。攻守の押し引き", "m"),
    # X4 数的優位
    "near_ball_15m": ("ボールから15m以内にいる自チームの人数", "人"),
    "numerical_advantage": ("ボール周辺の人数差（Home − Away）。正ならHome優勢", "人"),
    "in_attacking_third": ("アタッキングサードにいる自チームの人数", "人"),
    # Y1 xT
    "xT": ("期待脅威。その位置が得点にどれだけ近いか", "0–1"),
    "xT_delta": ("前フレームからの xT の変化量。前進で正になる", "—"),
    "xT_cumgain": ("xT の増分だけを積み上げた累積。前進の総量", "—"),
    "xT_smooth": ("xT の 0.5 秒移動平均。ノイズを均した推移", "0–1"),
    "xT_peak_so_far": ("窓開始からの xT 最大値", "0–1"),
    # Y2 空間支配
    "space_m2": ("その選手が最も早く到達できる面積（ボロノイ領域）", "m²"),
    "space_share": ("ピッチ全体に占めるそのチームの支配面積の割合", "0–1"),
    # Y3 前進・侵入
    "ball_forward_mps": ("ボールが攻撃方向へ進む速さ。負なら後退", "m/s"),
    "ball_progress_m": ("最初に観測できた位置からの前進距離", "m"),
    # 「in_attacking_third」より先に引かれるよう、より長い鍵で登録している
    "ball_in_attacking_third": ("ボールがアタッキングサードにあるか", "0/1"),
    "ball_in_penalty_area": ("ボールがペナルティエリアにあるか", "0/1"),
    "attacking_third_entry": ("アタッキングサードに入った瞬間", "0/1"),
    "penalty_area_entry": ("ペナルティエリアに入った瞬間", "0/1"),
    # Z 最終Y
    "time_to_goal_sec": ("ゴールまでの残り秒数。末尾が0", "秒"),
    "frames_to_goal": ("ゴールまでの残りフレーム数", "フレーム"),
    "is_goal_frame": ("そのフレームがゴールの瞬間か", "0/1"),
    # Q 品質
    "tracked": ("そのフレームで座標が取れた人数", "人"),
    "players_tracked": ("22人中、座標が取れた人数", "人"),
    "ball_measured": ("ボールが実測か（0なら補間または欠測）", "0/1"),
}


def _describe(col: str) -> tuple[str, str, str]:
    """列名から (対象, 説明, 単位) を引く。"""
    import re

    body = col.split("_", 1)[1] if "_" in col else col

    m = re.match(r"^((?:Home|Away)_P\d+)_(.+)$", body)
    if m:
        subject, suffix = f"選手 {m.group(1)}", m.group(2)
    else:
        m2 = re.match(r"^(Home|Away|home|away|ball)_(.+)$", body)
        if m2:
            subject = {"ball": "ボール"}.get(m2.group(1).lower(),
                                            f"{m2.group(1)} チーム")
            suffix = m2.group(2)
        else:
            subject, suffix = "全体", body

    # 「ball_」を剥がす前（body）を先に引く。剥がした形（suffix）で引くと
    # ball_in_attacking_third が in_attacking_third（＝人数）に化けるため。
    # 鍵は長いものから照合して、より具体的な定義を優先する。
    for cand in (body, suffix):
        for key in sorted(COLUMN_DESC, key=len, reverse=True):
            if cand == key or cand.endswith("_" + key) or cand.startswith(key):
                d, u = COLUMN_DESC[key]
                return subject, d, u
    return subject, "", ""


def feature_catalog(df: pd.DataFrame) -> pd.DataFrame:
    """付与した列の一覧。1 行 = 1 列で、意味・単位・値域まで引ける。

    指標選定の材料になるよう、カテゴリだけでなく **列ごとの説明** を持たせる。
    """
    rows = []
    for col in df.columns:
        cat, layer, group = "基本", "入力", "Export_GSA の元列（座標・GridID・xT 等）"
        for pre, lay, d in CATEGORY_INFO:
            if col.startswith(pre):
                cat, layer, group = pre.rstrip("_"), lay, d
                break
        subject, desc, unit = _describe(col) if cat != "基本" else ("", "", "")
        s = pd.to_numeric(df[col], errors="coerce")
        rows.append({
            "列名": col, "層": layer, "カテゴリ": cat,
            "対象": subject, "内容": desc, "単位": unit,
            "カテゴリ概要": group,
            "欠損率": round(df[col].isna().mean(), 3),
            "最小": round(s.min(), 3) if s.notna().any() else None,
            "最大": round(s.max(), 3) if s.notna().any() else None,
        })
    return pd.DataFrame(rows)

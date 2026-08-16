"""
rugby/physical.py
=================
モジュール4: フィジカルデータ（走行距離・速度・スプリント回数）の算出。

トラッキング座標から速度・距離を出すときの最大の敵は、検出枠の微小なブレ
（ジッター）である。選手が止まっていても枠が数ピクセル揺れるだけで「常に動いて
いる」と判定され、走行距離も速度も跳ね上がる。そこで本モジュールでは

    ① 座標を平滑化してから微分する
    ② 速度側にも平滑化をかけてスパイクを潰す
    ③ 歩行未満の速度は距離に加算しない（デッドバンド）
    ④ スプリントは「閾値超え」が一定時間continuousに続いた場合のみ計数する

の 4 段でノイズを落とす。閾値とウィンドウはすべて `PhysicalConfig` で外から
調整できる。
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np
import pandas as pd
from scipy.signal import savgol_filter


KMH = 3.6                      # m/s → km/h


@dataclass
class PhysicalConfig:
    """算出パラメータ。競技・映像品質に応じて調整する。

    既定値はサッカーの一般的なフィジカル分析基準（スプリント 24km/h 以上が
    1 秒継続）に合わせてある。ラグビーで使う場合はスプリント閾値を下げる
    ことが多い（フォワードは 20km/h 前後で運用するチームもある）。
    """

    pos_smooth_sec: float = 0.4        # 座標平滑化の窓（秒）
    speed_smooth_sec: float = 1.0      # 速度平滑化の窓（秒）1〜2秒推奨
    deadband_mps: float = 0.5          # これ未満は静止とみなし距離に加算しない
    sprint_kmh: float = 24.0           # スプリント速度閾値
    sprint_min_sec: float = 1.0        # 閾値超えが継続すべき時間
    max_speed_mps: float = 11.0        # 物理上限（これを超える値は異常として丸める）
    use_savgol: bool = True            # True=Savitzky-Golay / False=移動平均


def _odd_window(n_sec: float, dt: float, minimum: int = 3) -> int:
    """秒数を奇数フレーム数へ変換する（savgol は奇数窓を要求する）。"""
    w = int(round(n_sec / dt))
    w = max(w, minimum)
    return w if w % 2 == 1 else w + 1


def _smooth(a: np.ndarray, window: int, use_savgol: bool) -> np.ndarray:
    """1 次元系列を平滑化する。系列が窓より短い場合は素通しする。"""
    if len(a) < 3 or window < 3:
        return a
    w = min(window, len(a) if len(a) % 2 == 1 else len(a) - 1)
    if w < 3:
        return a
    if use_savgol:
        # polyorder=2 で山と谷の形（加速・減速）を残しつつ高周波だけ落とす
        return savgol_filter(a, w, polyorder=min(2, w - 1))
    return pd.Series(a).rolling(w, center=True, min_periods=1).mean().to_numpy()


# ── 選手ごとの時系列 ──────────────────────────────────────────────────────────

def compute_kinematics(
    df: pd.DataFrame, dt: float, cfg: PhysicalConfig | None = None
) -> pd.DataFrame:
    """長形式のトラッキングに、平滑化済みの速度と区間距離を付与して返す。

    Parameters
    ----------
    df : `pipeline.process_window` の出力（frame / track_id / x_m / y_m / kind）
    dt : フレーム間隔（秒）

    Returns
    -------
    元の列 + `speed_mps` / `speed_kmh` / `step_dist_m`（デッドバンド適用後）
    """
    cfg = cfg or PhysicalConfig()
    out = df[df["kind"] == "player"].copy() if "kind" in df.columns else df.copy()
    if out.empty:
        return out

    pos_w = _odd_window(cfg.pos_smooth_sec, dt)
    spd_w = _odd_window(cfg.speed_smooth_sec, dt)

    parts = []
    for _, g in out.groupby("track_id", sort=False):
        g = g.sort_values("frame").copy()
        t = g["frame"].to_numpy(float) * dt
        x = g["x_m"].to_numpy(float)
        y = g["y_m"].to_numpy(float)
        n = len(g)

        if n < 2:
            g["speed_mps"] = 0.0
            g["step_dist_m"] = 0.0
            parts.append(g)
            continue

        # トラックを「連続かつ物理的に妥当な区間」へ割る。区切る条件は 2 つ:
        #   ① 物理的にありえない変位 = ID 取り違えや遮蔽明けの飛び
        #   ② フレームの欠測 = その間に何が起きたか分からない
        # ②を無視して平滑化すると、欠測をまたいで補間したことになり、
        # 最高速度が数十 km/h に化ける（Savitzky-Golay は端で外挿的に振れる）。
        frames = g["frame"].to_numpy(float)
        step = np.hypot(np.diff(x), np.diff(y))
        span = np.maximum(np.diff(t), 1e-6)
        jump = np.zeros(n, dtype=bool)
        jump[1:] = (step > cfg.max_speed_mps * span) | (np.diff(frames) > 1)
        seg = np.cumsum(jump)

        v = np.zeros(n)
        d = np.zeros(n)
        # 平滑化窓に満たない断片は速度を推定できない（推定するとノイズが乗る）
        min_seg = max(pos_w, 3)

        for s in np.unique(seg):
            m = seg == s
            k = int(m.sum())
            if k < min_seg:
                continue
            xs = _smooth(x[m], pos_w, cfg.use_savgol)
            ys = _smooth(y[m], pos_w, cfg.use_savgol)
            ts = t[m]

            vs = np.hypot(np.gradient(xs, ts), np.gradient(ys, ts))
            vs = _smooth(vs, spd_w, cfg.use_savgol)
            v[m] = np.clip(vs, 0.0, cfg.max_speed_mps)

            ds = np.zeros(k)
            ds[1:] = np.hypot(np.diff(xs), np.diff(ys))
            gap = np.zeros(k)
            gap[1:] = np.diff(ts)
            # 静止（デッドバンド未満）と、欠測を挟んだ区間は距離に足さない
            ds = np.where((v[m] >= cfg.deadband_mps) & (gap <= dt * 3), ds, 0.0)
            d[m] = ds

        g["speed_mps"] = np.round(v, 3)
        g["step_dist_m"] = np.round(d, 4)
        g["segment"] = seg
        parts.append(g)

    res = pd.concat(parts, ignore_index=True)
    res["speed_kmh"] = (res["speed_mps"] * KMH).round(2)
    return res.sort_values(["frame", "track_id"]).reset_index(drop=True)


def _count_sprints(speed_mps: np.ndarray, dt: float, cfg: PhysicalConfig) -> tuple[int, float]:
    """閾値超えが `sprint_min_sec` 以上continuousに続いた回数と、その合計秒数。"""
    thr = cfg.sprint_kmh / KMH
    need = max(int(round(cfg.sprint_min_sec / dt)), 1)

    over = speed_mps >= thr
    count = 0
    total = 0.0
    run = 0
    for flag in over:
        if flag:
            run += 1
        else:
            if run >= need:
                count += 1
                total += run * dt
            run = 0
    if run >= need:                     # 末尾で終わっている場合
        count += 1
        total += run * dt
    return count, round(total, 2)


# ── 集計レポート ──────────────────────────────────────────────────────────────

def physical_report(
    df: pd.DataFrame, dt: float, cfg: PhysicalConfig | None = None
) -> pd.DataFrame:
    """選手（track_id）ごとのフィジカル集計を返す。

    Returns
    -------
    columns = [track_id, team_id, jersey, total_distance_m, top_speed_kmh,
               avg_speed_kmh, sprint_count, sprint_time_sec,
               distance_per_min_m, frames, duration_sec]

    `avg_speed_kmh` は停止時間（デッドバンド未満）を除いた平均。
    """
    cfg = cfg or PhysicalConfig()
    kin = compute_kinematics(df, dt, cfg)
    if kin.empty:
        return pd.DataFrame()

    rows = []
    for tid, g in kin.groupby("track_id", sort=False):
        v = g["speed_mps"].to_numpy(float)
        moving = v >= cfg.deadband_mps
        dur = len(g) * dt
        n_sprint, sprint_sec = _count_sprints(v, dt, cfg)
        dist = float(g["step_dist_m"].sum())

        team = g["team"].dropna()
        jersey = g["jersey"].dropna() if "jersey" in g.columns else pd.Series(dtype=object)

        rows.append({
            "track_id": int(tid),
            "team_id": int(team.mode().iloc[0]) if not team.empty else None,
            "jersey": jersey.iloc[0] if not jersey.empty else None,
            "total_distance_m": round(dist, 1),
            "top_speed_kmh": round(float(v.max()) * KMH, 2),
            "avg_speed_kmh": round(float(v[moving].mean()) * KMH, 2) if moving.any() else 0.0,
            "sprint_count": n_sprint,
            "sprint_time_sec": sprint_sec,
            "distance_per_min_m": round(dist / dur * 60, 1) if dur > 0 else 0.0,
            "frames": int(len(g)),
            "duration_sec": round(dur, 2),
            # 断絶が多いトラックは ID 取り違えの疑いがある（信頼度の目安）
            "discontinuities": int(g["segment"].nunique() - 1) if "segment" in g else 0,
        })

    return (pd.DataFrame(rows)
            .sort_values("total_distance_m", ascending=False)
            .reset_index(drop=True))


def config_summary(cfg: PhysicalConfig) -> pd.DataFrame:
    """使用した閾値を書き出す（レポートの再現性のため）。"""
    return pd.DataFrame(
        [{"パラメータ": k, "値": v} for k, v in asdict(cfg).items()]
    )

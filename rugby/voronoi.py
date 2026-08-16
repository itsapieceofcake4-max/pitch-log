"""
rugby/voronoi.py
================
モジュール5: ボロノイ図による空間支配の可視化。

ピッチ上の各地点を「最も近い選手の領土」として分割し、どちらのチームがどれだけ
の空間を支配しているかを見る。

実装上の要点
------------
`scipy.spatial.Voronoi` は外周の母点に対して **無限遠へ伸びる領域** を返す
（`region` に -1 が含まれる）。そのままでは描画も面積計算もできないので、
ピッチ矩形との論理積を取って有界化する必要がある。

ここでは無限領域を再構成する代わりに、**母点をピッチ外側へ鏡像反転させて
追加する**手法を使う。こうすると元の母点の領域はすべて有界になり、
`-1` を含む領域を扱わずに済む。そのうえで shapely でピッチ矩形とクリップする。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import Voronoi
from shapely.geometry import Polygon, box

from .pitch_model import PitchSpec


@dataclass
class VoronoiCell:
    """1 選手ぶんの支配領域。"""

    track_id: int
    team: int | None
    polygon: np.ndarray            # (N, 2) ピッチ座標の頂点列
    area_m2: float


def pitch_rect(spec: PitchSpec, include_in_goal: bool = False) -> Polygon:
    """クリッピングに使うピッチ矩形。

    既定ではインゴールを含めない（フィールドオブプレーのみ）。空間支配の
    議論はふつうフィールド内で行うため。
    """
    x0 = spec.x_min if include_in_goal else 0.0
    x1 = spec.x_max if include_in_goal else spec.length
    return box(x0, 0.0, x1, spec.width)


def compute_cells(
    points: np.ndarray,
    track_ids: list[int],
    teams: list[int | None],
    spec: PitchSpec,
    include_in_goal: bool = False,
) -> list[VoronoiCell]:
    """ボロノイ分割してピッチ枠でクリップしたセル群を返す。

    Parameters
    ----------
    points : (N, 2) ピッチ座標（メートル）
    track_ids, teams : points と同じ長さ

    母点が 3 未満、または全点が同一直線上にある場合は空リストを返す
    （ボロノイ分割が定義できないため）。
    """
    pts = np.asarray(points, dtype=float).reshape(-1, 2)
    if len(pts) < 3:
        return []

    bounds = pitch_rect(spec, include_in_goal)
    x0, y0, x1, y1 = bounds.bounds

    # ピッチ外へ鏡像反転した母点を足して、元の母点の領域をすべて有界にする。
    mirrored = np.vstack([
        pts,
        np.column_stack([2 * x0 - pts[:, 0], pts[:, 1]]),   # 左へ反転
        np.column_stack([2 * x1 - pts[:, 0], pts[:, 1]]),   # 右へ反転
        np.column_stack([pts[:, 0], 2 * y0 - pts[:, 1]]),   # 下へ反転
        np.column_stack([pts[:, 0], 2 * y1 - pts[:, 1]]),   # 上へ反転
    ])

    try:
        vor = Voronoi(mirrored)
    except Exception:
        # 同一直線上・重複点などで分割が定義できない
        return []

    cells: list[VoronoiCell] = []
    for i in range(len(pts)):
        region = vor.regions[vor.point_region[i]]
        if not region or -1 in region:
            continue
        poly = Polygon(vor.vertices[region])
        if not poly.is_valid:
            poly = poly.buffer(0)
        clipped = poly.intersection(bounds)
        if clipped.is_empty or clipped.geom_type != "Polygon":
            continue
        coords = np.asarray(clipped.exterior.coords)
        cells.append(VoronoiCell(
            track_id=int(track_ids[i]),
            team=teams[i],
            polygon=coords,
            area_m2=float(clipped.area),
        ))

    return cells


def cells_for_frame(
    df_frame, spec: PitchSpec, include_in_goal: bool = False
) -> list[VoronoiCell]:
    """1 フレーム分の DataFrame からセルを計算する。

    審判・チーム未判別（team が NaN）とピッチ外の座標は母点から除外する。
    """
    d = df_frame[df_frame["kind"] == "player"] if "kind" in df_frame.columns else df_frame
    d = d[d["team"].notna()]
    if d.empty:
        return []

    x0 = spec.x_min if include_in_goal else 0.0
    x1 = spec.x_max if include_in_goal else spec.length
    d = d[(d["x_m"].between(x0, x1)) & (d["y_m"].between(0.0, spec.width))]
    if len(d) < 3:
        return []

    return compute_cells(
        d[["x_m", "y_m"]].to_numpy(float),
        d["track_id"].astype(int).tolist(),
        [int(t) for t in d["team"].tolist()],
        spec,
        include_in_goal,
    )


def dominance(cells: list[VoronoiCell], spec: PitchSpec,
              include_in_goal: bool = False) -> dict[int | None, float]:
    """チーム別の空間支配率（0–1）。"""
    total = pitch_rect(spec, include_in_goal).area
    out: dict[int | None, float] = {}
    for c in cells:
        out[c.team] = out.get(c.team, 0.0) + c.area_m2
    return {k: round(v / total, 4) for k, v in out.items()}


def dominance_series(df, spec: PitchSpec, include_in_goal: bool = False):
    """全フレームのチーム別支配率を時系列で返す（DataFrame）。"""
    import pandas as pd

    rows = []
    for f, g in df.groupby("frame", sort=True):
        cells = cells_for_frame(g, spec, include_in_goal)
        if not cells:
            continue
        dom = dominance(cells, spec, include_in_goal)
        rows.append({
            "frame": int(f),
            "time_sec": float(g["time_sec"].iloc[0]) if "time_sec" in g.columns else None,
            "team0_share": dom.get(0, 0.0),
            "team1_share": dom.get(1, 0.0),
        })
    return pd.DataFrame(rows)

"""
pff/quality.py
==============
Task 3: トラッキング品質の実測。

なぜ測るか
----------
PFF は **放送映像由来（ブロードキャストトラッキング）** である。カメラがボールを
追うため、ボールから離れた選手ほど画面に映らず、座標が推定値（`ESTIMATED`）に
なる。オフボールの貢献を目的関数にする以上、この特性は致命的になりうる。

SkillCorner の公表値（試合全体 51.2% が実測）と比較できる形で出す。

    python -m pff.quality --game 3854
"""

from __future__ import annotations

import argparse
import bz2
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .loader import _first_ball, load_meta
from .paths import JAPAN_GAMES, locate

# ボールからの距離帯（SkillCorner の公表値と揃えた区切り）
BANDS = [(0, 5), (5, 10), (10, 15), (15, 20), (20, 30), (30, 40), (40, 50), (50, 999)]
SKILLCORNER_REF = {"0-5": 87.0, "15-20": 65.0, "30-40": 27.9, "50+": 7.9, "全体": 51.2}


def _band_label(d: float) -> str:
    for lo, hi in BANDS:
        if lo <= d < hi:
            return f"{lo}-{hi}" if hi < 999 else f"{lo}+"
    return "50+"


def measure(game_id: int, stride: int = 10, limit: int | None = None,
            progress=None) -> dict:
    """1 試合の品質を実測する。

    Parameters
    ----------
    stride : 何フレームおきに測るか。10 なら約 3fps 相当で全体を走査する。
        全 17 万フレームを 1 つずつ見る必要はなく、統計値は変わらない。
    limit  : 走査するフレーム数の上限（動作確認用）。

    Returns
    -------
    {"overall": {...}, "by_band": DataFrame, "per_frame": {...}}
    """
    f = locate(game_id)
    if not f.tracking:
        raise FileNotFoundError(f"Tracking が見つかりません: game_id={game_id}")

    n_vis = n_tot = 0
    conf_counts: dict[str, int] = {}
    band_vis: dict[str, int] = {}
    band_tot: dict[str, int] = {}
    per_frame_vis: list[int] = []
    n_frames = n_ball_missing = 0

    with bz2.open(str(f.tracking), "rt", encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i % stride:
                continue
            if limit and n_frames >= limit:
                break
            fr = json.loads(line)
            n_frames += 1

            b = _first_ball(fr.get("balls"))
            bx, by = b.get("x"), b.get("y")
            has_ball = bx is not None and by is not None
            if not has_ball:
                n_ball_missing += 1

            vis_here = 0
            for side in ("homePlayers", "awayPlayers"):
                for p in fr.get(side) or []:
                    x, y = p.get("x"), p.get("y")
                    if x is None or y is None:
                        continue
                    n_tot += 1
                    vis = p.get("visibility") == "VISIBLE"
                    n_vis += int(vis)
                    vis_here += int(vis)
                    c = p.get("confidence") or "?"
                    conf_counts[c] = conf_counts.get(c, 0) + 1

                    if has_ball:
                        d = float(np.hypot(float(x) - float(bx), float(y) - float(by)))
                        lb = _band_label(d)
                        band_tot[lb] = band_tot.get(lb, 0) + 1
                        band_vis[lb] = band_vis.get(lb, 0) + int(vis)

            per_frame_vis.append(vis_here)
            if progress and n_frames % 2000 == 0:
                progress(n_frames)

    order = [f"{lo}-{hi}" if hi < 999 else f"{lo}+" for lo, hi in BANDS]
    rows = []
    for lb in order:
        tot = band_tot.get(lb, 0)
        if tot == 0:
            continue
        rows.append({
            "距離帯(m)": lb,
            "実測率(%)": round(band_vis.get(lb, 0) / tot * 100, 1),
            "サンプル数": tot,
            "SkillCorner(%)": SKILLCORNER_REF.get(lb),
        })
    by_band = pd.DataFrame(rows)

    pf = np.array(per_frame_vis) if per_frame_vis else np.array([0])
    meta = load_meta(game_id, f)
    return {
        "overall": {
            "game_id": game_id,
            "match": f"{meta.home_name} vs {meta.away_name}",
            "走査フレーム数": n_frames,
            "選手サンプル数": n_tot,
            "実測率(%)": round(n_vis / n_tot * 100, 1) if n_tot else 0.0,
            "SkillCorner実測率(%)": SKILLCORNER_REF["全体"],
            "ボール欠損率(%)": round(n_ball_missing / n_frames * 100, 1) if n_frames else 0.0,
        },
        "confidence": {k: round(v / n_tot * 100, 1) for k, v in
                       sorted(conf_counts.items(), key=lambda kv: -kv[1])} if n_tot else {},
        "per_frame": {
            "実測人数_中央値": int(np.median(pf)),
            "実測人数_最小": int(pf.min()),
            "実測人数_最大": int(pf.max()),
            "22人中の実測割合(%)": round(float(np.median(pf)) / 22 * 100, 1),
        },
        "by_band": by_band,
    }


def report(game_id: int, stride: int = 10) -> str:
    """人が読める形の要約を返す。"""
    r = measure(game_id, stride)
    lines = [f"=== 品質実測: {r['overall']['match']} (game_id={game_id}) ==="]
    for k, v in r["overall"].items():
        if k not in ("game_id", "match"):
            lines.append(f"  {k}: {v}")
    lines.append(f"  confidence 内訳(%): {r['confidence']}")
    lines.append("")
    lines.append("  1フレームあたりの実測人数:")
    for k, v in r["per_frame"].items():
        lines.append(f"    {k}: {v}")
    lines.append("")
    lines.append("  ボールからの距離帯別 実測率:")
    lines.append("    " + r["by_band"].to_string(index=False).replace("\n", "\n    "))
    return "\n".join(lines)


def main() -> None:
    import io
    import sys

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="PFF トラッキングの品質を実測する")
    ap.add_argument("--game", type=int, help="game_id。省略で日本戦4試合")
    ap.add_argument("--stride", type=int, default=10, help="何フレームおきに測るか")
    args = ap.parse_args()

    games = [args.game] if args.game else list(JAPAN_GAMES)
    for gid in games:
        try:
            print(report(gid, args.stride))
            print()
        except Exception as e:
            print(f"  {gid}: 失敗 {e}\n")


if __name__ == "__main__":
    main()

"""
pff/batch.py
============
複数シーンをまとめて書き出す。**GSA の正解パターンを一式そろえる**ための道具。

1 シーンずつ画面で選ぶのは確認向き。正解例を何本も作る段階では、
「日本戦 4 試合のゴール全部」のように一括で出したほうが早い。

    python -m pff.batch --out C:\\pff_scenes                 # 日本戦の全ゴール
    python -m pff.batch --out C:\\pff_scenes --kinds ゴール 決定機
    python -m pff.batch --out C:\\pff_scenes --game 3854 --window 12

窓の長さについて
----------------
PFF はボールがデッドの間は追跡しないため、機械的に 30 秒を取ると大半が
デッドタイムということが起こる。既定では `--window auto` として
**ボール捕捉率が 95% を保てる最長の窓**を自動で選ぶ。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

from .convert import ball_coverage, build_export_gsa
from .enrich import enrich, feature_catalog
from .paths import JAPAN_GAMES
from .scenes import build_all

WINDOW_CANDIDATES = (5, 8, 10, 12, 15, 20, 30)
MIN_COVERAGE = 0.95


def pick_window(game_id: int, center_time: float,
                min_coverage: float = MIN_COVERAGE,
                fallback: float = 12.0) -> tuple[float, float]:
    """ボール捕捉率を保てる最長の窓を選ぶ。(窓秒, その捕捉率) を返す。"""
    try:
        cov = ball_coverage(game_id, center_time, WINDOW_CANDIDATES)
    except Exception:
        return fallback, float("nan")
    if cov.empty:
        return fallback, float("nan")
    ok = cov[cov["ボール捕捉率"] >= min_coverage]
    if ok.empty:
        best = cov.loc[cov["ボール捕捉率"].idxmax()]
        return float(best["窓(秒)"]), float(best["ボール捕捉率"])
    row = ok.loc[ok["窓(秒)"].idxmax()]
    return float(row["窓(秒)"]), float(row["ボール捕捉率"])


def _safe(text: str) -> str:
    """ファイル名に使える形へ。"""
    bad = '\\/:*?"<>|'
    out = "".join("_" if c in bad else c for c in str(text))
    return out.replace(" ", "_").strip("_")[:60]


def export_scenes(
    scenes: pd.DataFrame,
    out_dir: str | Path,
    window: float | str = "auto",
    with_features: bool = True,
    space_control: bool = True,
    progress=None,
) -> pd.DataFrame:
    """シーン一覧を受け取り、1 行 1 ファイルで書き出す。

    Returns
    -------
    書き出し結果の一覧（成否・行数・列数・窓・捕捉率つき）
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = []
    total = len(scenes)
    for i, (_, sc) in enumerate(scenes.iterrows(), start=1):
        gid = int(sc["game_id"])
        t = float(sc["event_time"])
        label = f"{gid}_{_safe(sc.get('player') or sc['kind'])}_{int(t)}s"
        if progress:
            progress(i / total, f"[{i}/{total}] {label}")

        rec = {"game_id": gid, "kind": sc["kind"], "player": sc.get("player"),
               "clock": sc.get("clock"), "event_time": t}
        try:
            if window == "auto":
                w, cov = pick_window(gid, t)
            else:
                w, cov = float(window), float("nan")
            rec["窓(秒)"] = w
            rec["ボール捕捉率"] = round(cov, 3) if cov == cov else None

            df, legend, info = build_export_gsa(gid, t, window_sec=w)
            target = df
            if with_features:
                target = enrich(df, info["fps"], space_control=space_control)

            stem = out_dir / label
            target.to_csv(f"{stem}.csv", index=False, encoding="utf-8-sig")
            if legend is not None and not legend.empty:
                legend.to_csv(f"{stem}_legend.csv", index=False, encoding="utf-8-sig")

            # ボールが 1 フレームも取れていない窓は、そのままでは
            # ボール由来の指標（距離・前進・保持者）がすべて欠測になる。
            note = "OK"
            if cov == cov and cov < 0.5:
                note = f"要確認（ボール捕捉率 {cov:.0%}）"
            rec.update(行数=len(target), 列数=target.shape[1],
                       ファイル=f"{label}.csv", 結果=note)
        except Exception as e:
            rec.update(行数=None, 列数=None, ファイル=None,
                       結果=f"失敗: {type(e).__name__}: {e}")
        rows.append(rec)

    result = pd.DataFrame(rows)
    result.to_csv(out_dir / "_index.csv", index=False, encoding="utf-8-sig")

    # 指標の説明は 1 つ作れば全ファイル共通なので、代表から出す。
    # 「要確認」も出力自体は成功しているので対象に含める。
    ok = result[~result["結果"].astype(str).str.startswith("失敗")]
    if with_features and not ok.empty:
        try:
            sample = pd.read_csv(out_dir / ok.iloc[0]["ファイル"])
            feature_catalog(sample).to_csv(
                out_dir / "_指標データ辞書.csv", index=False, encoding="utf-8-sig")
        except Exception:
            pass

    return result


def main() -> None:
    import io

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(
        description="正解パターン用に、複数シーンをまとめて書き出す")
    ap.add_argument("--out", required=True, help="出力フォルダ")
    ap.add_argument("--game", type=int, help="game_id。省略で日本戦4試合")
    ap.add_argument("--kinds", nargs="*", default=["ゴール"],
                    help="対象の種別（既定: ゴール）")
    ap.add_argument("--window", default="auto",
                    help="窓の秒数。auto なら捕捉率95%%を保てる最長を自動選択")
    ap.add_argument("--no-features", action="store_true",
                    help="座標のみ（127列）で出す")
    ap.add_argument("--no-space", action="store_true",
                    help="ボロノイ（空間支配）を省いて高速化")
    args = ap.parse_args()

    ids = [args.game] if args.game else list(JAPAN_GAMES)
    cat = build_all(ids)
    if cat.empty:
        print("シーンが見つかりませんでした。")
        return
    scenes = cat[cat["kind"].isin(args.kinds)] if args.kinds else cat
    if scenes.empty:
        print(f"該当なし（種別: {args.kinds}）。利用できる種別: "
              f"{sorted(cat['kind'].unique())}")
        return

    print(f"対象 {len(scenes)} シーン → {args.out}")
    res = export_scenes(
        scenes, args.out, window=args.window,
        with_features=not args.no_features, space_control=not args.no_space,
        progress=lambda f, m: print(f"  [{f*100:5.1f}%] {m}"),
    )

    status = res["結果"].astype(str)
    done = (~status.str.startswith("失敗")).sum()
    warn = status.str.startswith("要確認").sum()
    print(f"\n完了: {done}/{len(res)} 件"
          + (f"（うち {warn} 件はボール捕捉率が低く要確認）" if warn else ""))
    cols = [c for c in ("game_id", "kind", "player", "clock", "窓(秒)",
                        "ボール捕捉率", "行数", "列数", "結果") if c in res.columns]
    print(res[cols].to_string(index=False))
    print(f"\n一覧: {Path(args.out) / '_index.csv'}")


if __name__ == "__main__":
    main()

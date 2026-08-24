"""
pff/scenes.py
=============
イベントデータから「解析候補シーン」の一覧を作る。

どのシーンを GSA の正解パターンにするかは人が決める。ここはその**選定材料**を
並べるところ。ゴール・シュートだけでなく、PFF アナリストが付けた
`opportunityType`（決定機の質）と `linesBrokenType`（ライン突破）を拾う。

    python -m pff.scenes                 # 日本戦4試合ぶんを一覧
    python -m pff.scenes --game 3854     # 1試合だけ
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .loader import load_meta
from .paths import JAPAN_GAMES, locate

# 決定機の質（PFF の定義）
OPPORTUNITY_LABEL = {
    "C": "決定機",
    "H": "ハーフチャンス",
    "D": "危険な位置",
    "P": "相手に与えた",
}
# 突破したライン
LINES_LABEL = {
    "A": "攻撃ライン", "M": "中盤ライン", "D": "守備ライン",
    "AM": "攻撃+中盤", "MD": "中盤+守備", "AMD": "全ライン",
}
SHOT_OUTCOME_LABEL = {
    "G": "ゴール", "S": "枠内", "O": "枠外", "B": "ブロック",
}
# 重要度。大きいほど優先的に見るべきシーン。
KIND_PRIORITY = {"ゴール": 100, "決定機": 80, "シュート": 60,
                 "ハーフチャンス": 50, "ライン突破": 30, "危険な位置": 25}


def build_catalog(game_id: int, min_priority: int = 0) -> pd.DataFrame:
    """1 試合のシーン候補を返す。

    Returns
    -------
    columns = [game_id, match, kind, detail, event_time, clock, period,
               team, player, ball_x, ball_y, priority, video_url]
    `event_time` をそのまま `build_export_gsa(center_time=...)` に渡せる。
    """
    f = locate(game_id)
    if not f.event:
        raise FileNotFoundError(f"Event が見つかりません: game_id={game_id}")
    meta = load_meta(game_id, f)
    raw = json.loads(Path(f.event).read_text(encoding="utf-8"))

    rows = []
    for e in raw:
        ge = e.get("gameEvents") or {}
        pe = e.get("possessionEvents") or {}
        t = e.get("eventTime")
        if t is None:
            continue

        team = meta.home_name if ge.get("homeTeam") else meta.away_name
        player = ge.get("playerName") or ""
        ball = (e.get("ball") or [{}])
        b = ball[0] if ball else {}

        # 1 イベントが複数の観点で候補になりうるので、該当するものを全部出す
        cands: list[tuple[str, str]] = []

        outcome = pe.get("shotOutcomeType")
        if pe.get("possessionEventType") == "SH" or outcome:
            if outcome == "G":
                cands.append(("ゴール", SHOT_OUTCOME_LABEL.get(outcome, outcome or "")))
            else:
                cands.append(("シュート", SHOT_OUTCOME_LABEL.get(outcome, outcome or "")))

        opp = pe.get("opportunityType")
        if opp:
            label = OPPORTUNITY_LABEL.get(opp, opp)
            if label in ("決定機", "ハーフチャンス"):
                cands.append((label, f"opportunity={opp}"))
            else:
                cands.append(("危険な位置", label))

        lb = pe.get("linesBrokenType")
        if lb:
            cands.append(("ライン突破", LINES_LABEL.get(lb, lb)))

        for kind, detail in cands:
            pri = KIND_PRIORITY.get(kind, 10)
            if pri < min_priority:
                continue
            rows.append({
                "game_id": game_id,
                "match": f"{meta.home_name} vs {meta.away_name}",
                "kind": kind,
                "detail": detail,
                "event_time": round(float(t), 2),
                "clock": ge.get("startFormattedGameClock"),
                "period": ge.get("period"),
                "team": team,
                "player": player,
                "ball_x": b.get("x"),
                "ball_y": b.get("y"),
                "priority": pri,
                "video_url": pe.get("eventVideoUrl") or ge.get("eventVideoUrl"),
            })

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return (df.sort_values(["priority", "event_time"], ascending=[False, True])
            .reset_index(drop=True))


def build_all(game_ids=None, min_priority: int = 0) -> pd.DataFrame:
    """複数試合をまとめて一覧にする。既定は日本戦 4 試合。"""
    ids = list(game_ids) if game_ids else list(JAPAN_GAMES)
    parts = []
    for gid in ids:
        try:
            d = build_catalog(gid, min_priority)
            if not d.empty:
                parts.append(d)
        except Exception as e:
            print(f"  警告: game_id={gid} を読めませんでした（{e}）")
    if not parts:
        return pd.DataFrame()
    return (pd.concat(parts, ignore_index=True)
            .sort_values(["priority", "game_id", "event_time"], ascending=[False, True, True])
            .reset_index(drop=True))


def main() -> None:
    import io
    import sys

    if hasattr(sys.stdout, "buffer"):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

    ap = argparse.ArgumentParser(description="解析候補シーンの一覧を作る")
    ap.add_argument("--game", type=int, help="game_id。省略で日本戦4試合")
    ap.add_argument("--min-priority", type=int, default=0)
    ap.add_argument("--out", help="CSV に書き出す")
    args = ap.parse_args()

    df = (build_catalog(args.game, args.min_priority) if args.game
          else build_all(min_priority=args.min_priority))
    if df.empty:
        print("候補が見つかりませんでした。")
        return

    print(f"=== シーン候補 {len(df)} 件 ===")
    print(df["kind"].value_counts().to_string())
    print()
    cols = ["game_id", "kind", "detail", "event_time", "clock", "team", "player"]
    top = df[df["priority"] >= 60]
    print(f"--- ゴール・決定機・シュート（{len(top)} 件）---")
    print(top[cols].to_string(index=False))

    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(args.out, index=False, encoding="utf-8-sig")
        print(f"\n書き出し: {args.out}")


if __name__ == "__main__":
    main()

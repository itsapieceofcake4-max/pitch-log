"""
rugby/export.py
===============
追跡結果（長形式）を CSV へ書き出す。

主たる納品形式は **縦軸=時間・横軸=選手** のワイド形式。列名は PitchLog 既存の
Export_GSA と同じ規約（`Home_P1_X` / `Away_P3_Y` / `Ball_X` …）に揃えてあるので、
そのまま既存の可視化・特徴量付与パイプラインへ流し込める。
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


TEAM_LABEL = {0: "Home", 1: "Away"}


# ── トラック → 選手スロットの割当 ────────────────────────────────────────────

def assign_slots(df: pd.DataFrame, n_players: int = 15) -> dict[int, str]:
    """track_id → 列プレフィックス（例 "Home_P3"）の対応を決める。

    背番号が手動割当されていればそれを優先し、無ければ「長く映っている順」に
    P1, P2, … を振る。チーム未確定のトラックは `Unknown_Pn` に送る。
    """
    p = df[df["kind"] == "player"]
    if p.empty:
        return {}

    stats = (
        p.groupby("track_id")
        .agg(n=("frame", "count"),
             team=("team", lambda s: s.dropna().mode().iloc[0] if s.notna().any() else None),
             jersey=("jersey", lambda s: s.dropna().iloc[0] if s.notna().any() else None))
        .reset_index()
        .sort_values("n", ascending=False)
    )

    mapping: dict[int, str] = {}
    used: dict[str, set[str]] = {"Home": set(), "Away": set(), "Unknown": set()}

    # 背番号が割り当てられているものを先に確定させる
    for _, r in stats[stats["jersey"].notna()].iterrows():
        side = TEAM_LABEL.get(r["team"], "Unknown")
        slot = f"P{str(r['jersey']).strip()}"
        if slot in used[side]:
            continue
        used[side].add(slot)
        mapping[int(r["track_id"])] = f"{side}_{slot}"

    for _, r in stats.iterrows():
        tid = int(r["track_id"])
        if tid in mapping:
            continue
        side = TEAM_LABEL.get(r["team"], "Unknown")
        limit = n_players if side != "Unknown" else 99
        for i in range(1, limit + 1):
            slot = f"P{i}"
            if slot not in used[side]:
                used[side].add(slot)
                mapping[tid] = f"{side}_{slot}"
                break

    return mapping


# ── ワイド形式 ────────────────────────────────────────────────────────────────

def to_wide(
    df: pd.DataFrame,
    n_players: int = 15,
    coords: str = "meters",
    slots: dict[int, str] | None = None,
) -> pd.DataFrame:
    """長形式 → ワイド形式（行=フレーム / 列=選手ごとの X, Y）。

    coords : "meters"（x_m, y_m）または "normalized"（x_norm, y_norm 0–1）
    """
    if df.empty:
        return pd.DataFrame()

    xcol, ycol = ("x_m", "y_m") if coords == "meters" else ("x_norm", "y_norm")
    slots = slots if slots is not None else assign_slots(df, n_players)

    frames = df[["frame", "video_frame", "time_sec"]].drop_duplicates("frame")
    out = frames.sort_values("frame").reset_index(drop=True)
    out = out.rename(columns={"frame": "Frame", "video_frame": "Video_Frame",
                              "time_sec": "Time"})

    ball = df[df["kind"] == "ball"].set_index("frame")
    out["Ball_X"] = out["Frame"].map(ball[xcol]).astype(float).round(3)
    out["Ball_Y"] = out["Frame"].map(ball[ycol]).astype(float).round(3)
    out["Ball_Status"] = out["Frame"].map(ball["status"])

    players = df[df["kind"] == "player"]
    # 列順は Home_P1..Pn → Away_P1..Pn → Unknown の順に整える
    ordered = sorted(
        set(slots.values()),
        key=lambda s: (
            {"Home": 0, "Away": 1}.get(s.split("_")[0], 2),
            int(s.split("_P")[1]) if s.split("_P")[1].isdigit() else 999,
        ),
    )

    cols: dict[str, pd.Series] = {}
    for tid, prefix in slots.items():
        sub = players[players["track_id"] == tid].set_index("frame")
        cols[f"{prefix}_X"] = out["Frame"].map(sub[xcol])
        cols[f"{prefix}_Y"] = out["Frame"].map(sub[ycol])
        cols[f"{prefix}_Speed"] = out["Frame"].map(sub["speed_mps"])

    for prefix in ordered:
        for suffix in ("_X", "_Y", "_Speed"):
            key = prefix + suffix
            if key in cols:
                out[key] = cols[key].astype(float).round(3)

    return out


# ── 書き出し ──────────────────────────────────────────────────────────────────

def to_spec_schema(df: pd.DataFrame) -> pd.DataFrame:
    """統合仕様書（Allclip_Tracking_Specs）のモジュール1 出力スキーマへ変換する。

    columns = [frame_idx, timestamp, track_id, x_pitch, y_pitch, team_id]
    """
    d = df[df["kind"] == "player"] if "kind" in df.columns else df
    out = pd.DataFrame({
        "frame_idx": d["frame"].astype(int),
        "timestamp": d["time_sec"].astype(float).round(3),
        "track_id": d["track_id"].astype(int),
        "x_pitch": d["x_m"].astype(float).round(3),
        "y_pitch": d["y_m"].astype(float).round(3),
        "team_id": d["team"],
    })
    return out.sort_values(["frame_idx", "track_id"]).reset_index(drop=True)


def write_csvs(
    df: pd.DataFrame,
    out_dir: str | Path,
    stem: str,
    n_players: int = 15,
) -> dict[str, Path]:
    """ワイド(m) / ワイド(正規化) / 長形式 の 3 種を書き出す。

    正規化版は列名・値域が Export_GSA と揃うため、既存 PitchLog にそのまま載る。
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slots = assign_slots(df, n_players)

    paths: dict[str, Path] = {}

    p = out_dir / f"{stem}_wide_meters.csv"
    to_wide(df, n_players, "meters", slots).to_csv(p, index=False, encoding="utf-8-sig")
    paths["wide_meters"] = p

    p = out_dir / f"{stem}_wide_normalized.csv"
    to_wide(df, n_players, "normalized", slots).to_csv(p, index=False, encoding="utf-8-sig")
    paths["wide_normalized"] = p

    p = out_dir / f"{stem}_tracks_long.csv"
    df.to_csv(p, index=False, encoding="utf-8-sig")
    paths["long"] = p

    p = out_dir / f"{stem}_spec_schema.csv"
    to_spec_schema(df).to_csv(p, index=False, encoding="utf-8-sig")
    paths["spec_schema"] = p

    return paths

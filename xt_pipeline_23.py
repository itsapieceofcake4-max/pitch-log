"""
xt_pipeline_23.py
==================
Pitch Log v23 - Player Contribution Pipeline

Processes SkillCorner dynamic_events.csv to compute per-player metrics:
  - VAEP    : (Δ P(score)) − (Δ P(concede)) from on_ball_engagement events
  - Off-ball: xthreat from off_ball_run events (positional runs / space creation)
  - Defense : stop_possession_danger, reduce_possession_danger, force_backward,
              beaten_by_possession, beaten_by_movement (from on_ball_engagement)

VAEP Attribution
----------------
  on_ball_engagement events are indexed by the DEFENDING player.
  The ATTACKING player is recorded as player_in_possession.

  vaep_raw = (xshot_end − xshot_start) − (xloss_end − xloss_start)
    — positive vaep_raw means the attacking player maintained/created value
    — negative vaep_raw means the defending player disrupted the attack

  vaep_attack  [player_in_possession] += vaep_raw     (attack credit)
  vaep_defend  [player / defender]    += −vaep_raw    (defense credit)

Frame Window
------------
  Filtered by raw SkillCorner frame_start in [raw_frame_start, raw_frame_end].
  Inferred from match_info.json (goal_frame_raw − window_frames + 1 … goal_frame_raw).

Output
------
  player_contributions_23.csv
  match_info.json  (updated with raw_frame_start / raw_frame_end)

Usage
-----
  python xt_pipeline_23.py \\
      --events 1925299_dynamic_events.csv \\
      --match_info match_info.json \\
      [--home_team_id 1802] [--away_team_id 871] \\
      [--output player_contributions_23.csv]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


# ── Constants ──────────────────────────────────────────────────────────────────
HOME_TEAM_ID   = 1802   # Brisbane Roar (SkillCorner ID)
AWAY_TEAM_ID   = 871    # Perth Glory   (SkillCorner ID)

DEFAULT_EVENTS_CSV = "1925299_dynamic_events.csv"
DEFAULT_OUTPUT_CSV = "player_contributions_23.csv"
DEFAULT_MATCH_JSON = "match_info.json"


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_bool_int(series: pd.Series) -> pd.Series:
    """Convert True/False or 'True'/'False' strings to 0/1 integer."""
    return pd.to_numeric(
        series.map({True: 1, False: 0, "True": 1, "False": 0, 1: 1, 0: 0}),
        errors="coerce",
    ).fillna(0).astype(int)


def _build_player_team_map(events_df: pd.DataFrame) -> dict:
    """
    Build a dict mapping player_id → {player_name, team_id, team_shortname}
    from ALL events (any row where player_id is non-null).
    """
    sub = (
        events_df[["player_id", "player_name", "team_id", "team_shortname"]]
        .dropna(subset=["player_id"])
        .drop_duplicates(subset=["player_id"])
    )
    result = {}
    for _, row in sub.iterrows():
        pid = int(row["player_id"])
        result[pid] = {
            "player_name":   str(row["player_name"])    if pd.notna(row["player_name"])    else "",
            "team_id":       int(row["team_id"])        if pd.notna(row["team_id"])        else 0,
            "team_shortname": str(row["team_shortname"]) if pd.notna(row["team_shortname"]) else "",
        }
    return result


# ── Frame window helpers ───────────────────────────────────────────────────────

def frame_window_from_match_info(match_info: dict) -> tuple[int | None, int | None]:
    """
    Derive raw SkillCorner frame window [start, end] from match_info.json.

    Uses  goal_frame_raw  and  window_frames  keys.
    Returns (raw_frame_start, raw_frame_end), or (None, None) if unavailable.
    """
    # Prefer explicit keys set by this module
    if "raw_frame_start" in match_info and "raw_frame_end" in match_info:
        return int(match_info["raw_frame_start"]), int(match_info["raw_frame_end"])

    goal_frame    = match_info.get("goal_frame_raw")
    window_frames = match_info.get("window_frames")
    if goal_frame is None or window_frames is None:
        return None, None

    raw_end   = int(goal_frame)
    raw_start = raw_end - int(window_frames) + 1
    return raw_start, raw_end


def load_match_info(path: str) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"  WARNING: Could not load match_info.json: {e}")
        return {}


def save_match_info(path: str, info: dict,
                    raw_frame_start: int | None, raw_frame_end: int | None) -> None:
    """Persist match_info.json with raw frame IDs added."""
    info_out = dict(info)
    if raw_frame_start is not None:
        info_out["raw_frame_start"] = raw_frame_start
    if raw_frame_end is not None:
        info_out["raw_frame_end"] = raw_frame_end
    with open(path, "w", encoding="utf-8") as f:
        json.dump(info_out, f, indent=2, ensure_ascii=False)


# ── Core computation ───────────────────────────────────────────────────────────

def compute_player_contributions(
    events_df: pd.DataFrame,
    raw_frame_start: int | None = None,
    raw_frame_end: int | None = None,
    home_team_id: int = HOME_TEAM_ID,
    away_team_id: int = AWAY_TEAM_ID,
) -> pd.DataFrame:
    """
    Aggregate per-player contribution metrics for the given frame window.

    Parameters
    ----------
    events_df      : Full dynamic_events DataFrame.
    raw_frame_start: First raw SkillCorner frame (inclusive). None = use all events.
    raw_frame_end  : Last  raw SkillCorner frame (inclusive). None = use all events.
    home_team_id   : SkillCorner team ID for Home team.
    away_team_id   : SkillCorner team ID for Away team.

    Returns
    -------
    DataFrame with one row per player, columns:
        player_id, player_name, team_id, team_name, team_label,
        vaep_attack, xshot_gain, xloss_gain, n_engagements_atk,
        vaep_defend, n_engagements_def,
        stop_danger, reduce_danger, force_backward,
        beaten_possession, beaten_movement,
        off_ball_xthreat, n_runs, n_runs_line_break, n_runs_behind,
        vaep_total
    Sorted by vaep_total descending.
    """
    # ── Filter to scene frame window ───────────────────────────────────────────
    df = events_df.copy()
    if raw_frame_start is not None and raw_frame_end is not None:
        if "frame_start" in df.columns:
            df["frame_start"] = pd.to_numeric(df["frame_start"], errors="coerce")
            mask = (df["frame_start"] >= raw_frame_start) & (df["frame_start"] <= raw_frame_end)
            df = df[mask].reset_index(drop=True)
        else:
            print("  WARNING: 'frame_start' column not found; using all events.")

    if df.empty:
        print("  WARNING: No events found in the specified frame window.")
        return pd.DataFrame()

    ev_counts = df["event_type"].value_counts().to_dict()
    print(f"  Events in window: {len(df)} rows | {ev_counts}")

    # ── Build player → team lookup from ALL events ─────────────────────────────
    # (before window filtering) to resolve player_in_possession team IDs too
    player_map = _build_player_team_map(events_df)

    # Also build from player_in_possession columns in on_ball_engagement events
    # (these players may not appear as primary player_id in the window)
    obe_all = events_df[events_df["event_type"] == "on_ball_engagement"].copy()
    if not obe_all.empty and "player_in_possession_id" in obe_all.columns:
        for _, row in obe_all[["player_in_possession_id", "player_in_possession_name"]].dropna().drop_duplicates().iterrows():
            pip_id   = int(row["player_in_possession_id"])
            pip_name = str(row["player_in_possession_name"]) if pd.notna(row["player_in_possession_name"]) else ""
            if pip_id not in player_map:
                # Infer team from corresponding player_possession events or player_id lookup
                pip_team_rows = events_df[events_df["player_id"] == pip_id]
                if not pip_team_rows.empty:
                    player_map[pip_id] = {
                        "player_name":    pip_name or str(pip_team_rows.iloc[0].get("player_name", "")),
                        "team_id":        int(pip_team_rows.iloc[0]["team_id"]) if pd.notna(pip_team_rows.iloc[0]["team_id"]) else 0,
                        "team_shortname": str(pip_team_rows.iloc[0]["team_shortname"]) if pd.notna(pip_team_rows.iloc[0]["team_shortname"]) else "",
                    }
                else:
                    # Cannot determine team — skip this player
                    pass

    # ── on_ball_engagement events in window ────────────────────────────────────
    obe = df[df["event_type"] == "on_ball_engagement"].copy()
    if not obe.empty:
        for col in ["xshot_player_possession_start", "xshot_player_possession_end",
                    "xloss_player_possession_start", "xloss_player_possession_end"]:
            obe[col] = pd.to_numeric(obe[col], errors="coerce")

        obe["_delta_xshot"] = obe["xshot_player_possession_end"] - obe["xshot_player_possession_start"]
        obe["_delta_xloss"] = obe["xloss_player_possession_end"] - obe["xloss_player_possession_start"]
        obe["_vaep_raw"]    = obe["_delta_xshot"] - obe["_delta_xloss"]

        for col in ["stop_possession_danger", "reduce_possession_danger", "force_backward",
                    "beaten_by_possession", "beaten_by_movement"]:
            if col in obe.columns:
                obe[col] = _to_bool_int(obe[col])

    # ── off_ball_run events in window ─────────────────────────────────────────
    obr = df[df["event_type"] == "off_ball_run"].copy()
    if not obr.empty:
        if "xthreat" in obr.columns:
            obr["xthreat"] = pd.to_numeric(obr["xthreat"], errors="coerce").fillna(0.0)
        for col in ["break_defensive_line", "intended_run_behind", "push_defensive_line"]:
            if col in obr.columns:
                obr[col] = _to_bool_int(obr[col])

    # ── Collect unique player IDs to aggregate ─────────────────────────────────
    all_pids: set[int] = set()

    if not obe.empty:
        all_pids |= set(
            int(x) for x in obe["player_id"].dropna().unique()
        )
        if "player_in_possession_id" in obe.columns:
            all_pids |= set(
                int(x) for x in obe["player_in_possession_id"].dropna().unique()
            )

    if not obr.empty:
        all_pids |= set(int(x) for x in obr["player_id"].dropna().unique())

    if not all_pids:
        print("  WARNING: No players found in the event window.")
        return pd.DataFrame()

    # ── Per-player aggregation ─────────────────────────────────────────────────
    rows = []

    for pid in all_pids:
        info = player_map.get(pid, {})
        tid  = info.get("team_id", 0)

        row: dict = {
            "player_id":   pid,
            "player_name": info.get("player_name", str(pid)),
            "team_id":     tid,
            "team_name":   info.get("team_shortname", ""),
            "team_label":  "Home" if tid == home_team_id else ("Away" if tid == away_team_id else "Other"),
        }

        # VAEP — attacking role (credited to the player in possession)
        if not obe.empty and "player_in_possession_id" in obe.columns:
            atk = obe[obe["player_in_possession_id"] == pid]
            row["vaep_attack"]       = float(atk["_vaep_raw"].sum()) if len(atk) else 0.0
            row["xshot_gain"]        = float(atk["_delta_xshot"].sum()) if len(atk) else 0.0
            row["xloss_gain"]        = float(atk["_delta_xloss"].sum()) if len(atk) else 0.0
            row["n_engagements_atk"] = int(len(atk))
        else:
            row.update({"vaep_attack": 0.0, "xshot_gain": 0.0,
                        "xloss_gain": 0.0, "n_engagements_atk": 0})

        # VAEP — defensive role (credited to the engaging / defending player)
        if not obe.empty:
            def_ = obe[obe["player_id"] == pid]
            # Defensive credit = negative of attacking VAEP:
            # if vaep_raw < 0 (attack failed), the defender gets positive credit
            row["vaep_defend"]       = float(-def_["_vaep_raw"].sum()) if len(def_) else 0.0
            row["n_engagements_def"] = int(len(def_))

            for src, dst in [
                ("stop_possession_danger",  "stop_danger"),
                ("reduce_possession_danger","reduce_danger"),
                ("force_backward",          "force_backward"),
                ("beaten_by_possession",    "beaten_possession"),
                ("beaten_by_movement",      "beaten_movement"),
            ]:
                row[dst] = int(def_[src].sum()) if (len(def_) and src in def_.columns) else 0
        else:
            row.update({
                "vaep_defend": 0.0, "n_engagements_def": 0,
                "stop_danger": 0, "reduce_danger": 0, "force_backward": 0,
                "beaten_possession": 0, "beaten_movement": 0,
            })

        # Off-ball run contribution
        if not obr.empty:
            runs = obr[obr["player_id"] == pid]
            row["off_ball_xthreat"]  = float(runs["xthreat"].sum()) if (len(runs) and "xthreat" in runs.columns) else 0.0
            row["n_runs"]            = int(len(runs))
            row["n_runs_line_break"] = int(runs["break_defensive_line"].sum()) if (len(runs) and "break_defensive_line" in runs.columns) else 0
            row["n_runs_behind"]     = int(runs["intended_run_behind"].sum()) if (len(runs) and "intended_run_behind" in runs.columns) else 0
        else:
            row.update({"off_ball_xthreat": 0.0, "n_runs": 0,
                        "n_runs_line_break": 0, "n_runs_behind": 0})

        # Composite total VAEP
        # off_ball_xthreat is a run quality score (different scale) → weighted at 0.1
        row["vaep_total"] = (
            row["vaep_attack"]
            + row["vaep_defend"]
            + row["off_ball_xthreat"] * 0.1
        )

        rows.append(row)

    result = pd.DataFrame(rows)

    # Round float columns
    for col in ["vaep_attack", "xshot_gain", "xloss_gain",
                "vaep_defend", "off_ball_xthreat", "vaep_total"]:
        if col in result.columns:
            result[col] = result[col].round(5)

    result = result.sort_values("vaep_total", ascending=False).reset_index(drop=True)
    return result


# ══════════════════════════════════════════════════════════════════════════════
# GSA feature extension
# ══════════════════════════════════════════════════════════════════════════════

PITCH_W_M = 105.0   # pitch width in meters
PITCH_H_M = 68.0    # pitch height in meters


def add_gsa_features(df: pd.DataFrame, fps: float = 10.0) -> pd.DataFrame:
    """
    Add GSA-recommended feature columns to a 22-player scene CSV.

    Added columns (per frame)
    -------------------------
    Delta_Ball_xT, Delta_Home_MAX_xT, Delta_Away_MAX_xT,
    Delta_Home_SUM_xT, Delta_Away_SUM_xT   (target variable candidates)

    {team}_P{n}_dist_ball   : distance from player to ball in METERS
    {team}_P{n}_speed       : player's instantaneous speed in m/s

    Properties
    ----------
    - Non-destructive: existing columns are never modified.
    - Idempotent     : if Delta_Ball_xT exists, returns df unchanged.
    - Backward-compat: v22 readers ignore extra columns.

    Recommended GSA usage
    ---------------------
    Target variable (Y) :
        Delta_Ball_xT       (most direct measure of "value-creating action")
      or Delta_Away_MAX_xT  (team-level threat surge)
      or Away_MAX_xT        (current target — positional level)

    Feature variables (X) :
        Each player's xT
        Each player's dist_ball
        Each player's speed
      (Do NOT include X, Y, GridID — they are redundant with xT)
    """
    if "Delta_Ball_xT" in df.columns:
        return df   # already extended

    out = df.copy()

    # ── Delta time-series (target variable candidates) ─────────────────────────
    for col in ["Ball_xT", "Home_MAX_xT", "Away_MAX_xT",
                "Home_SUM_xT", "Away_SUM_xT"]:
        if col in out.columns:
            out[f"Delta_{col}"] = pd.to_numeric(out[col], errors="coerce").diff().fillna(0).round(5)

    # ── Detect team player numbers ─────────────────────────────────────────────
    def _nums(team: str) -> list[int]:
        nums = []
        import re as _re
        for c in out.columns:
            m = _re.match(rf"^{team}_P(\d+)_X$", c)
            if m and f"{team}_P{m.group(1)}_Y" in out.columns:
                nums.append(int(m.group(1)))
        return sorted(nums)

    h_nums = _nums("Home")
    a_nums = _nums("Away")

    if "Ball_X" not in out.columns or "Ball_Y" not in out.columns:
        return out   # not a 22-player scene CSV

    bx = pd.to_numeric(out["Ball_X"], errors="coerce")
    by = pd.to_numeric(out["Ball_Y"], errors="coerce")

    # ── Per-player distance-to-ball (meters) & speed (m/s) ────────────────────
    for team, nums in [("Home", h_nums), ("Away", a_nums)]:
        for n in nums:
            px = pd.to_numeric(out[f"{team}_P{n}_X"], errors="coerce")
            py = pd.to_numeric(out[f"{team}_P{n}_Y"], errors="coerce")

            # distance to ball (m)
            dx_m = (px - bx) * PITCH_W_M
            dy_m = (py - by) * PITCH_H_M
            out[f"{team}_P{n}_dist_ball"] = np.sqrt(dx_m**2 + dy_m**2).round(3)

            # speed (m/s) — based on per-frame position delta × fps
            vx_m = px.diff() * PITCH_W_M
            vy_m = py.diff() * PITCH_H_M
            out[f"{team}_P{n}_speed"] = (
                np.sqrt(vx_m**2 + vy_m**2) * fps
            ).fillna(0.0).round(3)

    return out


def detect_fps_from_scene(df: pd.DataFrame) -> float:
    """Infer playback FPS from the Time column of a scene CSV. Defaults to 10.0."""
    if "Time" not in df.columns or len(df) < 2:
        return 10.0
    dt = pd.to_numeric(df["Time"], errors="coerce").diff().dropna().median()
    if dt and dt > 0:
        return float(round(1.0 / dt))
    return 10.0


# ── CLI entry point ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pitch Log v23 - Player Contribution Pipeline")
    parser.add_argument("--events",       default=DEFAULT_EVENTS_CSV)
    parser.add_argument("--match_info",   default=DEFAULT_MATCH_JSON)
    parser.add_argument("--output",       default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--home_team_id", type=int, default=HOME_TEAM_ID)
    parser.add_argument("--away_team_id", type=int, default=AWAY_TEAM_ID)
    parser.add_argument("--frame_start",  type=int, default=None,
                        help="Override raw frame start (default: derived from match_info)")
    parser.add_argument("--frame_end",    type=int, default=None,
                        help="Override raw frame end   (default: derived from match_info)")
    parser.add_argument("--gsa_extend",   type=str, default=None,
                        help="Path to a scene CSV. Adds GSA feature columns and writes "
                             "_gsa_extended.csv (skips VAEP computation).")
    parser.add_argument("--fps",          type=float, default=10.0,
                        help="FPS for GSA speed calculation (only used with --gsa_extend)")
    args = parser.parse_args()

    # ── GSA extension-only mode ────────────────────────────────────────────────
    if args.gsa_extend:
        src = Path(args.gsa_extend)
        if not src.exists():
            sys.exit(f"ERROR: {src} not found.")

        print("=" * 60)
        print("  Pitch Log v23 - GSA Feature Extension")
        print("=" * 60)
        print(f"\n[Load] {src}")
        scene_df = pd.read_csv(src)
        print(f"       {len(scene_df)} rows  |  {len(scene_df.columns)} columns (input)")

        fps_use = args.fps if args.fps else detect_fps_from_scene(scene_df)
        print(f"\n[FPS]  {fps_use}")

        print("\n[Compute] Delta time-series + dist_ball + speed ...")
        ext_df = add_gsa_features(scene_df, fps=fps_use)
        n_added = len(ext_df.columns) - len(scene_df.columns)
        print(f"          Added {n_added} columns "
              f"({len(scene_df.columns)} -> {len(ext_df.columns)})")

        out_path = src.with_name(src.stem + "_gsa_extended.csv")
        ext_df.to_csv(out_path, index=False, encoding="utf-8")
        print(f"\n[Save] -> {out_path}")
        print("\n  Done.")
        sys.exit(0)

    print("=" * 60)
    print("  Pitch Log v23 - Player Contribution Pipeline")
    print("=" * 60)

    # Load events
    if not Path(args.events).exists():
        sys.exit(f"ERROR: {args.events} not found.")
    print(f"\n[Load] {args.events}")
    events_df = pd.read_csv(args.events, low_memory=False)
    print(f"       {len(events_df)} rows  |  {len(events_df.columns)} columns")
    print(f"       Event types: {events_df['event_type'].value_counts().to_dict()}")

    # Load match_info
    match_info = load_match_info(args.match_info)
    if match_info:
        print(f"\n[Match] {match_info.get('match_name', '?')}  |  "
              f"goal_frame_raw={match_info.get('goal_frame_raw')}  "
              f"window_frames={match_info.get('window_frames')}")

    # Determine frame window
    if args.frame_start is not None and args.frame_end is not None:
        raw_start, raw_end = args.frame_start, args.frame_end
    else:
        raw_start, raw_end = frame_window_from_match_info(match_info)
    if raw_start is None:
        print("\n  No frame window found. Using ALL events.")
    else:
        print(f"\n[Frame] {raw_start} ~ {raw_end}  ({raw_end - raw_start + 1} frames)")

    # Compute
    print("\n[Compute] Aggregating per-player metrics …")
    contrib_df = compute_player_contributions(
        events_df,
        raw_frame_start=raw_start,
        raw_frame_end=raw_end,
        home_team_id=args.home_team_id,
        away_team_id=args.away_team_id,
    )

    if contrib_df.empty:
        print("\n  No contributions computed.")
        sys.exit(0)

    # Save
    contrib_df.to_csv(args.output, index=False, encoding="utf-8")
    print(f"\n[Save] → {args.output}  ({len(contrib_df)} players)")

    for label in ["Home", "Away"]:
        team_df = contrib_df[contrib_df["team_label"] == label]
        if not team_df.empty:
            top = team_df.iloc[0]
            print(f"  {label} top: {top['player_name']:30s}  "
                  f"vaep_total={top['vaep_total']:+.4f}  "
                  f"atk={top['vaep_attack']:+.4f}  "
                  f"def={top['vaep_defend']:+.4f}  "
                  f"run={top['off_ball_xthreat']:.4f}")

    # Update match_info
    if Path(args.match_info).exists() and raw_start is not None:
        save_match_info(args.match_info, match_info, raw_start, raw_end)
        print(f"\n[Update] {args.match_info}  →  raw_frame_start={raw_start}  raw_frame_end={raw_end}")

    print("\n  Done.")

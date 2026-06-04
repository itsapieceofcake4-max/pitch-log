"""
convert_skillcorner_to_pipeline.py
====================================
Match : Brisbane Roar FC 0-1 Perth Glory FC
Date  : 2024-12-21
Match : 1925299

Reads the downloaded SkillCorner files from  skillcorner_1925299/
and writes  Sample_TrackingData_22.csv  in the format expected by
xt_pipeline_22.py / app_22.py.

Steps
-----
1. Parse 1925299_match.json  → player_id → (team, jersey_number)
2. Parse 1925299_phases_of_play.csv → goal frame_id
3. Stream 1925299_tracking_extrapolated.jsonl → build DataFrame
4. Normalize coords, map players, write CSV (30-second window)

Output columns (49)
-------------------
frame, time_sec, ball_x, ball_y, is_goal_frame,
Home_1_x, Home_1_y, ..., Home_11_x, Home_11_y,
Away_1_x, Away_1_y, ..., Away_11_x, Away_11_y

Usage
-----
  python convert_skillcorner_to_pipeline.py
"""

import io
import json
import sys
from pathlib import Path

# Force UTF-8 output on Windows (avoids cp932 encode errors)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import numpy as np
import pandas as pd

# ── constants ──────────────────────────────────────────────────────────────
MATCH_ID   = "1925299"
DATA_DIR   = Path(f"skillcorner_{MATCH_ID}")
OUT_CSV    = Path("Sample_TrackingData_22.csv")

HOME_TEAM_ID = 1802   # Brisbane Roar FC
AWAY_TEAM_ID = 871    # Perth Glory FC

FPS          = 10     # SkillCorner broadcast tracking rate
WINDOW_SEC   = 30     # seconds before goal to extract
WINDOW_FRAMES = FPS * WINDOW_SEC   # 300 frames

PITCH_W = 105.0
PITCH_H = 68.0

# Coordinate origin: SkillCorner uses meters, centred at (0, 0)
# Normalize to [0, 1]:  norm_x = (x + 52.5) / 105
#                        norm_y = (y + 34.0) / 68
X_OFFSET = PITCH_W / 2   # 52.5
Y_OFFSET = PITCH_H / 2   # 34.0


# ── helpers ────────────────────────────────────────────────────────────────

def load_match_json() -> tuple[dict, dict]:
    """Return (home_map, away_map) where each map is {player_id: jersey_number}."""
    path = DATA_DIR / f"{MATCH_ID}_match.json"
    if not path.exists():
        sys.exit(f"[ERROR] {path} not found — run fetch_skillcorner_1925299.py first")

    with open(path, encoding="utf-8") as f:
        match = json.load(f)

    home_map: dict[int, int] = {}
    away_map: dict[int, int] = {}

    # Try standard SkillCorner open-data structure
    for team_key, pid_map, team_id_check in [
        ("home_team", home_map, HOME_TEAM_ID),
        ("away_team", away_map, AWAY_TEAM_ID),
    ]:
        team_obj = match.get(team_key, {})
        players  = team_obj.get("players", [])
        for p in players:
            pid = p.get("id") or p.get("player_id")
            num = p.get("number") or p.get("jersey_number") or p.get("shirt_number")
            if pid is not None and num is not None:
                pid_map[int(pid)] = int(num)

    # Fallback: flat player list with team_id field
    if not home_map and not away_map:
        for p in match.get("players", []):
            pid  = p.get("id") or p.get("player_id")
            num  = p.get("number") or p.get("jersey_number")
            tid  = p.get("team_id")
            if pid is None or num is None or tid is None:
                continue
            if int(tid) == HOME_TEAM_ID:
                home_map[int(pid)] = int(num)
            elif int(tid) == AWAY_TEAM_ID:
                away_map[int(pid)] = int(num)

    print(f"  Home players mapped: {len(home_map)}")
    print(f"  Away players mapped: {len(away_map)}")
    if not home_map or not away_map:
        print("  [WARN] Some team mapping is empty — printing raw match.json keys:")
        print("  ", list(match.keys()))

    return home_map, away_map


def find_goal_frame() -> int:
    """
    Return the frame_id of the goal using phases_of_play.csv.

    The goal is the frame_end of the phase where
    team_possession_lead_to_goal == True (or 1).
    """
    path = DATA_DIR / f"{MATCH_ID}_phases_of_play.csv"
    if not path.exists():
        sys.exit(f"[ERROR] {path} not found")

    df = pd.read_csv(path)
    print(f"  phases_of_play columns: {list(df.columns)}")

    # Normalise column name variants
    col_map = {c.lower().strip(): c for c in df.columns}

    # Look for boolean goal-lead column
    goal_col = None
    for candidate in ["team_possession_lead_to_goal", "leads_to_goal",
                       "possession_lead_to_goal"]:
        if candidate in col_map:
            goal_col = col_map[candidate]
            break

    if goal_col is None:
        # Print first few rows to help debug
        print("  [WARN] No goal-detection column found. Columns available:")
        print("  ", list(df.columns))
        print(df.head(3).to_string())
        sys.exit("[ERROR] Cannot detect goal frame automatically")

    goal_phases = df[df[goal_col].astype(str).str.lower().isin(["true", "1", "yes"])]
    if goal_phases.empty:
        sys.exit(f"[ERROR] No rows with {goal_col}==True found")

    # frame_end column variants
    end_col = None
    for candidate in ["frame_end", "end_frame", "frame_id_end", "frame_stop"]:
        if candidate in col_map:
            end_col = col_map[candidate]
            break

    if end_col is None:
        print("  [WARN] No frame_end column. Using last row's numeric column.")
        print("  ", list(df.columns))
        end_col = goal_phases.columns[-1]

    goal_frame = int(goal_phases.iloc[-1][end_col])
    print(f"  Goal frame detected: {goal_frame}")
    return goal_frame


def load_possession_map(start_frame: int, goal_frame: int) -> dict:
    """
    Return {original_frame_id: 'H'|'A'|''} for frames in [start_frame, goal_frame].

    Uses phases_of_play.csv: each row covers a range [frame_start, frame_end]
    with team_in_possession_id indicating which team held the ball.
    """
    path = DATA_DIR / f"{MATCH_ID}_phases_of_play.csv"
    if not path.exists():
        return {}

    df = pd.read_csv(path)
    col_map = {c.lower().strip(): c for c in df.columns}

    start_col = col_map.get("frame_start", col_map.get("start_frame"))
    end_col   = col_map.get("frame_end",   col_map.get("end_frame"))
    poss_col  = col_map.get("team_in_possession_id")

    if not all([start_col, end_col, poss_col]):
        print(f"  [WARN] possession columns not found: {list(df.columns)}")
        return {}

    # Filter to phases that overlap our window
    df = df[(df[end_col] >= start_frame) & (df[start_col] <= goal_frame)]

    poss_map: dict = {}
    for _, row in df.iterrows():
        fs = int(row[start_col])
        fe = int(row[end_col])
        tid = row[poss_col]
        label = ""
        try:
            t = int(tid)
            if t == HOME_TEAM_ID:
                label = "H"
            elif t == AWAY_TEAM_ID:
                label = "A"
        except (ValueError, TypeError):
            pass
        for fid in range(max(fs, start_frame), min(fe, goal_frame) + 1):
            poss_map[fid] = label

    print(f"  Possession map built: {len(poss_map)} frames covered")
    h = sum(1 for v in poss_map.values() if v == "H")
    a = sum(1 for v in poss_map.values() if v == "A")
    print(f"    Home possession: {h} frames, Away possession: {a} frames")
    return poss_map


def norm_x(x: float) -> float:
    return (x + X_OFFSET) / PITCH_W


def norm_y(y: float) -> float:
    return (y + Y_OFFSET) / PITCH_H


def parse_tracking(home_map: dict, away_map: dict,
                   goal_frame: int, poss_map: dict) -> pd.DataFrame:
    """
    Stream the JSONL file and build a DataFrame of the 300-frame window
    ending at goal_frame.
    """
    path = DATA_DIR / f"{MATCH_ID}_tracking_extrapolated.jsonl"
    if not path.exists():
        sys.exit(f"[ERROR] {path} not found")

    # Assign stable slot indices for jersey numbers (sorted ascending)
    # Home slots: jersey sorted → slot 1..11
    # Away slots: jersey sorted → slot 1..11
    # We build these lazily from the first populated frame.
    home_jerseys: list[int] = []
    away_jerseys: list[int] = []

    # Decide frame window: [start_frame, goal_frame]
    start_frame = goal_frame - WINDOW_FRAMES + 1

    print(f"  Reading window frames {start_frame} to {goal_frame}  "
          f"({WINDOW_FRAMES} frames @ {FPS}fps = {WINDOW_SEC}s)")
    print(f"  Streaming JSONL... (this may take a while for the full file)")

    rows: list[dict] = []
    lines_read = 0

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            lines_read += 1
            if lines_read % 5000 == 0:
                print(f"\r  Lines read: {lines_read:,}  rows captured: {len(rows)}", end="", flush=True)

            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            fid = rec.get("frame_id") or rec.get("frame") or rec.get("id")
            if fid is None:
                continue
            fid = int(fid)

            if fid < start_frame or fid > goal_frame:
                continue

            # ── ball ──────────────────────────────────────────────
            ball_obj = rec.get("ball_data") or rec.get("ball") or rec.get("ball_coordinates") or {}
            if isinstance(ball_obj, dict):
                bx_raw = ball_obj.get("x", np.nan)
                by_raw = ball_obj.get("y", np.nan)
            else:
                bx_raw, by_raw = np.nan, np.nan

            # Detect if coords already normalised (0–1) vs. meters
            if abs(bx_raw) <= 1.5 and abs(by_raw) <= 1.5:
                # Already normalised (unusual for SkillCorner but handle it)
                bx_norm, by_norm = float(bx_raw), float(by_raw)
            else:
                bx_norm = norm_x(float(bx_raw)) if not np.isnan(bx_raw) else np.nan
                by_norm = norm_y(float(by_raw)) if not np.isnan(by_raw) else np.nan

            row: dict = {
                "frame_id":       fid,
                "ball_x":         bx_norm,
                "ball_y":         by_norm,
                "is_goal_frame":  1 if fid == goal_frame else 0,
                "ball_possession": poss_map.get(fid, ""),
            }

            # ── players ───────────────────────────────────────────
            players = rec.get("player_data") or rec.get("players") or rec.get("player_positions") or []
            for p in players:
                pid  = p.get("player_id") or p.get("id")
                tid  = p.get("team_id")
                px   = p.get("x", np.nan)
                py   = p.get("y", np.nan)
                if pid is None:
                    continue

                pid = int(pid)
                if px is None or py is None:
                    continue
                px, py = float(px), float(py)

                # Normalise
                if abs(px) <= 1.5 and abs(py) <= 1.5:
                    pxn, pyn = px, py
                else:
                    pxn = norm_x(px)
                    pyn = norm_y(py)

                # Determine team & jersey
                if pid in home_map:
                    jersey = home_map[pid]
                    row[f"home_{jersey}_x"] = pxn
                    row[f"home_{jersey}_y"] = pyn
                    if jersey not in home_jerseys:
                        home_jerseys.append(jersey)
                elif pid in away_map:
                    jersey = away_map[pid]
                    row[f"away_{jersey}_x"] = pxn
                    row[f"away_{jersey}_y"] = pyn
                    if jersey not in away_jerseys:
                        away_jerseys.append(jersey)
                else:
                    # Unknown player: try team_id field
                    if tid is not None:
                        if int(tid) == HOME_TEAM_ID:
                            row[f"home_unk_{pid}_x"] = pxn
                        elif int(tid) == AWAY_TEAM_ID:
                            row[f"away_unk_{pid}_x"] = pxn

            rows.append(row)

            # Early exit once we have all window frames
            if len(rows) >= WINDOW_FRAMES and fid >= goal_frame:
                break

    print(f"\n  Total lines read: {lines_read:,}  Rows captured: {len(rows)}")
    return pd.DataFrame(rows), sorted(home_jerseys), sorted(away_jerseys)


def build_output(raw_df: pd.DataFrame,
                 home_jerseys: list[int],
                 away_jerseys: list[int]) -> pd.DataFrame:
    """
    Convert raw parsed DataFrame → canonical 49-column format.

    Players are ranked by jersey number and assigned slots 1..11.
    Missing players in a frame get NaN (pipeline tolerates it).
    """
    raw_df = raw_df.sort_values("frame_id").reset_index(drop=True)

    # Clamp to exactly WINDOW_FRAMES rows (take last WINDOW_FRAMES)
    if len(raw_df) > WINDOW_FRAMES:
        raw_df = raw_df.iloc[-WINDOW_FRAMES:].reset_index(drop=True)

    out = pd.DataFrame()
    out["frame"]           = range(1, len(raw_df) + 1)
    out["time_sec"]        = (raw_df["frame_id"].values - raw_df["frame_id"].values[0]) / FPS
    out["ball_x"]          = raw_df["ball_x"].values
    out["ball_y"]          = raw_df["ball_y"].values
    out["is_goal_frame"]   = raw_df["is_goal_frame"].values
    out["ball_possession"] = raw_df["ball_possession"].values if "ball_possession" in raw_df.columns else ""

    # Home: up to 11 players
    h_slots = home_jerseys[:11] if len(home_jerseys) >= 11 else home_jerseys
    for slot_idx, jersey in enumerate(h_slots, start=1):
        cx = f"home_{jersey}_x"
        cy = f"home_{jersey}_y"
        out[f"Home_{slot_idx}_x"] = raw_df[cx].values if cx in raw_df.columns else np.nan
        out[f"Home_{slot_idx}_y"] = raw_df[cy].values if cy in raw_df.columns else np.nan
    # Pad with NaN if fewer than 11 tracked
    for slot_idx in range(len(h_slots) + 1, 12):
        out[f"Home_{slot_idx}_x"] = np.nan
        out[f"Home_{slot_idx}_y"] = np.nan

    # Away: up to 11 players
    a_slots = away_jerseys[:11] if len(away_jerseys) >= 11 else away_jerseys
    for slot_idx, jersey in enumerate(a_slots, start=1):
        cx = f"away_{jersey}_x"
        cy = f"away_{jersey}_y"
        out[f"Away_{slot_idx}_x"] = raw_df[cx].values if cx in raw_df.columns else np.nan
        out[f"Away_{slot_idx}_y"] = raw_df[cy].values if cy in raw_df.columns else np.nan
    for slot_idx in range(len(a_slots) + 1, 12):
        out[f"Away_{slot_idx}_x"] = np.nan
        out[f"Away_{slot_idx}_y"] = np.nan

    return out


def print_player_legend(home_jerseys: list[int],
                        away_jerseys: list[int]) -> None:
    print("\n  Player slot mapping written to output:")
    print("  Home (Brisbane Roar):")
    for i, j in enumerate(home_jerseys[:11], 1):
        print(f"    Home_{i}_x/y  ← jersey #{j}")
    print("  Away (Perth Glory):")
    for i, j in enumerate(away_jerseys[:11], 1):
        print(f"    Away_{i}_x/y  ← jersey #{j}")


# ── main ───────────────────────────────────────────────────────────────────

def main() -> None:
    print("=" * 60)
    print("  SkillCorner to Pipeline Converter")
    print(f"  Match {MATCH_ID}: Brisbane Roar 0-1 Perth Glory")
    print("=" * 60)

    # 1. Player mapping
    print("\n[1] Loading match.json ...")
    home_map, away_map = load_match_json()

    # 2. Goal frame
    print("\n[2] Detecting goal frame ...")
    goal_frame = find_goal_frame()

    # 3. Parse tracking JSONL
    print("\n[3] Building possession map ...")
    start_frame = goal_frame - WINDOW_FRAMES + 1
    poss_map = load_possession_map(start_frame, goal_frame)

    print("\n[4] Parsing tracking data ...")
    raw_df, home_jerseys, away_jerseys = parse_tracking(home_map, away_map, goal_frame, poss_map)

    if raw_df.empty:
        sys.exit("[ERROR] No rows captured — check frame window vs JSONL content")

    print(f"  Home jerseys seen: {sorted(home_jerseys)}")
    print(f"  Away jerseys seen: {sorted(away_jerseys)}")

    # 5. Build output
    print("\n[5] Formatting output CSV ...")
    out_df = build_output(raw_df, home_jerseys, away_jerseys)

    out_df.to_csv(OUT_CSV, index=False, float_format="%.6f")
    print(f"  Written: {OUT_CSV}  ({len(out_df)} rows × {len(out_df.columns)} cols)")
    print_player_legend(home_jerseys, away_jerseys)

    print("\n" + "=" * 60)
    print("  Done.  Next steps:")
    print("    python xt_pipeline_22.py    (FPS=10, WINDOW=300 already auto-detected)")
    print("    streamlit run app_22.py")
    print("=" * 60)


if __name__ == "__main__":
    main()

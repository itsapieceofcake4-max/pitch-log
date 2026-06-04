"""
xt_pipeline_22.py
==================
22-player xT pipeline for Pitch Log.

Steps
-----
  1. Load xT base map (105×68 grid)
  2. Load tracking CSV (22 players + ball)
  3. Assign GridID & xT to every subject every frame
  4. Extract 30-second goal window (750 frames)
  5. Reformat to 94-column export schema
  6. Save → Export_GSA_22players_30s.csv

Output schema (94 cols)
-----------------------
  Frame, Time,
  Ball_X, Ball_Y, Ball_GridID, Ball_xT,
  Home_P1_X, Home_P1_Y, Home_P1_GridID, Home_P1_xT,
  ...
  Home_P11_X, Home_P11_Y, Home_P11_GridID, Home_P11_xT,
  Away_P1_X, Away_P1_Y, Away_P1_GridID, Away_P1_xT,
  ...
  Away_P11_X, Away_P11_Y, Away_P11_GridID, Away_P11_xT

GridID = X_idx + Y_idx * 105 + 1   (1-based, 1..7140)
xT     = value from 105×68 base map at the player's grid cell.
         Applied identically to both teams; high xT for an Away player
         indicates a dangerous defensive zone for the Home team.

Usage
-----
  python xt_pipeline_22.py
"""

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

# ── constants ──────────────────────────────────────────────────────────────────
X_BINS        = 105
Y_BINS        = 68
WINDOW_SEC    = 30
# FPS and WINDOW_FRAMES are inferred from the data at runtime (see auto_detect_fps)

XT_MAP_CSV    = "xT_BaseMap_105x68.csv"
TRACKING_CSV  = "Sample_TrackingData_22.csv"
OUTPUT_CSV    = "Export_GSA_22players_30s.csv"
MATCH_INFO_JSON = "match_info.json"

MATCH_NAME    = "Brisbane Roar 0-1 Perth Glory"
MATCH_ROUND   = "Round 09 | Isuzu UTE A-League 2024-25"


# ── helpers ────────────────────────────────────────────────────────────────────

def load_xt_map(path: str) -> np.ndarray:
    df  = pd.read_csv(path, index_col=0)
    arr = df.values.astype(np.float32)
    assert arr.shape == (Y_BINS, X_BINS), f"Unexpected xT map shape: {arr.shape}"
    return arr


def coord_to_bin(x_norm: np.ndarray, y_norm: np.ndarray):
    xi = np.clip(np.floor(x_norm * X_BINS).astype(int), 0, X_BINS - 1)
    yi = np.clip(np.floor(y_norm * Y_BINS).astype(int), 0, Y_BINS - 1)
    return xi, yi


def compute_grid_id(xi: np.ndarray, yi: np.ndarray) -> np.ndarray:
    return xi + yi * X_BINS + 1   # 1-based, 1..7140


def lookup_xt(xt_map: np.ndarray, xi: np.ndarray, yi: np.ndarray) -> np.ndarray:
    return xt_map[yi, xi].astype(np.float64)


def detect_team_nums(df: pd.DataFrame, team: str) -> list[int]:
    """Return sorted list of player numbers for a team prefix ('Home' or 'Away')."""
    pat  = re.compile(rf"^{team}_(\d+)_x$", re.IGNORECASE)
    nums = []
    for col in df.columns:
        m = pat.match(col)
        if m and f"{team}_{m.group(1)}_y" in df.columns:
            nums.append(int(m.group(1)))
    return sorted(nums)


def auto_detect_fps(df: pd.DataFrame) -> int:
    """Infer FPS from time_sec column. Falls back to 25 if unavailable."""
    if "time_sec" not in df.columns or len(df) < 2:
        return 25
    dt = pd.to_numeric(df["time_sec"], errors="coerce").dropna().diff().dropna()
    median_dt = float(dt.median())
    if median_dt <= 0:
        return 25
    fps = round(1.0 / median_dt)
    return int(fps) if fps > 0 else 25


def detect_goal_frame(df: pd.DataFrame) -> int:
    frame_col = "frame" if "frame" in df.columns else df.columns[0]
    if "is_goal_frame" in df.columns:
        rows = df.index[df["is_goal_frame"] == 1].tolist()
        if rows:
            return int(df.loc[rows[-1], frame_col])
    return int(df[frame_col].iloc[-1])


# ── Step 1: assign GridID + xT ────────────────────────────────────────────────

def assign_grid_and_xt_22(df: pd.DataFrame, xt_map: np.ndarray) -> pd.DataFrame:
    """
    Add {prefix}_GridID (Int64) and {prefix}_xT (float64) columns.

    - Home team  : standard xT map (attacks toward x=1)
    - Away team  : x-mirrored xT map (attacks toward x=0)
    - Ball_xT    : possession-aware if 'ball_possession' column present;
                   otherwise uses the Home-perspective map.
    """
    out = df.copy()
    # Away team uses a mirrored map so high xT = danger toward x=0 (Away's goal)
    xt_map_away = xt_map[:, ::-1]

    def _process(raw_x_col: str, raw_y_col: str, out_prefix: str,
                 map_to_use: np.ndarray) -> None:
        if raw_x_col not in out.columns or raw_y_col not in out.columns:
            return
        x = pd.to_numeric(out[raw_x_col], errors="coerce").values
        y = pd.to_numeric(out[raw_y_col], errors="coerce").values
        valid = ~(np.isnan(x) | np.isnan(y))

        gid  = np.full(len(out), np.nan, dtype=np.float64)
        xt_v = np.full(len(out), np.nan, dtype=np.float64)

        if valid.any():
            xi, yi     = coord_to_bin(x[valid], y[valid])
            gid[valid] = compute_grid_id(xi, yi).astype(np.float64)
            xt_v[valid] = lookup_xt(map_to_use, xi, yi)

        out[f"{out_prefix}_GridID"] = pd.array(
            np.where(valid, gid, pd.NA), dtype=pd.Int64Dtype()
        )
        out[f"{out_prefix}_xT"] = xt_v

    # Ball — possession-aware xT
    bx = pd.to_numeric(out["ball_x"], errors="coerce").values
    by = pd.to_numeric(out["ball_y"], errors="coerce").values
    valid_b = ~(np.isnan(bx) | np.isnan(by))

    gid_b  = np.full(len(out), np.nan, dtype=np.float64)
    xt_b   = np.full(len(out), np.nan, dtype=np.float64)

    if valid_b.any():
        xi_b, yi_b = coord_to_bin(bx[valid_b], by[valid_b])
        gid_b[valid_b] = compute_grid_id(xi_b, yi_b).astype(np.float64)

        if "ball_possession" in out.columns:
            # Per-frame possession-aware lookup
            poss = out["ball_possession"].fillna("").values
            xi_all, yi_all = coord_to_bin(
                np.where(valid_b, bx, 0), np.where(valid_b, by, 0)
            )
            for i in range(len(out)):
                if not valid_b[i]:
                    continue
                xi_i, yi_i = int(xi_all[i]), int(yi_all[i])
                use_map = xt_map_away if poss[i] == "A" else xt_map
                xt_b[i] = float(use_map[yi_i, xi_i])
        else:
            xt_b[valid_b] = lookup_xt(xt_map, xi_b, yi_b)

    out["ball_GridID"] = pd.array(
        np.where(valid_b, gid_b, pd.NA), dtype=pd.Int64Dtype()
    )
    out["ball_xT"] = xt_b

    # Home players — standard map
    for n in detect_team_nums(df, "Home"):
        _process(f"Home_{n}_x", f"Home_{n}_y", f"Home_{n}", xt_map)
        print(f"    Home_{n} done")

    # Away players — mirrored map
    for n in detect_team_nums(df, "Away"):
        _process(f"Away_{n}_x", f"Away_{n}_y", f"Away_{n}", xt_map_away)
        print(f"    Away_{n} done (mirrored xT)")

    return out


# ── Step 2: extract goal window ───────────────────────────────────────────────

def extract_goal_window(
    df: pd.DataFrame, fps: int, goal_frame_override: int | None = None,
    window_sec: int = WINDOW_SEC,
) -> tuple[pd.DataFrame, dict]:
    """
    Extract a time window ending at the goal frame.
    Returns (window_df, metadata_dict).
    metadata_dict contains actual match times (in seconds) for display.
    """
    window_frames = window_sec * fps
    frame_col = "frame" if "frame" in df.columns else df.columns[0]
    df_s      = df.sort_values(frame_col).reset_index(drop=True)

    if goal_frame_override is not None:
        gf = goal_frame_override
    else:
        gf = detect_goal_frame(df_s)

    idx   = df_s.index[df_s[frame_col] == gf]
    pos   = int(idx[-1]) if len(idx) else len(df_s) - 1
    start = max(0, pos - window_frames + 1)
    window = df_s.iloc[start : pos + 1].reset_index(drop=True)

    # Capture actual match times from time_sec column
    time_col = "time_sec" if "time_sec" in df_s.columns else None
    if time_col:
        window_start_sec = float(df_s.iloc[start][time_col])
        goal_time_sec    = float(df_s.iloc[pos][time_col])
    else:
        window_start_sec = 0.0
        goal_time_sec    = float(window_sec)

    meta = {
        "match_name":       MATCH_NAME,
        "match_round":      MATCH_ROUND,
        "goal_frame_raw":   int(gf),
        "goal_time_sec":    round(goal_time_sec, 3),
        "window_start_sec": round(window_start_sec, 3),
        "window_end_sec":   round(goal_time_sec, 3),
        "window_sec":       window_sec,
        "window_frames":    len(window),
        "fps":              fps,
        "tracking_csv":     TRACKING_CSV,
        "output_csv":       OUTPUT_CSV,
    }

    print(f"  Goal frame : {gf}  ({_fmt_mmss(goal_time_sec)})")
    print(f"  Window     : {_fmt_mmss(window_start_sec)} 〜 {_fmt_mmss(goal_time_sec)}")
    print(f"  FPS        : {fps}  →  {window_frames} frames = {window_sec}s")
    print(f"  Captured   : {len(window)} frames")
    return window, meta


def _fmt_mmss(sec: float) -> str:
    """Convert seconds to MM:SS string."""
    m, s = divmod(int(sec), 60)
    return f"{m}:{s:02d}"


# ── Step 3: reformat to export schema ─────────────────────────────────────────

def reformat_to_22player_schema(
    window: pd.DataFrame, fps: int, window_start_sec: float = 0.0
) -> pd.DataFrame:
    """
    Convert internal columns to the export schema.

    Frame           : 1-based sequential integer
    Time            : Frame / fps  (relative seconds, 5 decimal places)
    Match_Time_sec  : window_start_sec + Time  (absolute match clock, 3 dp)
    X, Y            : normalised [0,1]  (5 decimal places)
    GridID          : integer 1-7140
    xT              : float (5 decimal places)
    """
    n   = len(window)
    out = pd.DataFrame()

    out["Frame"] = np.arange(1, n + 1)
    out["Time"]  = (out["Frame"] / fps).round(5)
    out["Match_Time_sec"] = (window_start_sec + out["Time"]).round(3)

    # Ball (4 cols)
    out["Ball_X"]      = window["ball_x"].round(5).values
    out["Ball_Y"]      = window["ball_y"].round(5).values
    out["Ball_GridID"] = window["ball_GridID"].values
    out["Ball_xT"]     = window["ball_xT"].round(5).values

    # Home players (11 × 4 = 44 cols)
    for i in range(1, 12):
        src = f"Home_{i}"
        out[f"Home_P{i}_X"]      = window[f"{src}_x"].round(5).values
        out[f"Home_P{i}_Y"]      = window[f"{src}_y"].round(5).values
        out[f"Home_P{i}_GridID"] = window[f"{src}_GridID"].values
        out[f"Home_P{i}_xT"]     = window[f"{src}_xT"].round(5).values

    # Away players (11 × 4 = 44 cols)
    for i in range(1, 12):
        src = f"Away_{i}"
        out[f"Away_P{i}_X"]      = window[f"{src}_x"].round(5).values
        out[f"Away_P{i}_Y"]      = window[f"{src}_y"].round(5).values
        out[f"Away_P{i}_GridID"] = window[f"{src}_GridID"].values
        out[f"Away_P{i}_xT"]     = window[f"{src}_xT"].round(5).values

    # Team aggregate xT (4 cols)
    home_xt_cols = [f"Home_P{i}_xT" for i in range(1, 12)]
    away_xt_cols = [f"Away_P{i}_xT" for i in range(1, 12)]

    home_xt = out[home_xt_cols].apply(pd.to_numeric, errors="coerce")
    away_xt = out[away_xt_cols].apply(pd.to_numeric, errors="coerce")

    out["Home_MAX_xT"] = home_xt.max(axis=1).round(5)
    out["Home_SUM_xT"] = home_xt.sum(axis=1).round(5)
    out["Away_MAX_xT"] = away_xt.max(axis=1).round(5)
    out["Away_SUM_xT"] = away_xt.sum(axis=1).round(5)

    return out   # rows × 98 cols


# ── Zone evaluation (non-destructive extension) ────────────────────────────────

ZONE_SAFE_MAX     = 0.33   # normalised X: safe zone upper bound (Home's perspective)
ZONE_BUILD_MAX    = 0.66   # normalised X: build zone upper / attacking third start
BALL_CONTROL_M    = 2.0    # metres: ball-holder detection radius
PASS_TRAVEL_MIN_M = 8.0    # metres: minimum ball travel to qualify as a through-pass
DEF_PROXIMITY_M   = 3.0    # metres: defenders counted if within this radius at reception
LBP_LOOKAHEAD     = 30     # frames: look-ahead window (30 frames = 3s at 10fps)


def _dist_m(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance in metres between two normalised-[0,1] pitch coordinates."""
    return float(np.sqrt(((x1 - x2) * 105.0) ** 2 + ((y1 - y2) * 68.0) ** 2))


def _effective_x(x_norm: float, team: str) -> float:
    """Return X in the team's own attacking direction (0=own goal, 1=opponent goal)."""
    return (1.0 - x_norm) if team == "Away" else x_norm


def add_zone_and_lbp_columns(df: pd.DataFrame, fps: int) -> pd.DataFrame:
    """
    Append zone-evaluation columns to the export dataframe.
    Non-destructive: adds columns only, never modifies existing ones.
    If columns already exist (e.g. loaded from a saved CSV) returns df unchanged.

    New columns
    -----------
    is_line_breaking_pass : int  1 while a line-breaking pass is in progress, else 0
    lbp_passer            : str  "Home_P3" style player id of passer (empty string if none)
    lbp_receiver          : str  player id of the receiver            (empty string if none)
    lbp_nearby_def_count  : int  defenders within DEF_PROXIMITY_M of the reception point
    """
    if "is_line_breaking_pass" in df.columns:
        return df   # already annotated

    n          = len(df)
    is_lbp     = np.zeros(n, dtype=np.int8)
    lbp_passer = [""] * n
    lbp_recv   = [""] * n
    lbp_defs   = np.zeros(n, dtype=np.int8)

    h_nums = [i for i in range(1, 12) if f"Home_P{i}_X" in df.columns]
    a_nums = [i for i in range(1, 12) if f"Away_P{i}_X" in df.columns]

    def _find_holder(row, bx: float, by: float):
        best_key, best_d = (None, None), np.inf
        for prefix, nums in [("Home", h_nums), ("Away", a_nums)]:
            for num in nums:
                px = row.get(f"{prefix}_P{num}_X", np.nan)
                py = row.get(f"{prefix}_P{num}_Y", np.nan)
                if pd.isna(px) or pd.isna(py):
                    continue
                d = _dist_m(float(px), float(py), bx, by)
                if d < best_d:
                    best_d, best_key = d, (prefix, num)
        return best_key if best_d <= BALL_CONTROL_M else (None, None)

    i = 0
    while i < n:
        row = df.iloc[i]
        bx  = float(row.get("Ball_X", np.nan))
        by  = float(row.get("Ball_Y", np.nan))
        if np.isnan(bx) or np.isnan(by):
            i += 1
            continue

        p_team, p_num = _find_holder(row, bx, by)
        if p_team is None:
            i += 1
            continue

        px_norm = float(row.get(f"{p_team}_P{p_num}_X", np.nan))
        eff_px  = _effective_x(px_norm, p_team)
        if not (ZONE_SAFE_MAX <= eff_px < ZONE_BUILD_MAX):
            i += 1
            continue

        found = False
        for k in range(1, min(LBP_LOOKAHEAD + 1, n - i)):
            frow = df.iloc[i + k]
            fbx  = float(frow.get("Ball_X", np.nan))
            fby  = float(frow.get("Ball_Y", np.nan))
            if np.isnan(fbx) or np.isnan(fby):
                continue
            if _dist_m(bx, by, fbx, fby) < PASS_TRAVEL_MIN_M:
                continue

            r_team, r_num = _find_holder(frow, fbx, fby)
            if r_team is None or r_team != p_team or r_num == p_num:
                continue

            rx_norm = float(frow.get(f"{r_team}_P{r_num}_X", np.nan))
            eff_rx  = _effective_x(rx_norm, r_team)
            if eff_rx < ZONE_BUILD_MAX:
                continue

            def_prefix = "Away" if p_team == "Home" else "Home"
            def_nums   = a_nums if p_team == "Home" else h_nums
            nearby     = 0
            for dn in def_nums:
                dx = frow.get(f"{def_prefix}_P{dn}_X", np.nan)
                dy = frow.get(f"{def_prefix}_P{dn}_Y", np.nan)
                if not (pd.isna(dx) or pd.isna(dy)):
                    if _dist_m(float(dx), float(dy), fbx, fby) <= DEF_PROXIMITY_M:
                        nearby += 1

            pid = f"{p_team}_P{p_num}"
            rid = f"{r_team}_P{r_num}"
            for j in range(i, i + k + 1):
                is_lbp[j]     = 1
                lbp_passer[j] = pid
                lbp_recv[j]   = rid
                lbp_defs[j]   = nearby

            found = True
            i += k + 1
            break

        if not found:
            i += 1

    out = df.copy()
    out["is_line_breaking_pass"] = is_lbp.astype(int)
    out["lbp_passer"]            = lbp_passer
    out["lbp_receiver"]          = lbp_recv
    out["lbp_nearby_def_count"]  = lbp_defs.astype(int)
    return out


# ── main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import json as _json

    for f in [XT_MAP_CSV, TRACKING_CSV]:
        if not Path(f).exists():
            sys.exit(f"ERROR: {f} not found. Run generate_sample_tracking_22.py first.")

    print("=" * 60)
    print("  Pitch Log - 22-Player Tracking Processor")
    print("=" * 60)

    print(f"\n[Load] xT map  : {XT_MAP_CSV}")
    xt_map = load_xt_map(XT_MAP_CSV)
    print(f"       shape   : {xt_map.shape}  max={xt_map.max():.4f}")

    print(f"\n[Load] Tracking: {TRACKING_CSV}")
    tracking = pd.read_csv(TRACKING_CSV)
    print(f"       shape   : {tracking.shape}")
    print(f"       Home nums: {detect_team_nums(tracking, 'Home')}")
    print(f"       Away nums: {detect_team_nums(tracking, 'Away')}")

    fps = auto_detect_fps(tracking)
    print(f"       FPS auto-detected: {fps}")

    print("\n[Step 1] Assigning GridID and xT to all 22 players + ball …")
    enriched = assign_grid_and_xt_22(tracking, xt_map)

    print("\n[Step 2] Extracting 30-second goal window …")
    window, meta = extract_goal_window(enriched, fps)

    print("\n[Step 3] Reformatting to 22-player export schema …")
    result = reformat_to_22player_schema(window, fps, meta["window_start_sec"])

    print("\n[Step 3b] Computing zone evaluation and line-breaking pass detection ...")
    result = add_zone_and_lbp_columns(result, fps)
    lbp_count = int(result["is_line_breaking_pass"].sum())
    print(f"  Line-breaking passes detected: {lbp_count} frames flagged")

    result.to_csv(OUTPUT_CSV, index=False)
    print(f"\n  Saved -> {OUTPUT_CSV}")
    print(f"  Shape : {result.shape[0]} rows × {result.shape[1]} cols")
    print(f"  Cols  : {list(result.columns[:8])} …")

    with open(MATCH_INFO_JSON, "w", encoding="utf-8") as _f:
        _json.dump(meta, _f, indent=2, ensure_ascii=False)
    print(f"  Saved -> {MATCH_INFO_JSON}")
    print(f"    Match : {meta['match_name']} | {meta['match_round']}")
    print(f"    Window: {_fmt_mmss(meta['window_start_sec'])} 〜 {_fmt_mmss(meta['window_end_sec'])}")
    print("\n  Done.")

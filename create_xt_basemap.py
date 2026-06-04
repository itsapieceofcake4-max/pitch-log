"""
create_xt_basemap.py
====================
Pitch Log — xT Base Map Generator (105 × 68 grid)

Pipeline
--------
Step 1  Fetch all matches from chosen competitions via statsbombpy
Step 2  Extract Pass / Carry / Shot events and preprocess
Step 3  Markov-chain value iteration → xT map
Step 4  Export  xT_BaseMap_105x68.csv
        Columns: Y_Grid | X0_ID1 | X1_ID2 | … | X104_ID105
        Rows   : 68 (one per Y-bin, 0 = bottom touchline)
"""

import sys
import warnings
from time import time

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# ───────────────────────────── constants ──────────────────────────────────────
PITCH_X      = 120.0
PITCH_Y      = 80.0
X_BINS       = 105
Y_BINS       = 68
N_CELLS      = X_BINS * Y_BINS          # 7 140
OUTPUT_CSV   = "xT_BaseMap_105x68.csv"

# Competitions to use (La Liga all 18 seasons + Champions League all 18 seasons)
# Feel free to extend or reduce this list.
COMPETITIONS = [
    (43, 106),    # FIFA World Cup 2022 – 64 matches
]

# ─────────────────────────── Step 1: data fetch ───────────────────────────────

def fetch_all_events(competitions: list) -> pd.DataFrame:
    """Download all match events for the given competition list."""
    try:
        from statsbombpy import sb
    except ImportError:
        sys.exit("ERROR: statsbombpy not installed. Run: pip install statsbombpy")

    all_frames = []
    total_matches = 0

    for (comp_id, season_filter) in competitions:
        comps_df = sb.competitions()
        rows = comps_df[comps_df["competition_id"] == comp_id]
        if season_filter is not None:
            rows = rows[rows["season_id"] == season_filter]

        for _, row in rows.iterrows():
            sid   = int(row["season_id"])
            cname = row["competition_name"]
            sname = row["season_name"]

            matches = sb.matches(competition_id=comp_id, season_id=sid)
            n = len(matches)
            total_matches += n
            print(f"  [{cname} {sname}] {n} matches …", flush=True)

            for mid in matches["match_id"].tolist():
                try:
                    ev = sb.events(match_id=mid)
                    # keep only Pass / Carry / Shot
                    ev = ev[ev["type"].isin({"Pass", "Carry", "Shot"})].copy()
                    if len(ev):
                        all_frames.append(ev)
                except Exception as exc:
                    print(f"    WARNING match {mid}: {exc}")

    print(f"\n  Total matches processed : {total_matches}")
    if not all_frames:
        sys.exit("ERROR: no events retrieved.")

    raw = pd.concat(all_frames, ignore_index=True)
    print(f"  Raw events (Pass/Carry/Shot): {len(raw):,}")
    return raw


# ─────────────────────────── Step 2: preprocessing ───────────────────────────

def _extract_coord(series: pd.Series, idx: int) -> pd.Series:
    return series.apply(
        lambda v: float(v[idx]) if isinstance(v, (list, tuple)) and len(v) > idx else np.nan
    )


def preprocess(raw: pd.DataFrame) -> pd.DataFrame:
    """Normalise coords, create flag columns, return clean DataFrame."""
    df = raw.copy()

    # ── origin coords ────────────────────────────────────────────────────────
    df["x"] = _extract_coord(df["location"], 0) / PITCH_X
    df["y"] = _extract_coord(df["location"], 1) / PITCH_Y

    # ── destination coords ───────────────────────────────────────────────────
    def _dest(row):
        t = row["type"]
        if t == "Pass":
            loc = row.get("pass_end_location")
        elif t == "Carry":
            loc = row.get("carry_end_location")
        else:
            return np.nan, np.nan
        if isinstance(loc, (list, tuple)) and len(loc) >= 2:
            return float(loc[0]) / PITCH_X, float(loc[1]) / PITCH_Y
        return np.nan, np.nan

    dest = df.apply(_dest, axis=1, result_type="expand")
    df["end_x"] = dest[0]
    df["end_y"]  = dest[1]

    # ── flags ────────────────────────────────────────────────────────────────
    df["type_name"] = df["type"]

    df["is_shot"] = (df["type_name"] == "Shot").astype(np.int8)

    df["is_goal"] = (
        (df["type_name"] == "Shot") &
        (df.get("shot_outcome", pd.Series(dtype=object))
           .fillna("").astype(str).str.strip() == "Goal")
    ).astype(np.int8)

    def _successful(row):
        if row["type_name"] == "Carry":
            return 1
        if row["type_name"] == "Pass":
            return 1 if pd.isna(row.get("pass_outcome")) else 0
        return 0

    df["is_successful_move"] = df.apply(_successful, axis=1).astype(np.int8)

    df = df.dropna(subset=["x", "y"]).reset_index(drop=True)
    print(f"  Clean events after dropna  : {len(df):,}")
    return df[["type_name", "x", "y", "end_x", "end_y",
               "is_shot", "is_goal", "is_successful_move"]]


# ─────────────────────────── Step 3: xT model ────────────────────────────────

def _coord_to_bin(x_norm: np.ndarray, y_norm: np.ndarray):
    xi = np.clip(np.floor(x_norm * X_BINS).astype(int), 0, X_BINS - 1)
    yi = np.clip(np.floor(y_norm * Y_BINS).astype(int), 0, Y_BINS - 1)
    return xi, yi


def compute_xt(df: pd.DataFrame, n_iter: int = 15) -> np.ndarray:
    """
    Markov-chain value iteration.

    V(c) = s(c)·g(c)  +  m(c)·Σ_{c'} T(c→c')·V(c')

    Returns
    -------
    np.ndarray, shape (Y_BINS, X_BINS)
    """
    n = N_CELLS

    C     = np.zeros(n, dtype=np.float64)   # total actions in cell
    S     = np.zeros(n, dtype=np.float64)   # shots
    G     = np.zeros(n, dtype=np.float64)   # goals (given shot)
    M     = np.zeros(n, dtype=np.float64)   # successful moves
    T_num = np.zeros((n, n), dtype=np.float32)

    xi_from, yi_from = _coord_to_bin(df["x"].values, df["y"].values)
    cell_from = yi_from * X_BINS + xi_from

    shots = df["is_shot"].values
    goals = df["is_goal"].values
    moves = df["is_successful_move"].values
    ex_vals = df["end_x"].values
    ey_vals = df["end_y"].values

    print("  Building count arrays …", flush=True)
    for i in range(len(df)):
        c = cell_from[i]
        C[c] += 1.0
        if shots[i]:
            S[c] += 1.0
            if goals[i]:
                G[c] += 1.0
        elif moves[i]:
            ex, ey = ex_vals[i], ey_vals[i]
            if not (np.isnan(ex) or np.isnan(ey)):
                xi_t, yi_t = _coord_to_bin(
                    np.array([ex]), np.array([ey])
                )
                c_to = int(yi_t[0]) * X_BINS + int(xi_t[0])
                M[c] += 1.0
                T_num[c, c_to] += 1.0

    eps = 1e-9
    with np.errstate(invalid="ignore", divide="ignore"):
        s_prob = np.where(C > 0, S / C, 0.0)
        g_prob = np.where(S > 0, G / S, 0.0)
        m_prob = np.where(C > 0, M / C, 0.0)

        row_sums = T_num.sum(axis=1, keepdims=True)
        T = np.where(row_sums > 0, T_num / (row_sums + eps), 0.0)

    print(f"  Value iteration ({n_iter} steps) …", flush=True)
    V = np.zeros(n, dtype=np.float64)
    for k in range(n_iter):
        V_new = s_prob * g_prob + m_prob * (T @ V)
        delta = np.abs(V_new - V).max()
        V = V_new
        print(f"    iter {k+1:>2d}  max_delta={delta:.8f}  "
              f"max_xT={V.max():.6f}", flush=True)
        if delta < 1e-9:
            print("    Converged early.")
            break

    return V.reshape(Y_BINS, X_BINS)


# ─────────────────────────── Step 4: export CSV ──────────────────────────────

def export_csv(xt_map: np.ndarray, path: str = OUTPUT_CSV) -> None:
    """
    Write xT_BaseMap_105x68.csv.

    Format
    ------
    Columns: Y_Grid | X0_ID1 | X1_ID2 | … | X104_ID105
    Rows   : 68 rows (Y_Grid 0 = bottom touchline, 67 = top)
    Values : xT probability for each 1 m² cell
    """
    col_names = ["Y_Grid"] + [f"X{x}_ID{x+1}" for x in range(X_BINS)]

    rows = []
    for yi in range(Y_BINS):
        row = [yi] + xt_map[yi, :].tolist()
        rows.append(row)

    out = pd.DataFrame(rows, columns=col_names)
    out.to_csv(path, index=False, float_format="%.8f")
    print(f"\n  Saved → {path}")
    print(f"  Shape : {out.shape}  ({Y_BINS} rows × {X_BINS + 1} columns)")
    print(f"  xT stats — min={xt_map.min():.6f}  "
          f"max={xt_map.max():.6f}  mean={xt_map.mean():.8f}")


# ──────────────────────────────── main ───────────────────────────────────────

if __name__ == "__main__":
    t0 = time()

    print("=" * 60)
    print("  Pitch Log - xT Base Map Creator")
    print("  Grid: 105 × 68  |  Cells: 7 140")
    print("=" * 60)

    # Step 1
    print("\n[Step 1] Fetching event data …")
    raw = fetch_all_events(COMPETITIONS)

    # Step 2
    print("\n[Step 2] Preprocessing …")
    df = preprocess(raw)
    print(f"  is_shot sum          : {df['is_shot'].sum():,}")
    print(f"  is_goal sum          : {df['is_goal'].sum():,}")
    print(f"  is_successful_move   : {df['is_successful_move'].sum():,}")

    # Step 3
    print("\n[Step 3] Computing xT via Markov-chain iteration …")
    xt_map = compute_xt(df, n_iter=15)

    # Step 4
    print("\n[Step 4] Exporting CSV …")
    export_csv(xt_map, OUTPUT_CSV)

    elapsed = time() - t0
    print(f"\n  Total time: {elapsed/60:.1f} min ({elapsed:.0f} s)")
    print("  Done.")

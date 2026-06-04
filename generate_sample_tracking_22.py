"""
generate_sample_tracking_22.py
================================
Generate synthetic 22-player tracking data (Home 11 + Away 11 + ball).

Home attacks left → right (positive X direction).
Away defends, retreating as Home builds up the goal.
Goal at frame 1499 (last frame of 60 sec @ 25 fps).

Output
------
  Sample_TrackingData_22.csv
  Rows  : 1500  (60 sec × 25 fps)
  Cols  : 49   (frame, time_sec, ball_x/y, is_goal_frame,
                Home_1_x/y … Home_11_x/y,
                Away_1_x/y … Away_11_x/y)
"""

import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline

FPS   = 25
TOTAL = 60          # seconds
N     = TOTAL * FPS # 1500 frames

rng = np.random.default_rng(42)


def smooth_path(waypoints, noise: float = 0.004, n: int = N):
    """Interpolate list of (x,y) waypoints with cubic spline + small Gaussian noise."""
    t  = np.linspace(0, 1, len(waypoints))
    xs = np.array([p[0] for p in waypoints])
    ys = np.array([p[1] for p in waypoints])
    tt = np.linspace(0, 1, n)
    xv = np.clip(CubicSpline(t, xs)(tt) + rng.normal(0, noise, n), 0.01, 0.99)
    yv = np.clip(CubicSpline(t, ys)(tt) + rng.normal(0, noise, n), 0.01, 0.99)
    return xv, yv


# ── Ball: midfield → away penalty area → goal ─────────────────────────────────
BALL_WPT = [
    (0.30, 0.55), (0.42, 0.48), (0.50, 0.62),
    (0.60, 0.55), (0.68, 0.40), (0.75, 0.52),
    (0.82, 0.48), (0.88, 0.50), (0.93, 0.52), (0.97, 0.50),
]
ball_x, ball_y = smooth_path(BALL_WPT, noise=0.002)

# ── Home team (blue, attacking right) ─────────────────────────────────────────
# Roles: 1=GK  2=RB  3=CB  4=CB  5=LB  6=CDM  7=RM  8=CM  9=ST  10=CAM  11=LM
HOME = {
    1:  [(0.04, 0.50), (0.04, 0.50), (0.05, 0.48), (0.05, 0.50)],
    2:  [(0.22, 0.16), (0.36, 0.18), (0.52, 0.14), (0.68, 0.12)],
    3:  [(0.20, 0.36), (0.33, 0.35), (0.46, 0.34), (0.60, 0.35)],
    4:  [(0.20, 0.64), (0.33, 0.65), (0.46, 0.66), (0.60, 0.65)],
    5:  [(0.22, 0.84), (0.36, 0.82), (0.52, 0.86), (0.68, 0.88)],
    6:  [(0.38, 0.50), (0.50, 0.47), (0.63, 0.48), (0.74, 0.50)],
    7:  [(0.50, 0.20), (0.62, 0.22), (0.73, 0.20), (0.85, 0.18)],
    8:  [(0.48, 0.50), (0.58, 0.52), (0.69, 0.50), (0.79, 0.52)],
    9:  [(0.62, 0.50), (0.73, 0.48), (0.86, 0.50), (0.95, 0.50)],
    10: [(0.58, 0.56), (0.69, 0.58), (0.81, 0.57), (0.92, 0.53)],
    11: [(0.50, 0.80), (0.62, 0.78), (0.73, 0.80), (0.85, 0.82)],
}

# ── Away team (red, defending — retreating as Home advances) ──────────────────
# Roles: 1=GK  2=RB  3=CB  4=CB  5=LB  6=CM  7=RM  8=CM  9=ST  10=SS  11=LM
AWAY = {
    1:  [(0.96, 0.50), (0.96, 0.50), (0.96, 0.50), (0.96, 0.50)],
    2:  [(0.78, 0.84), (0.70, 0.82), (0.62, 0.84), (0.50, 0.82)],
    3:  [(0.80, 0.62), (0.73, 0.62), (0.67, 0.63), (0.58, 0.63)],
    4:  [(0.80, 0.38), (0.73, 0.38), (0.67, 0.37), (0.58, 0.37)],
    5:  [(0.78, 0.16), (0.70, 0.18), (0.62, 0.16), (0.50, 0.18)],
    6:  [(0.65, 0.50), (0.58, 0.50), (0.52, 0.48), (0.43, 0.48)],
    7:  [(0.63, 0.22), (0.56, 0.24), (0.50, 0.22), (0.40, 0.25)],
    8:  [(0.63, 0.50), (0.57, 0.50), (0.51, 0.52), (0.42, 0.50)],
    9:  [(0.55, 0.43), (0.48, 0.42), (0.40, 0.43), (0.30, 0.42)],
    10: [(0.55, 0.58), (0.48, 0.58), (0.40, 0.57), (0.30, 0.58)],
    11: [(0.63, 0.78), (0.56, 0.76), (0.50, 0.78), (0.40, 0.75)],
}

# ── assemble DataFrame ────────────────────────────────────────────────────────
data: dict = {
    "frame":         np.arange(N),
    "time_sec":      np.arange(N) / FPS,
    "ball_x":        ball_x,
    "ball_y":        ball_y,
    "is_goal_frame": np.zeros(N, dtype=int),
}
data["is_goal_frame"][N - 1] = 1

for num, wpts in HOME.items():
    hx, hy = smooth_path(wpts)
    data[f"Home_{num}_x"] = hx
    data[f"Home_{num}_y"] = hy

for num, wpts in AWAY.items():
    ax, ay = smooth_path(wpts)
    data[f"Away_{num}_x"] = ax
    data[f"Away_{num}_y"] = ay

df = pd.DataFrame(data)
df.to_csv("Sample_TrackingData_22.csv", index=False)

print(f"Saved  Sample_TrackingData_22.csv")
print(f"Shape  {df.shape[0]} rows x {df.shape[1]} cols")
print(f"Cols   {list(df.columns)}")

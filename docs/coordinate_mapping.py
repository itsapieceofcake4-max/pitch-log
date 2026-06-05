"""
coordinate_mapping.py
=====================
Pitch Log の現在の座標マッピングを1枚の図に可視化する。
出力: docs/coordinate_mapping.png
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

# Windows の日本語フォントを優先指定（豆腐化防止）
for _f in ["Meiryo", "Yu Gothic", "MS Gothic", "Yu Gothic UI"]:
    if any(_f.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = _f
        break
plt.rcParams["axes.unicode_minus"] = False
from matplotlib.patches import Rectangle, FancyArrow
import numpy as np

PITCH_W, PITCH_H = 105.0, 68.0
X_BINS, Y_BINS = 105, 68

fig, ax = plt.subplots(figsize=(13, 9))
fig.patch.set_facecolor("#0e1825")
ax.set_facecolor("#1a3d1a")

# ── pitch outline ──────────────────────────────────────────────────────────
lc = "white"
ax.add_patch(Rectangle((0, 0), PITCH_W, PITCH_H, fill=False, ec=lc, lw=2))
ax.plot([PITCH_W/2, PITCH_W/2], [0, PITCH_H], color=lc, lw=1.5)
ax.add_patch(plt.Circle((PITCH_W/2, PITCH_H/2), 9.15, fill=False, ec=lc, lw=1.5))
# penalty areas
ax.add_patch(Rectangle((0, PITCH_H/2-20.16), 16.5, 40.32, fill=False, ec=lc, lw=1.3))
ax.add_patch(Rectangle((PITCH_W-16.5, PITCH_H/2-20.16), 16.5, 40.32, fill=False, ec=lc, lw=1.3))
# goals
ax.add_patch(Rectangle((-2, PITCH_H/2-3.66), 2, 7.32, fill=False, ec=lc, lw=1.3))
ax.add_patch(Rectangle((PITCH_W, PITCH_H/2-3.66), 2, 7.32, fill=False, ec=lc, lw=1.3))

# ── axes annotations ───────────────────────────────────────────────────────
# Origin marker
ax.plot(0, 0, "o", color="#FFD700", ms=12, zorder=5)
ax.annotate("原点 (0, 0)\n= 左下コーナー\n正規化 (0.0, 0.0)",
            xy=(0, 0), xytext=(8, -7), color="#FFD700", fontsize=11, weight="bold",
            arrowprops=dict(arrowstyle="->", color="#FFD700"))

# X axis arrow + labels
ax.annotate("", xy=(PITCH_W, -5), xytext=(0, -5),
            arrowprops=dict(arrowstyle="->", color="#5ec4ff", lw=2))
ax.text(PITCH_W/2, -8.5, "X 軸:  0  →  105 m   (正規化 0.0 → 1.0)",
        color="#5ec4ff", fontsize=12, ha="center", weight="bold")
ax.text(0, -3.0, "x=0\n左ゴール", color="#5ec4ff", fontsize=9, ha="center")
ax.text(PITCH_W, -3.0, "x=105\n右ゴール", color="#5ec4ff", fontsize=9, ha="center")

# Y axis arrow + labels
ax.annotate("", xy=(-6, PITCH_H), xytext=(-6, 0),
            arrowprops=dict(arrowstyle="->", color="#4ade80", lw=2))
ax.text(-9.5, PITCH_H/2, "Y 軸:  0 → 68 m\n(正規化 0.0 → 1.0)",
        color="#4ade80", fontsize=11, ha="center", va="center",
        rotation=90, weight="bold")
ax.text(-3.5, 0, "y=0 下", color="#4ade80", fontsize=9, va="center")
ax.text(-3.5, PITCH_H, "y=68 上", color="#4ade80", fontsize=9, va="center")

# ── attack directions ──────────────────────────────────────────────────────
ax.annotate("", xy=(PITCH_W*0.62, PITCH_H+4), xytext=(PITCH_W*0.38, PITCH_H+4),
            arrowprops=dict(arrowstyle="-|>", color="#3b9eff", lw=3))
ax.text(PITCH_W*0.5, PITCH_H+6.5, "Home 攻撃方向 →（高xT=右）",
        color="#3b9eff", fontsize=11, ha="center", weight="bold")
ax.annotate("", xy=(PITCH_W*0.38, PITCH_H+9.5), xytext=(PITCH_W*0.62, PITCH_H+9.5),
            arrowprops=dict(arrowstyle="-|>", color="#ff5555", lw=3))
ax.text(PITCH_W*0.5, PITCH_H+11.5, "← Away 攻撃方向（高xT=左, ミラー）",
        color="#ff5555", fontsize=11, ha="center", weight="bold")

# ── GridID examples ────────────────────────────────────────────────────────
def gid(xi, yi):
    return xi + yi * X_BINS + 1

samples = [
    (0, 0, "セル(0,0)"),
    (104, 0, "セル(104,0)"),
    (0, 67, "セル(0,67)"),
    (104, 67, "セル(104,67)"),
    (52, 34, "中央セル(52,34)"),
]
for xi, yi, label in samples:
    cx, cy = xi + 0.5, yi + 0.5
    ax.add_patch(Rectangle((xi, yi), 1, 1, color="#FFD700", alpha=0.85, zorder=4))
    ax.annotate(f"{label}\nGridID={gid(xi,yi)}",
                xy=(cx, cy), xytext=(cx + (10 if xi < 52 else -10), cy + (8 if yi < 34 else -8)),
                color="white", fontsize=8.5, ha="center",
                bbox=dict(boxstyle="round,pad=0.3", fc="#13202f", ec="#FFD700", alpha=0.9),
                arrowprops=dict(arrowstyle="->", color="#FFD700"))

# ── formula box ────────────────────────────────────────────────────────────
formula = (
    "GridID = X_idx + Y_idx × 105 + 1\n"
    "範囲: 1 〜 7140 (105×68セル)\n"
    "X_idx = floor(x_norm × 105)  (0..104)\n"
    "Y_idx = floor(y_norm × 68)   (0..67)"
)
ax.text(PITCH_W/2, PITCH_H/2, formula, color="white", fontsize=11, ha="center", va="center",
        bbox=dict(boxstyle="round,pad=0.6", fc="#13202f", ec="#5ec4ff", lw=1.5, alpha=0.92))

ax.set_xlim(-16, PITCH_W + 8)
ax.set_ylim(-13, PITCH_H + 14)
ax.set_aspect("equal")
ax.axis("off")
ax.set_title("Pitch Log — 座標マッピング (105×68 グリッド)",
             color="white", fontsize=15, weight="bold", pad=14)

plt.tight_layout()
out = "docs/coordinate_mapping.png"
plt.savefig(out, dpi=130, facecolor=fig.get_facecolor(), bbox_inches="tight")
print(f"saved -> {out}")

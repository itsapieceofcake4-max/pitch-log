"""
depth_mockup.py
===============
敵陣深度%（自陣ゴール=0% → 敵陣ゴール=100%）のビジュアル案モックアップ。
長辺方向に芝ストライプ風グラデで深度を表現する。
出力: docs/depth_mockup.png
"""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import Rectangle
import numpy as np

for _f in ["Meiryo", "Yu Gothic", "MS Gothic"]:
    if any(_f.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = _f
        break
plt.rcParams["axes.unicode_minus"] = False

PITCH_W, PITCH_H = 105.0, 68.0

fig, ax = plt.subplots(figsize=(13, 9))
fig.patch.set_facecolor("#0e1825")

# ── 芝ベース + 深度グラデ（Home視点: 右に行くほど敵陣深い） ──────────────────
nx = 420
depth = np.linspace(0, 1, nx)                       # 0(左/自陣) → 1(右/敵陣)
grid = np.tile(depth, (60, 1))

# 芝の縦ストライプ（明暗）
stripe = (np.floor(np.linspace(0, 10, nx)) % 2) * 0.04
base_green = np.zeros((60, nx, 3))
base_green[..., 0] = 0.26 + stripe                  # R
base_green[..., 1] = 0.55 + stripe                  # G
base_green[..., 2] = 0.20 + stripe                  # B
# 深度が深いほど暖色寄り（赤み）に寄せて「敵陣の深さ」を強調
warm = grid[..., None] * np.array([0.55, -0.18, -0.05])
img = np.clip(base_green + warm, 0, 1)
ax.imshow(img, extent=[0, PITCH_W, 0, PITCH_H], origin="lower", aspect="auto", zorder=0)

# ── pitch lines ─────────────────────────────────────────────────────────────
lc = "white"
ax.add_patch(Rectangle((0, 0), PITCH_W, PITCH_H, fill=False, ec=lc, lw=2))
ax.plot([PITCH_W/2, PITCH_W/2], [0, PITCH_H], color=lc, lw=1.5)
ax.add_patch(plt.Circle((PITCH_W/2, PITCH_H/2), 9.15, fill=False, ec=lc, lw=1.5))
ax.add_patch(Rectangle((0, PITCH_H/2-20.16), 16.5, 40.32, fill=False, ec=lc, lw=1.3))
ax.add_patch(Rectangle((PITCH_W-16.5, PITCH_H/2-20.16), 16.5, 40.32, fill=False, ec=lc, lw=1.3))

# ── 深度ルーラー（下） ───────────────────────────────────────────────────────
for pct in range(0, 101, 10):
    x = PITCH_W * pct / 100
    ax.plot([x, x], [0, 1.2], color="white", lw=1, alpha=0.5)
    ax.text(x, -3.0, f"{pct}%", color="#ffe08a", fontsize=9, ha="center", weight="bold")
ax.annotate("", xy=(PITCH_W, -6.5), xytext=(0, -6.5),
            arrowprops=dict(arrowstyle="-|>", color="#3b9eff", lw=2.5))
ax.text(PITCH_W/2, -9.5, "Home 敵陣深度:  自陣ゴール 0%  →  敵陣ゴール 100%",
        color="#3b9eff", fontsize=12, ha="center", weight="bold")
ax.text(2, PITCH_H+2, "← 自陣（浅い）", color="white", fontsize=10, ha="left")
ax.text(PITCH_W-2, PITCH_H+2, "敵陣（深い）→", color="#ff8a8a", fontsize=10, ha="right", weight="bold")

# ── サンプル選手 + 深度%ラベル ──────────────────────────────────────────────
def depth_home(xn): return xn * 100
def depth_away(xn): return (1 - xn) * 100

samples = [
    (0.18, 0.50, "Home", "#3b9eff"),
    (0.50, 0.35, "Home", "#3b9eff"),
    (0.82, 0.55, "Home", "#3b9eff"),
    (0.70, 0.30, "Away", "#ff5555"),
    (0.35, 0.62, "Away", "#ff5555"),
]
for xn, yn, team, col in samples:
    x, y = xn * PITCH_W, yn * PITCH_H
    d = depth_home(xn) if team == "Home" else depth_away(xn)
    ax.plot(x, y, "o", color=col, ms=22, mec="white", mew=2, zorder=5)
    ax.annotate(f"{team}\n深度 {d:.0f}%", xy=(x, y), xytext=(x, y+9),
                color="white", fontsize=9, ha="center", weight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc="#13202f", ec=col, alpha=0.9),
                arrowprops=dict(arrowstyle="->", color=col), zorder=6)

ax.text(PITCH_W/2, PITCH_H-5,
        "※ Away は左右ミラー（左ゴール=Awayの敵陣100%）",
        color="#ffd0d0", fontsize=10, ha="center",
        bbox=dict(boxstyle="round,pad=0.3", fc="#2a1010", ec="#ff5555", alpha=0.85))

ax.set_xlim(-4, PITCH_W + 4)
ax.set_ylim(-12, PITCH_H + 6)
ax.set_aspect("equal")
ax.axis("off")
ax.set_title("Pitch Log — 敵陣深度% ビジュアル案（連続）",
             color="white", fontsize=15, weight="bold", pad=12)

plt.tight_layout()
out = "docs/depth_mockup.png"
plt.savefig(out, dpi=130, facecolor=fig.get_facecolor(), bbox_inches="tight")
print(f"saved -> {out}")

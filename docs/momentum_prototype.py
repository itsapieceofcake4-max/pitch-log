"""
momentum_prototype.py
=====================
phases_of_play.csv から試合全体のモメンタムチャートを描く試作。
出力: docs/momentum_chart.png
"""
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

for _f in ["Meiryo", "Yu Gothic", "MS Gothic"]:
    if any(_f.lower() in f.name.lower() for f in font_manager.fontManager.ttflist):
        plt.rcParams["font.family"] = _f; break
plt.rcParams["axes.unicode_minus"] = False

HOME_ID, AWAY_ID = 1802, 871
HOME_NAME, AWAY_NAME = "Brisbane (Home)", "Perth (Away)"
C_HOME, C_AWAY = "#3b9eff", "#ff5555"
HALF_LEN = 45  # 表示用オフセット

csv = sys.argv[1] if len(sys.argv) > 1 else "phases_of_play.csv"
df = pd.read_csv(csv)

# 連続マッチ時間（分）: 後半は +45 オフセット
t = df["minute_start"] + df["second_start"] / 60.0
df["t_disp"] = np.where(df["period"] == 2, t + HALF_LEN, t)

# 脅威スコア（攻撃側視点）
score = (1.0
         + 2.0 * (df["third_end"] == "attacking_third")
         + 3.0 * df["team_possession_lead_to_shot"].astype(bool)
         + 8.0 * df["team_possession_lead_to_goal"].astype(bool))
sign = np.where(df["team_in_possession_id"] == HOME_ID, 1.0, -1.0)
df["signed"] = score * sign
df = df.sort_values("t_disp").reset_index(drop=True)

# 細かい時間グリッドでローリング5分 & 累積
grid = np.arange(0, df["t_disp"].max() + 1, 0.25)
roll = np.zeros_like(grid)
WIN = 5.0
for i, g in enumerate(grid):
    m = (df["t_disp"] > g - WIN) & (df["t_disp"] <= g)
    roll[i] = df.loc[m, "signed"].sum()
cum = np.array([df.loc[df["t_disp"] <= g, "signed"].sum() for g in grid])

# ゴール時刻（Away=Perthが1点 → lead_to_goalのAway phase）
goals = df[df["team_possession_lead_to_goal"].astype(bool)]

fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 8), sharex=True)
fig.patch.set_facecolor("#0e1825")
for ax in (ax1, ax2):
    ax.set_facecolor("#13202f")
    ax.axhline(0, color="white", lw=0.8, alpha=0.5)
    ax.axvline(HALF_LEN, color="#ffd700", lw=1.2, ls="--", alpha=0.7)
    ax.tick_params(colors="#b0c8e0")
    for s in ax.spines.values(): s.set_color("#234060")
    ax.grid(axis="y", color="white", alpha=0.06)

# ① ローリング5分
ax1.fill_between(grid, 0, np.clip(roll, 0, None), color=C_HOME, alpha=0.55, label=HOME_NAME)
ax1.fill_between(grid, 0, np.clip(roll, None, 0), color=C_AWAY, alpha=0.55, label=AWAY_NAME)
ax1.plot(grid, roll, color="white", lw=0.8, alpha=0.6)
ax1.set_title("① 5分ローリング モメンタム（局所優勢）", color="white", fontsize=13, weight="bold", loc="left")
ax1.legend(facecolor="#0e1825", edgecolor="#234060", labelcolor="white", loc="upper right", fontsize=10)
ax1.set_ylabel("脅威スコア(5分窓)", color="#b0c8e0")

# ② 累積
ax2.fill_between(grid, 0, np.clip(cum, 0, None), color=C_HOME, alpha=0.45)
ax2.fill_between(grid, 0, np.clip(cum, None, 0), color=C_AWAY, alpha=0.45)
ax2.plot(grid, cum, color="white", lw=1.5)
ax2.set_title("② 累積モメンタム（試合全体の優勢ドリフト）", color="white", fontsize=13, weight="bold", loc="left")
ax2.set_ylabel("累積 脅威スコア", color="#b0c8e0")
ax2.set_xlabel("試合時間（分）  ※点線=ハーフタイム", color="#b0c8e0")

# ゴールマーク
for _, g in goals.iterrows():
    col = C_HOME if g["team_in_possession_id"] == HOME_ID else C_AWAY
    for ax in (ax1, ax2):
        ax.axvline(g["t_disp"], color=col, lw=1.4, alpha=0.8)
    ax1.annotate("GOAL", xy=(g["t_disp"], ax1.get_ylim()[1]*0.82),
                 color=col, fontsize=9, weight="bold", ha="center")

fig.suptitle("Pitch Log — 試合モメンタムチャート（Brisbane 0-1 Perth）",
             color="white", fontsize=15, weight="bold")
ax1.text(HALF_LEN+0.5, ax1.get_ylim()[1]*0.9, "後半", color="#ffd700", fontsize=9)
ax1.text(HALF_LEN-4, ax1.get_ylim()[1]*0.9, "前半", color="#ffd700", fontsize=9, ha="right")

plt.tight_layout(rect=[0, 0, 1, 0.96])
out = "momentum_chart.png"
plt.savefig(out, dpi=130, facecolor=fig.get_facecolor(), bbox_inches="tight")
print("saved ->", out)
print(f"phases={len(df)}  Home可能性score>0時間割合={np.mean(roll>0):.0%}  最終累積={cum[-1]:.0f}")

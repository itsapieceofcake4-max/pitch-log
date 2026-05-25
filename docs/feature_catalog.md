# Pitch Log — 追加可能カラム カタログ

GSA説明変数として CSV に追加できる候補を網羅的に整理。

凡例：
- 🟢 = 実装簡単（1〜数行）
- 🟡 = 中程度（10〜30行）
- 🔴 = 大きめ（外部データ統合 or 複雑なロジック）
- ★ = GSA寄与度（多いほど強力）

---

## 📦 現状実装済み（v23 GSA拡張時点）

```
基本（v22 由来）
  Frame, Time, Match_Time_sec
  Ball_X, Ball_Y, Ball_GridID, Ball_xT
  {team}_P{1-11}_X / _Y / _GridID / _xT  × 22名
  Home/Away_MAX_xT, Home/Away_SUM_xT
  is_line_breaking_pass, lbp_passer/receiver/nearby_def_count

GSA拡張（v23 add_gsa_features）
  Delta_Ball_xT, Delta_Home/Away_MAX_xT, Delta_Home/Away_SUM_xT
  {team}_P{n}_dist_ball, {team}_P{n}_speed
  Ball_Zone_Home, Ball_Zone_Away
  Cumulative_Ball_xT_gain, Cumulative_{team}_MAX_xT_gain
```

合計 152〜157カラム

---

## ① 動き・速度系  🟢 簡単で高ROI

| カラム名 | 内容 | GSA価値 | 実装 |
|---|---|---|---|
| `Ball_vx`, `Ball_vy` | ボール速度成分 (m/s) | ★★★ | 🟢 |
| `Ball_speed` | ボール速度 (m/s) | ★★★ | 🟢 |
| `Ball_acceleration` | ボール加速度 (m/s²) | ★★ | 🟢 |
| `Ball_direction` | ボール進行方向 (角度) | ★★ | 🟢 |
| `Ball_dist_traveled` | 累積走行距離 (m) | ★ | 🟢 |
| `{team}_P{n}_vx`, `vy` | 各選手の速度成分 | ★★ | 🟢 |
| `{team}_P{n}_acceleration` | 各選手の加速度 | ★★★ | 🟢 |
| `{team}_P{n}_direction` | 各選手の進行方向 | ★ | 🟢 |
| `{team}_P{n}_is_sprinting` | スプリント判定 (>5.5m/s) | ★★ | 🟢 |
| `{team}_P{n}_dist_traveled` | 累積走行距離 | ★ | 🟢 |

→ 22選手分入れると 約 100 カラム追加

---

## ② 距離・位置関係  🟢 〜 🟡

| カラム名 | 内容 | GSA価値 | 実装 |
|---|---|---|---|
| `{team}_P{n}_dist_goal` | 各選手からゴールまでの距離 | ★★★ | 🟢 |
| `{team}_P{n}_dist_own_goal` | 自陣ゴールまでの距離 | ★★ | 🟢 |
| `{team}_P{n}_dist_nearest_opp` | 最近接相手選手との距離 | ★★★ | 🟡 |
| `{team}_P{n}_dist_nearest_team` | 最近接味方との距離 | ★★ | 🟡 |
| `{team}_P{n}_n_opp_within_3m` | 3m以内の相手選手数（プレッシャー） | ★★★ | 🟡 |
| `{team}_P{n}_n_opp_within_5m` | 5m以内の相手選手数 | ★★ | 🟡 |
| `Ball_dist_goal_home` | ボール→Homeゴール距離 | ★★ | 🟢 |
| `Ball_dist_goal_away` | ボール→Awayゴール距離 | ★★ | 🟢 |
| `Ball_carrier_id` | 現在のボール保持者ID | ★★★ | 🟡 |
| `Ball_carrier_team` | 保持チーム（Home/Away/None） | ★★★ | 🟡 |
| `Pressure_on_carrier` | 保持者への3m以内相手数 | ★★★ | 🟡 |

---

## ③ チーム形状・組織  🟡

| カラム名 | 内容 | GSA価値 | 実装 |
|---|---|---|---|
| `Home_centroid_X`, `_Y` | Home重心座標 | ★★ | 🟢 |
| `Away_centroid_X`, `_Y` | Away重心座標 | ★★ | 🟢 |
| `Home_width` | Home横幅 (Ymax - Ymin) | ★★ | 🟢 |
| `Home_depth` | Home縦幅 (Xmax - Xmin) | ★★ | 🟢 |
| `Home_compactness` | 選手間平均距離 | ★★ | 🟡 |
| `Home_hull_area` | 布陣カバー面積 (凸包) | ★★ | 🟡 |
| `Home_last_def_line_X` | 最終DFラインのX座標 | ★★★ | 🟢 |
| `Home_def_line_height` | DFラインの平均高さ | ★★ | 🟢 |
| `Home_mid_line_X` | 中盤ラインX座標 | ★★ | 🟡 |
| `Home_attack_line_X` | 攻撃ラインX座標 | ★★ | 🟡 |
| `Home_interline_dist_DF_MF` | DF-MF間距離 | ★★ | 🟡 |
| `Home_interline_dist_MF_FW` | MF-FW間距離 | ★★ | 🟡 |
| (Awayも同様) | | | |

→ チーム形状は **戦術的崩れ** を捉えるのに強力

---

## ④ ゾーン拡張  🟢

| カラム名 | 内容 | GSA価値 | 実装 |
|---|---|---|---|
| `Ball_Zone_5div` | 縦5分割 (1〜5) | ★★ | 🟢 |
| `Ball_Zone_lateral` | 横3分割 (left/center/right) | ★★ | 🟢 |
| `Ball_Grid20` | 5×4=20領域グリッド | ★★ | 🟢 |
| `Ball_in_penalty_area` | ペナルティエリア内フラグ | ★★★ | 🟢 |
| `Ball_in_box_18yard` | 18ヤードボックス内フラグ | ★★★ | 🟢 |
| `Ball_in_half_space` | ハーフスペース内フラグ | ★★ | 🟢 |
| `Ball_in_wide_channel` | サイドチャネル内フラグ | ★★ | 🟢 |
| `{team}_P{n}_Zone` | 各選手のゾーン | ★ | 🟢 |
| `Ball_zone_transition` | ゾーン変化フラグ (進入/退出) | ★★★ | 🟢 |
| `Ball_attacking_third_dwell_sec` | アタッキングサード滞在累計秒 | ★★ | 🟢 |

---

## ⑤ ボール所有・フェーズ  🟡

| カラム名 | 内容 | GSA価値 | 実装 |
|---|---|---|---|
| `Ball_possession` | Home/Away/None | ★★★ | 🟡 |
| `Possession_duration_sec` | 連続保持時間 | ★★★ | 🟡 |
| `Possession_team_phase` | ビルドアップ/トランジ等 | ★★ | 🔴 |
| `Defensive_phase` | ブロック構築/プレッシング等 | ★★ | 🔴 |
| `Is_open_play` | オープンプレー中か | ★ | 🟢 |
| `Is_set_piece` | セットプレー中か | ★ | 🟢 |

※ 元データに `ball_possession` 列があれば 🟢、なければ近接距離から推定 🟡

---

## ⑥ パス・前進系  🟡 〜 🔴

| カラム名 | 内容 | GSA価値 | 実装 |
|---|---|---|---|
| `Pass_event_flag` | パス発生フレーム | ★★★ | 🟡 |
| `Pass_xT_gain` | パスによるxT増加 | ★★★ | 🟡 |
| `Pass_distance_m` | パス距離 (m) | ★★ | 🟡 |
| `Pass_angle` | パス角度 | ★ | 🟡 |
| `Pass_forward_component_m` | パスの前進成分 (m) | ★★ | 🟡 |
| `Pass_breaks_line_count` | 突破ライン数 (0〜3) | ★★★ | 🔴 |
| `Pass_speed` | パス速度 (m/s) | ★ | 🟡 |
| `Ball_forward_velocity` | ボール前進速度 | ★★ | 🟢 |

---

## ⑦ 個人xT 変化系  🟢

| カラム名 | 内容 | GSA価値 | 実装 |
|---|---|---|---|
| `{team}_P{n}_Delta_xT` | 各選手のxT変化量 | ★★★ | 🟢 |
| `{team}_P{n}_Cumulative_xT_gain` | 各選手の累積xT獲得 | ★★ | 🟢 |
| `{team}_P{n}_xT_smoothed_3f` | 3フレーム移動平均xT | ★ | 🟢 |
| `{team}_P{n}_peak_xT_in_scene` | シーン中の最大xT | ★ | 🟢 |
| `{team}_P{n}_xT_acceleration` | xT変化の加速度 | ★ | 🟢 |
| `{team}_xT_weighted_centroid_X` | xT加重重心 | ★★ | 🟡 |

→ 22人 × 4列追加で約88カラム

---

## ⑧ 時間ラグ（GSA因果分析の本命）  🟢

GSAの時系列因果分析には**ラグ変数**が必須。

| カラム名 | 内容 | GSA価値 | 実装 |
|---|---|---|---|
| `Ball_xT_lag1` | 1フレーム前 (0.1秒前) | ★★★ | 🟢 |
| `Ball_xT_lag5` | 5フレーム前 (0.5秒前) | ★★★ | 🟢 |
| `Ball_xT_lag10` | 10フレーム前 (1秒前) | ★★★ | 🟢 |
| `Ball_xT_lag20` | 20フレーム前 (2秒前) | ★★ | 🟢 |
| `Ball_xT_lag30` | 30フレーム前 (3秒前) | ★ | 🟢 |
| `{team}_P{n}_xT_lag5` | 各選手xTの0.5秒前 | ★★★ | 🟢 |
| `{team}_P{n}_xT_lag10` | 各選手xTの1秒前 | ★★ | 🟢 |
| `{team}_P{n}_speed_lag5` | 各選手速度の0.5秒前 | ★★ | 🟢 |

→ **ラグ変数は GSA で因果方向を特定する核心**

---

## ⑨ dynamic_events.csv 連動  🔴 外部データ統合

| カラム名 | 内容 | GSA価値 | 実装 |
|---|---|---|---|
| `Is_pass_moment` | パス発生フレームフラグ | ★★★ | 🔴 |
| `Is_shot_moment` | シュート発生フレームフラグ | ★★★ | 🔴 |
| `Is_engagement_moment` | 守備接触発生フラグ | ★★★ | 🔴 |
| `Is_off_ball_run_active` | オフボールラン進行中 | ★★ | 🔴 |
| `Frame_xshot_start/end` | xshot値 (時系列) | ★★★ | 🔴 |
| `Frame_xloss_start/end` | xloss値 (時系列) | ★★ | 🔴 |
| `Cumulative_VAEP_attack` | 累積攻撃VAEP | ★★ | 🔴 |
| `Cumulative_VAEP_defend` | 累積守備VAEP | ★★ | 🔴 |
| `Phase_index` | プレーフェーズ番号 | ★ | 🔴 |
| `Pressing_chain_active` | プレッシングチェーン中 | ★★ | 🔴 |

※ raw frame ID で events を tracking と突合する必要あり

---

## ⑩ 目的変数候補の追加  🟢 〜 🟡

| カラム名 | 内容 | GSA価値 | 実装 |
|---|---|---|---|
| `Ball_xT_smoothed_5f` | ノイズ除去版 Ball_xT | 目的変数候補 | 🟢 |
| `Delta_Ball_xT_smoothed_3f` | ノイズ除去版 ΔxT | 目的変数候補 | 🟢 |
| `Ball_xT_squared` | xT² (大きな値を強調) | 目的変数候補 | 🟢 |
| `Ball_xT_max_in_5sec_window` | 5秒ウィンドウ最大xT | 目的変数候補 | 🟢 |
| `Time_to_peak_xT_sec` | xTピークまでの秒数 | 目的変数候補 | 🟢 |
| `Time_to_goal_sec` | ゴールまでの残り秒数 | 目的変数候補 | 🟢 |
| `Is_attacking_third_entry` | アタッキングサード進入フレーム | 目的変数候補 | 🟢 |
| `Is_penalty_area_entry` | ペナルティエリア進入フレーム | 目的変数候補 | 🟢 |

---

## 📊 推奨実装ロードマップ

### Phase 1: GSA基礎強化（最優先・全部🟢）
```
✅ 既に実装済
追加候補：
  - 個人 Delta_xT × 22                          (★★★)
  - 個人 acceleration × 22                      (★★★)
  - ボール 速度・加速度                          (★★★)
  - dist_goal × 22                              (★★★)
  - n_opp_within_3m × 22                        (★★★)
  - Ball_carrier_id, Ball_carrier_team           (★★★)
  - Ball ラグ変数 (lag5, lag10)                 (★★★)
  - DFラインX × 2チーム                         (★★)
  - チーム重心                                   (★★)

→ 約 +110 カラム追加 = 合計 267カラム
   実装時間: 30分
   GSA精度向上: 大
```

### Phase 2: 戦術的特徴量（🟡 中程度）
```
追加候補：
  - チーム形状（width, depth, compactness, hull）
  - チームライン（DF/MF/FW、line間距離）
  - ペナルティエリア・ハーフスペースフラグ
  - 個人xTラグ × 22

→ 約 +50 カラム
   実装時間: 1〜2時間
```

### Phase 3: dynamic_events 統合（🔴 大きめ）
```
追加候補：
  - イベントフラグ系（pass/shot/engagement）
  - 累積VAEP（attack/defend）
  - プレッシングチェーン情報

→ 約 +20 カラム
   実装時間: 半日
```

---

## 🎯 GSA目的変数として有望なもの

```
最有力候補（時系列・連続値）：
  1. Delta_Ball_xT (現状)
  2. Delta_Ball_xT_smoothed_3f (ノイズ除去版)
  3. Delta_Away_MAX_xT
  4. Cumulative_Ball_xT_gain
  5. Ball_xT_smoothed

イベント型（バイナリ・離散）：
  6. Is_attacking_third_entry
  7. Is_penalty_area_entry
  8. Is_shot_moment
  9. Is_goal_moment (= 最終フレームフラグ)

絶対量・状態：
  10. Ball_xT そのもの (現状)
  11. Away_MAX_xT そのもの (現状)
```

---

## ⚠️ 注意：多重共線性

以下のペアは**両方入れない**：

| ペア | 理由 |
|---|---|
| 位置(X,Y) と 個人xT | xTは位置から計算される |
| 個人xT と 個人GridID | GridIDも位置の関数 |
| MAX_xT と 個人xT全員 | MAXは個人xTの集計 |
| SUM_xT と 個人xT全員 | SUMは個人xTの集計 |
| Ball_speed と Ball_vx/vy | speedは成分から計算 |
| Pressure_on_carrier と n_opp_within_3m for carrier | 同じ情報 |

GSA投入時はどちらか片方を選ぶ。

---

## 💡 まとめ

| 優先度 | 列数 | 実装時間 | GSA効果 |
|---|---|---|---|
| **Phase 1** (動き・距離・ラグ) | +110 | 30分 | ★★★ |
| Phase 2 (チーム形状・ライン) | +50 | 1〜2h | ★★ |
| Phase 3 (events統合) | +20 | 半日 | ★★ |

**月曜のGSA回しに間に合わせるなら Phase 1 だけでも大きな効果が見込めます。**

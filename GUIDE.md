# Pitch Log — ファイル配置・実行ガイド

## フォルダ構成（すべて同じフォルダに置く）

```
📁 作業フォルダ/
│
│  ─── 最初から存在するファイル ───────────────────────────────────
├── xT_BaseMap_105x68.csv               ← xTベースマップ（生成済み・触らない）
│
│  ─── Pythonスクリプト ─────────────────────────────────────────
├── fetch_skillcorner_1925299.py        ← [Step 0a] SkillCornerデータDL（実データ用）
├── convert_skillcorner_to_pipeline.py  ← [Step 0b] SkillCorner→パイプライン変換
├── generate_sample_tracking_22.py      ← [Step 1] サンプルデータ生成（合成データ用）
├── xt_pipeline_22.py                   ← [Step 2] データ処理・CSV出力
├── app_22.py                           ← [Step 3] Streamlit ダッシュボード
│
│  ─── スクリプトが生成するファイル ──────────────────────────────
├── skillcorner_1925299/                ← Step 0a が生成するフォルダ
│   ├── 1925299_match.json
│   ├── 1925299_phases_of_play.csv
│   ├── 1925299_dynamic_events.csv
│   └── 1925299_tracking_extrapolated.jsonl   (大容量・LFS)
├── Sample_TrackingData_22.csv          ← Step 0b or Step 1 が生成
├── Export_GSA_22players_30s.csv        ← Step 2 が生成（94列）
│
│  ─── 外部システムから受け取るファイル（将来）────────────────────
└── causal_scores_22.csv                ← GSAから届いたら置くだけ（任意）
```

---

## 実行順序

### （オプション）Step 0 ── SkillCorner 実データを使う場合

```bash
# SkillCorner データをダウンロード（初回のみ・大容量注意）
python fetch_skillcorner_1925299.py

# パイプライン形式に変換 → Sample_TrackingData_22.csv を上書き
python convert_skillcorner_to_pipeline.py
```

- 対象: Brisbane Roar 0-1 Perth Glory（2024-12-21, Match 1925299）
- 変換後は Step 2 から通常どおり実行できる（FPS=10 自動検出）
- 合成データで動作確認したい場合は Step 0 をスキップして Step 1 から始める

---

### Step 1 ── サンプルデータを生成する（合成データ）

```bash
python generate_sample_tracking_22.py
```

- **生成** → `Sample_TrackingData_22.csv`（1500行 × 49列）
- 実データがある場合はこのファイルを差し替えてよい（カラム形式は下記参照）

---

### Step 2 ── 22名にGridID・xTを付与してCSV出力

```bash
python xt_pipeline_22.py
```

- **必要** → `xT_BaseMap_105x68.csv` + `Sample_TrackingData_22.csv`
- **生成** → `Export_GSA_22players_30s.csv`（750行 × 94列）

---

### Step 3 ── ダッシュボード起動

```bash
streamlit run app_22.py
```

- **必要** → `xT_BaseMap_105x68.csv` + `Export_GSA_22players_30s.csv`
- **ブラウザ** → http://localhost:8501

---

## 実データを使う場合の入力CSVフォーマット

`Sample_TrackingData_22.csv` を実データに差し替える場合は以下の列名に合わせる。

| カラム名 | 型 | 説明 |
|---|---|---|
| `frame` | int | フレーム番号 |
| `time_sec` | float | 経過秒数 |
| `ball_x`, `ball_y` | float (0〜1) | ボール座標（正規化済み） |
| `is_goal_frame` | int (0/1) | ゴールフレームに 1 |
| `Home_1_x`, `Home_1_y` … `Home_11_x`, `Home_11_y` | float (0〜1) | Home 11名の座標 |
| `Away_1_x`, `Away_1_y` … `Away_11_x`, `Away_11_y` | float (0〜1) | Away 11名の座標 |

---

## 出力CSVフォーマット（94列）

`Export_GSA_22players_30s.csv` のカラム構成。

```
Frame, Time,
Ball_X, Ball_Y, Ball_GridID, Ball_xT,
Home_P1_X, Home_P1_Y, Home_P1_GridID, Home_P1_xT,
...
Home_P11_X, Home_P11_Y, Home_P11_GridID, Home_P11_xT,
Away_P1_X, Away_P1_Y, Away_P1_GridID, Away_P1_xT,
...
Away_P11_X, Away_P11_Y, Away_P11_GridID, Away_P11_xT
```

- `GridID` : 1〜7140（計算式: `X_idx + Y_idx × 105 + 1`）
- `xT` : 105×68ベースマップから参照した脅威度スコア

---

## GSA連携スコアを追加する場合（Step 4）

因果解析システムの出力CSVを以下の形式で `causal_scores_22.csv` として同フォルダに置くだけ。
ダッシュボードの「貢献度スコア」欄が自動で切り替わる。

| カラム | 説明 |
|---|---|
| `Frame` | フレーム番号（1〜750） |
| `Home_P1_contribution` … `Home_P11_contribution` | Home 11名のスコア |
| `Away_P1_contribution` … `Away_P11_contribution` | Away 11名のスコア |

---

## ファイル関係図

```
xT_BaseMap_105x68.csv ─────────────────┐
                                       ↓
Sample_TrackingData_22.csv ──→ xt_pipeline_22.py ──→ Export_GSA_22players_30s.csv
  （実データで差し替え可）                                        │
                                                               ↓
causal_scores_22.csv（任意） ────────────────────→ app_22.py（Streamlit）
```

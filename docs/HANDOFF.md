# 🚚 Pitch Log — 新PC 移行ガイド

このドキュメントは、Pitch Log プロジェクトを新しいPCに引き継ぐためのものです。

---

## 📦 1. 移行するもの一覧

### A. GitHub から自動取得できる（クローンするだけ）

```
✅ app_22.py                  v22 アプリ本体
✅ app_23.py                  v23 アプリ本体
✅ app_manual.py              取扱説明書アプリ
✅ xt_pipeline_22.py          v22 パイプライン
✅ xt_pipeline_23.py          v23 パイプライン
✅ convert_skillcorner_to_pipeline.py  SkillCorner変換スクリプト
✅ xT_BaseMap_105x68.csv      xT基本マップ
✅ Export_GSA_22players_30s.csv  シーンCSV（サンプル）
✅ match_info.json            試合情報
✅ requirements.txt           依存ライブラリ
✅ docs/                      ドキュメント一式
   ├ pitch-log-manual.html    取扱説明書
   ├ feature-catalog.html     カラムカタログ
   ├ feature_catalog.md       同 Markdown版
   ├ TODO_gsa_result_reader.md  GSA結果リーダーTODO
   └ HANDOFF.md               このファイル
```

### B. 別途バックアップが必要（gitに入っていない大きいデータ）

```
⚠️ skillcorner_1925299/   約 100MB
   ├ 1925299_dynamic_events.csv          (4.8MB) VAEP分析の元データ
   ├ 1925299_match.json                   (28KB)
   ├ 1925299_phases_of_play.csv           (134KB)
   └ 1925299_tracking_extrapolated.jsonl  (97MB) 生トラッキング
```

これらは `.gitignore` で意図的に除外されています（GitHubの100MB上限対策）。

---

## 🚀 2. 新PCでのセットアップ手順

### Step 1: Python環境準備

```powershell
# Python 3.10 以上を入れる（既にあれば不要）
python --version

# 仮想環境を作る（推奨）
cd C:\Users\<新ユーザー>\Desktop
python -m venv pitch-log-env
.\pitch-log-env\Scripts\Activate.ps1
```

### Step 2: リポジトリのクローン

```powershell
cd C:\Users\<新ユーザー>\Desktop
git clone https://github.com/itsapieceofcake4-max/pitch-log.git
cd pitch-log
```

### Step 3: 依存ライブラリインストール

```powershell
pip install -r requirements.txt
```

主要ライブラリ：
- streamlit
- pandas
- numpy
- plotly

### Step 4: 大きなデータの復元（必要なら）

旧PCから以下を**手動でコピー**：
```
旧PC: C:\Users\user\Desktop\claud\.claude\worktrees\lucid-bhaskara-09d96c\skillcorner_1925299\
            ↓
新PC: <repo-root>\skillcorner_1925299\
```

または再ダウンロード：
- SkillCorner Open Data: https://github.com/SkillCorner/opendata
- 試合ID 1925299 = Brisbane Roar vs Perth Glory (A-League 2024-25)

### Step 5: 動作確認

```powershell
streamlit run app_22.py
# → ブラウザで http://localhost:8501 を開いて動作確認
```

---

## 🤖 3. 新しい Claude Code への引き継ぎ

### A. プロジェクトを開く

新PCで Claude Code を起動し、以下のディレクトリで開く：
```
C:\Users\<新ユーザー>\Desktop\pitch-log
```

### B. 初回プロンプト（コピペ用）

新しい Claude Code に最初に貼り付けるテキスト：

```
このプロジェクトは「Pitch Log」というサッカー戦術分析プラットフォームです。
docs/HANDOFF.md と docs/pitch-log-manual.html を読んで、現状を把握してください。

主な構成：
- app_22.py: v22 ビジュアライザ（xT表示）
- app_23.py: v23 VAEP分析（オフボール・守備評価）
- app_manual.py: 取扱説明書アプリ
- xt_pipeline_22.py: 基本パイプライン
- xt_pipeline_23.py: GSA拡張・VAEP計算
- convert_skillcorner_to_pipeline.py: SkillCorner変換

デプロイ先：
- v22: https://pitch-log-22.streamlit.app/
- v23: https://pitch-log-23.streamlit.app/
- 取説: https://pitch-log-manual.streamlit.app/

GitHub: https://github.com/itsapieceofcake4-max/pitch-log

次にやりたいことは [ここに書く] です。
```

### C. 過去の経緯まとめ（参考用）

```
【これまでに完成しているもの】

1. v22 ビジュアライザ
   - 22選手 + ボールのアニメーション再生
   - xT ヒートマップ表示（Home/Away切替）
   - シーン取り込みウィザード（4ステップ）

2. v23 VAEP分析（v22の機能 + VAEP）
   - SkillCorner dynamic_events.csv から VAEP 計算
   - 攻撃 / 守備 / オフボール の3軸評価
   - Δ Ball_xT タイムライン
   - ゾーン別 xT 分析（自陣 / ミドル / アタッキングサード）

3. GSA拡張カラム（add_gsa_features）
   - Δ xT, dist_ball, speed, Ball_Zone 等 54カラム
   - 別途運用するGSAシステム用

4. ドキュメント
   - 取扱説明書（HTML + サイドバーで切替可能）
   - 追加可能カラム カタログ（500個の候補）

【今後のTODO（docs/TODO_gsa_result_reader.md 参照）】

- GSA結果（因果マッピング）リーダー
- 1次/2次/3次の因果階層を整理して表示
- 「どんなプレー、なぜ評価」を自動説明

【検証済みデータ】

- 試合: Brisbane Roar 0-1 Perth Glory
- シーン: ゴール前 30秒（300フレーム @ 10fps）
- フォーマット: SkillCorner Open Data
```

---

## 📝 4. よく使うコマンド集

### アプリ起動
```powershell
streamlit run app_22.py        # v22
streamlit run app_23.py        # v23
streamlit run app_manual.py    # 取説
```

### GSA拡張CSV生成
```powershell
python xt_pipeline_23.py --gsa_extend Export_GSA_22players_30s.csv
```

### VAEP貢献度計算
```powershell
python xt_pipeline_23.py --events skillcorner_1925299/1925299_dynamic_events.csv --match_info match_info.json
```

### SkillCorner変換
```powershell
python convert_skillcorner_to_pipeline.py
```

### Git操作
```powershell
git status                     # 変更確認
git add <file>                 # ステージング
git commit -m "メッセージ"     # コミット
git push origin main           # GitHubに反映 → Streamlit Cloud 自動再デプロイ
```

---

## 🔗 5. 重要URL集

### アプリ
| 用途 | URL |
|---|---|
| v22 | https://pitch-log-22.streamlit.app/ |
| v23 | https://pitch-log-23.streamlit.app/ |
| 取説 | https://pitch-log-manual.streamlit.app/ |

### 開発
| 用途 | URL |
|---|---|
| GitHub | https://github.com/itsapieceofcake4-max/pitch-log |
| Streamlit Cloud | https://share.streamlit.io/ |

### ドキュメント（直接HTML）
| 用途 | URL |
|---|---|
| 取説 | https://raw.githack.com/itsapieceofcake4-max/pitch-log/main/docs/pitch-log-manual.html |
| カタログ | https://raw.githack.com/itsapieceofcake4-max/pitch-log/main/docs/feature-catalog.html |

### データソース
| 用途 | URL |
|---|---|
| SkillCorner Open Data | https://github.com/SkillCorner/opendata |
| SkillCorner Portal | https://platform.skillcorner.com/ |
| StatsBomb Open Data | https://github.com/statsbomb/open-data |
| Metrica Sample Data | https://github.com/metrica-sports/sample-data |

---

## 🆘 6. トラブルシューティング

### Q. `streamlit` コマンドが見つからない
```powershell
# 仮想環境を有効化しているか確認
.\pitch-log-env\Scripts\Activate.ps1

# または直接実行
python -m streamlit run app_22.py
```

### Q. `xt_pipeline_22.py が見つからない` エラー
リポジトリのルートに以下が揃っているか確認：
```
ls *.py
# → app_22.py, app_23.py, app_manual.py
#   xt_pipeline_22.py, xt_pipeline_23.py
#   convert_skillcorner_to_pipeline.py
```

### Q. Streamlit Cloud のアプリにアクセスできない
- スリープから復帰待ち（1-2分）
- `share.streamlit.io` で Reboot app
- ブラウザの強制リロード（Ctrl+Shift+R）

### Q. シーンCSVを再生成したい
```powershell
# 1. xT_BaseMap_105x68.csv とトラッキングCSV があることを確認
# 2. 実行
python xt_pipeline_22.py
# → Export_GSA_22players_30s.csv が再生成される
```

### Q. 認証関連でGitHubにプッシュできない
新PCで Git の認証情報を再設定：
```powershell
git config --global user.email "its.a.piece.of.cake4@gmail.com"
git config --global user.name "itsapieceofcake4-max"

# プッシュ時に Personal Access Token を求められたら
# https://github.com/settings/tokens で発行
```

---

## ✅ 7. 引き継ぎチェックリスト

新PCで作業開始前に確認：

- [ ] Python 3.10+ インストール済み
- [ ] git インストール済み
- [ ] リポジトリをクローン済み
- [ ] `pip install -r requirements.txt` 完了
- [ ] `streamlit run app_22.py` で起動確認
- [ ] GitHub に push できることを確認（プッシュ権限）
- [ ] 旧PCの skillcorner_1925299/ をバックアップ（必要なら）
- [ ] Claude Code を新PCにインストール
- [ ] 上記「初回プロンプト」をClaude Codeに渡した

---

完了！ よい開発を 🚀

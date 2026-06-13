# Changelog — Pitch Log

変更履歴。新しいものを上に追記していく。日付は実装日（git log ベース）。
形式: `- 内容 (コミット短縮ハッシュ)`

> 運用ルール：機能を追加・変更したら、push 前にこのファイルへ1行追記する。

---

## 2026-06-10

- 顧客提案スライド `docs/Pitch_Log_Proposal.pptx`（全11枚）を追加。生成スクリプト `docs/make_proposal_pptx.py`。①レーダー→因果6軸→②因果ビュー→連鎖断絶→③シミュレータ→差別化→まとめ の構成。
- `docs/DATASETS.md` を追加。公開トラッキングデータ（映像有無・入手方法）比較表＋ feature_catalog.pptx の10カテゴリ指標が各データで作れるかの対応表。
- モメンタム指標に「xT位置（絶対脅威）」モードを追加。ゴール前の膠着でΔxTが低くなる問題を解消。UIラジオで切替可能。

---

## 2026-06-06

- **TOPハブ `app_top.py` 新規**：v22/v23/v24/取説 への入口を1枚に集約。アプリ比較(VERSIONS)と変更履歴(CHANGELOG)をタブで同居表示。
- アプリ特徴整理 `docs/VERSIONS.md` と変更履歴 `CHANGELOG.md` を追加。push前にCHANGELOG追記する運用ルールを明文化。 (46b2ddb)
- app_22 / app_23 の同一画面下部に「試合全体モメンタム」を埋め込み。共通ロジックを `match_momentum.py` に集約（重複排除）。app_24 はモジュールを使う薄いラッパーに整理。 (73292f7)
- **app_24（v24）新規**：試合全体モメンタムビュー。インタラクティブ Plotly チャート（xT added）、net/正のみ切替、ローリング窓スライダー、ピンチ/チャンス/ゴール自動抽出、ボックス選択で区間抽出＋CSVダウンロード、ズーム解除。`build_match_phases.py` で `match_phases_summary.csv` を生成（cloud用に同梱）。 (e84d023)

## 2026-06-05

- Zone_ID を選手/ボールのホバーと app_22 フレーム表に表示（app_22 / app_23）。 (68eeae8)
- **Zone_ID 座標マッピング追加**：絶対座標 = 深度バンド×100＋幅行（21深度×14幅）。各 subject に `_ZoneID` 列を Export CSV へ。 (e583f69)

## 2026-06-04

- xT ヒートマップの色をチーム規約に統一（Home=青／Away=赤、選手ドット・タイムラインと一致）。 (4f239fa)
- xT ヒートマップの初期表示を「両方（Home＋Away）」に変更。 (49a407b)
- データ生成スクリプト3本を追加し完全再現性を確保（fetch_skillcorner / generate_sample_tracking_22 / create_xt_basemap）。 (5a2a271)
- 生成系CSVを .gitignore に追加。 (5cdec30)
- 不足パイプラインファイルと新PC移行ガイドを追加（xt_pipeline_22 / convert_skillcorner / HANDOFF）。 (7cd6878)

## 2026-05-25 〜 30

- 追加可能カラム カタログ（HTML＋Markdown、500候補）と複数ドキュメントビューアを追加。 (432fcd9, f99b599, 97b9504)
- Δ xT タイムライン＋ゾーン別分析を追加。 (d4786a8)
- GSA結果リーダーの将来仕様メモ（TODO）を追加。 (4142a28)

## 2026-05-23

- 取説アプリ `app_manual.py`（HTML配信ラッパー）と取説HTMLを追加。Dev Container 設定。 (a293edb, 354c6e3, 30bce19, a5f96f2)
- GSA拡張カラム（Delta_xT / dist_ball / speed）を追加。 (ade96e3)
- **app_23（v23）新規**：VAEP＋オフボール＋守備の選手貢献分析。 (87af30a)

## 2026-05-21 〜 22

- 4ステップ シーン取り込みウィザード（フルCSV→切出→変換）とWeb UIデータ取込。 (ae73009, 331204b, 3afe32e)
- ボール半透明・Away xTヒートマップ・選手表示トグル・再生ボタン修正。 (a7a7a68)
- シーン時間窓表示と再切り出し機能。 (af8b72e)
- ゾーン評価モード（ラインブレイクパス検知）。 (1f76ac6)
- ログインを Streamlit 標準 Google 認証に変更。 (f2e67e9, ce75e5f)
- **初版**：Pitch Log 22人 xT ダッシュボード（app_22）。 (c1686cf)

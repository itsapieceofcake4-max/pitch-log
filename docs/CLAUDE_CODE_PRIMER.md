# 🤖 Claude Code 初回プロンプト（コピペ用）

新しい PC の Claude Code に最初に貼り付けてください。

---

## 📋 そのままコピペするテキスト

```
このプロジェクトは「Pitch Log」というサッカー戦術分析プラットフォームです。

【プロジェクトの目的】
SkillCorner トラッキングデータを使い、特定シーン（30秒程度）の
xT・VAEP・選手貢献度を可視化するStreamlitアプリ。
別途運用するGSA（因果関係解析）システムへの説明変数CSVも生成する。

【現状】
- v22（基本ビジュアライザ）と v23（VAEP分析追加版）が完成済み
- Streamlit Cloud に3つのアプリをデプロイ中
- 検証データ: Brisbane Roar 0-1 Perth Glory（A-League）の30秒シーン

【公開URL】
- v22: https://pitch-log-22.streamlit.app/
- v23: https://pitch-log-23.streamlit.app/
- 取説: https://pitch-log-manual.streamlit.app/
- GitHub: https://github.com/itsapieceofcake4-max/pitch-log

【主要ファイル構成】
- app_22.py: v22 ビジュアライザ
- app_23.py: v23 VAEP分析 + Δ xT + ゾーン分析
- app_manual.py: 取扱説明書アプリ
- xt_pipeline_22.py: 基本パイプライン（xT付与・シーン切出）
- xt_pipeline_23.py: GSA拡張・VAEP計算
- convert_skillcorner_to_pipeline.py: SkillCorner → 内部形式変換
- xT_BaseMap_105x68.csv: xT基本マップ
- Export_GSA_22players_30s.csv: シーンCSV（103カラム、+GSA拡張で157）
- match_info.json: 試合情報

【ドキュメント】
- docs/pitch-log-manual.html: 取扱説明書（HTML）
- docs/feature-catalog.html: 追加可能カラム カタログ（500個の候補）
- docs/HANDOFF.md: 新PC移行ガイド
- docs/TODO_gsa_result_reader.md: 次の機能TODO

まずは docs/HANDOFF.md を読んで全体像を把握してください。
そのあと、今日やりたいタスクを指示します。
```

---

## 💡 状況別の追加プロンプト

### 状況A: 既存機能の改善・修正をしたい

```
状況：[何が起きているか]
やりたいこと：[何をしたいか]
影響範囲：[どのアプリ/ファイル]

該当ファイルを読んで修正案を提案してください。
```

### 状況B: 新機能を追加したい

```
新機能：[機能の概要]
背景：[なぜ必要か]
入力：[何のデータを使う]
出力：[どう表示する/どこに保存する]

実装案を docs/TODO_gsa_result_reader.md の形式でまず整理してください。
```

### 状況C: 別の試合データに適用したい

```
新試合：[試合名・データソース]
ファイル形式：[CSV / JSON / 他]
特殊な事情：[Home/Away判定、選手番号の振り分け等]

docs/feature-catalog.html の「他試合への適用ガイド」を参考に、
convert_xxx_to_pipeline.py を作成してください。
```

### 状況D: GSA結果リーダーを実装したい

```
GSA出力ファイル: [パスや形式]
やりたいこと: docs/TODO_gsa_result_reader.md に書いた仕様で実装

まずTODOを読んで、現在のGSA出力形式と照合しながら実装案を提案してください。
```

### 状況E: ラグビー・他競技に拡張したい

```
対象スポーツ: [ラグビー/競馬/他]
利用可能なデータ: [プロバイダ・形式]

既存のサッカー版のコードを最大限流用しつつ、
競技固有の差分（人数、ピッチサイズ、評価指標）を整理してください。
```

---

## 🎯 直近の優先タスク候補

過去の会話で挙がっていた次の作業候補：

| 優先度 | タスク | 詳細 |
|---|---|---|
| 高 | GSA結果リーダー実装 | docs/TODO_gsa_result_reader.md |
| 高 | GSA推奨カラムを Phase 1 まで追加 | feature-catalog.html Phase 1（+110カラム） |
| 中 | Δ Ball_xT を目的変数として明示的にサポート | 目的変数選択UIを追加 |
| 中 | 他試合データでの動作確認 | 別 SkillCorner Open Data の試合で検証 |
| 低 | ラグビー版の構想 | docs/feature-catalog.html の他競技セクション参照 |

---

## 📞 困ったとき

- このリポジトリの `docs/` 配下を読む
- GitHub のコミット履歴で過去の変更を確認
- Streamlit Cloud のログでデプロイエラーを確認

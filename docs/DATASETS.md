# 公開サッカートラッキングデータ 比較表

> 調査日: 2026-06-10。Pitch Log で使える「映像とセットで使える」公開トラッキングデータの整理。
> 結論: **映像が実際に手に入る公開データは実質 SoccerNet 一択**。
> **J リーグの生トラッキング＋映像のオープンデータは存在しない**（走行距離等の集計指標のみ公式サイトで閲覧可）。

## 比較表

| データセット | 中身 | 試合数 | 周波数 | リーグ／出所 | 🎥 映像 | 入手方法・ライセンス |
|---|---|---|---|---|---|---|
| **SoccerNet** | 放送映像＋トラッキング＋アクション＋GSR（ミニマップ座標） | 映像500試合/764h、うちトラッキング12試合フル＋200×30秒クリップ | 25 Hz | 欧州主要リーグ放送 | **◎ 実映像を配布**（NDA同意要） | 無料・NDAフォーム＋`pip install SoccerNet` |
| **PFF FC 2022 W杯** | 放送トラッキング＋イベント＋プレーグレード | **64試合（全試合）** | 29.97 Hz | 2022 FIFA W杯 | ✕ 映像は非同梱（放送由来） | 無料（研究用）・申請制 |
| **Metrica Sports Sample** | トラッキング＋同期イベント | 3試合（匿名） | 25 Hz | 非公開（匿名化） | ✕ 座標のみ | 無料・GitHub |
| **SkillCorner Open Data** | 放送トラッキング（一部イベント） | 9試合（旧）＋10試合（豪Aリーグ24/25） | 10 Hz | 欧州主要＋豪Aリーグ | ✕ 映像は非配布 | 無料・GitHub |
| **StatsBomb Open Data** | イベント＋360フリーズフレーム（連続トラッキングではない） | 360は約200試合超 | イベント単位 | W杯・女子・メッシ全試合等 | ✕ | 無料・GitHub |
| **DFL/IDSSE**（Nature 2025） | 光学トラッキング＋イベント | 7試合（独プロ） | 25 Hz | ブンデス級 | ✕ | 無料・論文付随 |
| **J リーグ** | 走行距離・スプリント等の集計指標（生トラッキングはクラブ限定） | J1全試合（2015〜） | — | J1／Data Stadium | ✕ | 集計のみ J.LEAGUE.jp・Football LAB で閲覧。**生データ＋映像のオープン版なし** |

## ポイント

- **映像とセットで使いたいなら SoccerNet**。放送映像クリップ＋トラッキング＋ピッチキャリブレーションが揃う唯一の選択肢。NDA同意は要るが無料、`pip` で取得可。今の Pitch Log（放送由来 xT）と相性が良い。
- **フル試合のトラッキング＋イベントを量で使うなら PFF FC の 2022 W杯**（64試合・29.97Hz）が最強。ただし映像は付かない。`app_24` モメンタムをそのまま大規模化できる。
- **J リーグは映像付きオープンデータが無い**。走行距離等の集計は閲覧可だが、生 x,y は Data Stadium 経由でクラブ／メディア限定（有償・契約）。研究用の無料配布はない。J リーグ＋映像でやるなら SkillCorner/PFF 方式（放送映像から自前で抽出）が現実的な代替。

## feature_catalog.pptx の指標は各データで作れるか

カタログの指標は**生データから計算する派生特徴量**であり、どのサイトにも「そのままの形」では入っていない。
論点は「指標が入っているか」ではなく**「計算に必要な素材が揃うか」**。素材は2つ：

- **A. 全22選手＋ボールの連続トラッキング**（高頻度・欠損なし）→ 速度/加速度/距離/形状/ラグ系
- **B. イベントデータ**（パス・シュート・ポゼッション・VAEP）→ パス前進系/events連動系

### カタログ10カテゴリ × 公開データ 対応表

◎=ほぼ全部算出可 / △=一部・精度落ち / ✕=不可

| カテゴリ | 必要素材 | PFF 2022W杯 | Metrica/DFL | SoccerNet | SkillCorner | StatsBomb |
|---|---|:--:|:--:|:--:|:--:|:--:|
| ① 動き・速度系 | A 高頻度連続 | ◎ | ◎ | △ | △ | ✕ |
| ② 距離・位置関係 | A 全22名 | ◎ | ◎ | △ | △ | △ |
| ③ チーム形状 | A 全22名 | ◎ | ◎ | △ | △ | △ |
| ④ ゾーン拡張 | ボール位置 | ◎ | ◎ | ◎ | ◎ | ◎ |
| ⑤ 所有・フェーズ | B 所有 | ◎ | ◎ | △ | △ | ◎ |
| ⑥ パス・前進系 | B パスevent | ◎ | ◎ | ✕ | △ | ◎ |
| ⑦ 個人xT変化 | A 全22名 | ◎ | ◎ | △ | △ | △ |
| ⑧ 時間ラグ | A 高頻度連続 | ◎ | ◎ | △ | △ | ✕ |
| ⑨ events連動(VAEP等) | B 詳細event | ◎※ | ◎※ | ✕ | ✕ | ◎ |
| ⑩ 目的変数 | ボール+ゴール | ◎ | ◎ | △ | △ | △ |

※VAEP は付属せず、イベントから自前で算出する前提。

### 結論：一部か全部か

- **「ほぼ全部」算出可 ＝ PFF FC 2022 W杯 / Metrica / DFL**。フル22名トラッキング（PFF=放送30Hz、Metrica/DFL=光学25Hz）＋イベントが揃い、①〜⑩がほぼ全部出せる。**PFF が最有力**（64試合と量もある）。
- **「一部だけ」＝ SoccerNet / SkillCorner**。トラッキングはあるが放送由来で欠損・低頻度（off-camera選手が落ちる、SkillCornerは10Hz）。①③⑦⑧は精度が落ち、⑥⑨（パス/VAEP系イベント）はほぼ不可。④ゾーンのみ確実。
- **「イベント側だけ」＝ StatsBomb**。⑤⑥⑨は◎だが、360はイベント瞬間のフリーズフレームのみ＝連続フレームが無く、①速度・⑧ラグは原理的に不可。
- **「ほぼゼロ」＝ J リーグ**。生データ非公開のため、フレーム単位の指標はどれも作れない。

→ カタログを丸ごと再現したいなら **PFF（量）か Metrica/DFL（質）**。映像も欲しいなら SoccerNet だが指標は一部に絞られるトレードオフ。

## Pitch Log への取り込み

- 既存パイプライン: `convert_skillcorner_to_pipeline.py`（SkillCorner 形式 → pipeline 入力）。
- SoccerNet / PFF を使う場合は、各フォーマット → `Sample_TrackingData_22.csv` 互換（frame, ball_x/y, {team}_{n}_x/y, 0〜1正規化）への変換アダプタを足す。

## 出典

- [SoccerNet – Data](https://www.soccer-net.org/data) / [sn-tracking](https://github.com/SoccerNet/sn-tracking) / [SoccerNet-GSR (arXiv)](https://arxiv.org/abs/2404.11335)
- [PFF FC 2022 World Cup Dataset](https://www.blog.fc.pff.com/blog/pff-fc-release-2022-world-cup-data)
- [SkillCorner Open Data](https://github.com/SkillCorner/opendata)
- [KU Leuven ECML 2024 – Soccer datasets](https://dtai.cs.kuleuven.be/tutorials/sports/ecml2024/notes/datasets/soccer/)
- [An integrated dataset of spatiotemporal and event data in elite soccer (Nature Sci Data 2025)](https://www.nature.com/articles/s41597-025-04505-y)
- [トラッキングデータの活用（J.LEAGUE.jp / Data Stadium）](https://www.jleague.jp/column/article/656/)
- [J リーグトラッキングデータコンテスト（Wikipedia）](https://ja.wikipedia.org/wiki/Jリーグトラッキングデータコンテスト)

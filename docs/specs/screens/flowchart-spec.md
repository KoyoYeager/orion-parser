# フローチャート仕様書

## 概要

関数ごとにJIS準拠のフローチャートを生成する。
コールツリー + フローチャート + クラス図の3つで**元のコードを完全に復元**できることを目標とする。

## JIS図形仕様

| 図形 | 形状 | QGraphicsView | Graphviz DOT | 用途 |
|------|------|---------------|-------------|------|
| 端子 (開始) | 角丸四角 | `rounded` | `shape=box, style="rounded,filled"` | 関数の開始。ラベルは「開始: 関数名(引数)」 |
| 端子 (終了) | 角丸四角 | `rounded` | 同上 | 関数の終了。ラベルは「終了」 |
| 処理 | 四角 | `rect` | `shape=box` | 代入、式、関数呼び出し |
| 判断 | ひし形 | `diamond` | `shape=diamond` | if, while の条件式 |
| ループ開始 | 台形 (下広) | `trap_bottom` | `shape=invtrapezium` | for/while ループの始まり |
| ループ終了 | 台形 (上広) | `trap_top` | `shape=trapezium` | for/while ループの終わり |
| 入出力 | 平行四辺形 | `parallelogram` | `shape=parallelogram` | print, input |
| 復帰 | 角丸四角 | `rounded` | `shape=box, style="rounded,filled"` | return文 |

## ラベル仕様

| ノード種別 | ラベル形式 | 例 |
|-----------|----------|-----|
| 開始 | `開始: 関数シグネチャ` | `開始: process_data(items, threshold=0)` |
| 終了 | `終了` | `終了` |
| 処理 | そのまま | `result = value * multiplier` |
| 判断 | 条件式 | `item > threshold` |
| ループ開始 | `for 変数 in イテラブル` | `for item in items` |
| ループ終了 | (開始と同じ) | `for item in items` |
| 入出力 | `print(引数)` / `input(引数)` | `print(report)` |
| 復帰 | `return 値` | `return result` |

### ラベルの詳細ルール
- **省略しない** — ノード幅をラベル長に合わせて自動拡張
- **行番号は含めない** — フローチャートは処理理解が目的
- **docstringはノードにしない** — startノードのツールチップに表示
- **keyword引数を正しく表示** — `func(data, threshold=10)` 形式
- **AugAssign** — `errors += 1` と表示 (`augassign` ではない)
- **dict literal** — 内容を展開 `{"name": s.name, "kind": s.kind, ...}`

## レイアウト仕様

### GUIキャンバス (QGraphicsView)
- **全ノード1列配置** — 上から下に順に配置
- **ノード幅は自動** — `max(140px, ラベル文字数 × 8 + 30)`
- **行高さ** — 65px
- **中央揃え** — 全ノードがx=300に中央配置

### エッジ (接続線)
- **YES (True)** — 判断の下に直線で接続。「YES」ラベルは左下に表示
- **NO (False)** — 判断の右から水平に出て、下のノードに接続。「NO」ラベルは右上に表示
- **通常フロー** — 上のノードの下端 → 下のノードの上端に直線
- **合流** — 分岐後の合流は、右から左に水平線で戻る
- **矢印** — 全エッジに三角矢印 (先端に)

### 色分け
| ノード種別 | 色 |
|-----------|-----|
| 開始 | `#A9DFBF` (緑) |
| 終了 | `#F5B7B1` (赤) |
| 処理 | `#85C1E9` (青) |
| 判断 | `#F9E79F` (黄) |
| ループ | `#D7BDE2` (紫) |
| 入出力 | `#F5CBA7` (橙) |
| 復帰 | `#F5B7B1` (赤) |

## エクスポート仕様

### PNG/JPEG等 (画像形式)
- **GUIのQGraphicsScene描画をそのまま保存** (Graphviz経由ではない)
- ファイル名デフォルト: `flowchart_関数名.png`

### DOT/SVG等 (Graphviz形式)
- `digraph Flowchart { rankdir=TB; ... }`
- ノード型に応じた `shape` 属性
- True/False のエッジラベル付き
- 開始/終了は `shape=box, style="rounded,filled"`

### Excel/HTML/JSON等
- 既存のエクスポータを共有

## 制御フロー抽出仕様

### 対象
- トップレベル関数
- クラス内メソッド (`ClassName.method_name` 形式)

### 対象外
- docstring (ノードにしない、ツールチップに表示)
- ネストされた関数/クラス定義
- デコレータ

### 分岐の扱い
- **if-else** — `decision` ノード + True/False エッジ
- **elif** — ネストされた `decision` として展開
- **for** — `loop_start` + body + `loop_end`
- **while** — `loop_start` + body + `loop_end`
- **try-except** — `process("try")` + `process("except ...")` + 合流
- **with** — `process("with ...")` + body

## ツールチップ
- **startノード** — 関数シグネチャ + docstring
- **全ノード** — ラベルの全文 (省略なし)

## 既知の問題
- NO分岐線がひし形ノードに重なる場合がある → エッジオフセットの調整が必要
- startノードに「開始:」プレフィクスがない → 追加が必要
- endノードに「終了」がない → 「END」を「終了」に変更すべき

# OrionParser GUI アプリケーション仕様書

## 1. 概要

PySide6 ベースのデスクトップ GUI アプリケーション。
ソースコードの**コード解析**と**グラフ解析**を2本柱として提供する。

### 2本柱

| 柱 | 目的 | 含む機能 |
|----|------|---------|
| **コード解析** | コードの中身を人間が読み解く | シンボル一覧、トークン列、AST ツリー |
| **グラフ解析** | コードの関係性を視覚的に把握する | コールツリー、データフロー、(将来) DFD・フローチャート・依存関係・メトリクス等 |

### 設計思想

- **ソースコードは常に見える** — 解析結果と元コードを並べて対応関係を掴む
- **2モードで迷わない** — やりたいことは「コードを読む」か「関係を見る」のどちらか
- **グラフ解析側に拡張スペース** — 将来の機能追加は主にグラフ解析に集約される

### 技術スタック

| 項目 | 技術 |
|------|------|
| GUI フレームワーク | PySide6 (Qt 6) |
| グラフ描画 | QGraphicsView + NetworkX レイアウト |
| シンタックスハイライト | QSyntaxHighlighter |
| アイコン | Qt 標準 + Material Design Icons |
| パッケージ | `orionparser[gui]` optional dependency |

---

## 2. 全体レイアウト

```
┌──────────────────────────────────────────────────────────────────┐
│  メニューバー  [ファイル] [表示] [ヘルプ]                            │
├──────────────────────────────────────────────────────────────────┤
│  ツールバー  [📂開く] [📁フォルダ] [🔄再解析] | 言語: Python 3      │
├───────┬──────────────────────────────────────────────────────────┤
│       │ ┌──────────────┬──────────────┐                          │
│ ファイル│ │ 📝 コード解析  │ 🔗 グラフ解析  │  ← 2大モード切替         │
│ ツリー │ └──────────────┴──────────────┘                          │
│       │                                                          │
│ 📂 src│    選択中モードのコンテンツ                                  │
│  📄a.py│                                                          │
│  📄b.py│    (以下、モード別に異なるレイアウト)                        │
│ 📂test│                                                          │
│  📄t.py│                                                          │
│       │                                                          │
├───────┴──────────────────────────────────────────────────────────┤
│  ステータスバー                                                    │
└──────────────────────────────────────────────────────────────────┘
```

### サイズ・比率

| 要素 | 初期サイズ | リサイズ |
|------|-----------|---------|
| ウィンドウ全体 | 1280 x 800 | 自由リサイズ、最小 800x600 |
| ファイルツリー | 幅 220px | QSplitter で可変、非表示可 |
| メインエリア | 残り全部 | モード内で QSplitter 可変 |

---

## 3. コード解析モード

**目的:** ソースコードの中身を多角的に読み解く

ソースビューアを常に左に表示し、右側のサブタブで解析結果を切り替える。
解析結果の項目をクリックすると、ソースの該当行にジャンプする。

```
┌──────────────────────────────────────────────────────────────┐
│ [📝 コード解析] [🔗 グラフ解析]                                  │
├──────────────────────────┬───────────────────────────────────┤
│                          │ ┌─────────┬────────┬─────┐        │
│  ソースビューア            │ │シンボル一覧│ トークン │ AST │        │
│  (常時表示)               │ └─────────┴────────┴─────┘        │
│                          │                                   │
│  1│ import sys           │  ▼ 関数 (12)                      │
│  2│ import os            │  ┌──────────┬────────┬────┬─────┐ │
│  3│                      │  │ 名前      │スコープ │ 行 │ doc │ │
│  4│ def main(): ←ハイライト│  ├──────────┼────────┼────┼─────┤ │
│  5│     x = 1            │  │→main     │<module>│  4 │ ... │ │
│  6│     print(x)         │  │ parse    │<module>│ 32 │ ... │ │
│  7│                      │  └──────────┴────────┴────┴─────┘ │
│  8│ class Config:        │                                   │
│  9│     """Config."""     │  ▼ クラス (3)                      │
│ 10│     name = "app"     │  ┌──────────┬────────┬────┬─────┐ │
│ 11│     ...              │  │ Config   │<module>│  8 │ ... │ │
│   │                      │  └──────────┴────────┴────┴─────┘ │
│   │                      │                                   │
│   │                      │  ▶ 変数 (8)   ▶ インポート (5)     │
│   │                      │                                   │
├──────────────────────────┴───────────────────────────────────┤
│ main.py | 関数: 12  クラス: 3  変数: 8  import: 5 | 0.15s    │
└──────────────────────────────────────────────────────────────┘
```

### 中核: ソース ↔ 解析の双方向連動

| 操作 | 動作 |
|------|------|
| シンボル行をクリック | ソースビューアが該当行にスクロール＆ハイライト |
| トークン行をクリック | ソースビューアが該当行にスクロール＆ハイライト |
| AST ノードをクリック | ソースビューアが該当行にスクロール＆ハイライト |
| ソースビューアの行をクリック | 右パネルで対応するシンボル/トークン/ノードを選択 |

### サブタブの比率

- ソースビューア 45% : サブタブ 55% (QSplitter で可変)

---

## 4. グラフ解析モード

**目的:** コードの関係性を視覚的なグラフで把握する

グラフキャンバスを広く取り、左サイドにグラフ種別セレクタ、下部に詳細パネルを配置。
将来の解析種別（DFD、フローチャート、依存関係等）はセレクタに追加するだけで拡張できる。

```
┌──────────────────────────────────────────────────────────────┐
│ [📝 コード解析] [🔗 グラフ解析]                                  │
├──────────┬───────────────────────────────────────────────────┤
│          │  [レイアウト: 階層 ▼] [ズーム: − 100% +] [フィット]   │
│ グラフ    │  [📷PNG] [📋DOT]                                   │
│ 種別     ├───────────────────────────────────────────────────┤
│          │                                                   │
│ ┌──────┐ │           ┌──────────┐                            │
│ │▶コール ││           │ <module> │                            │
│ │ ツリー ││           └─────┬────┘                            │
│ ├──────┤ │         ┌───────┼───────┐                         │
│ │ データ ││    ┌────┴───┐ ┌┴─────┐ ┌┴────────┐               │
│ │ フロー ││    │  main  │ │Config│ │setup_log│               │
│ ├──────┤ │    └────┬───┘ └──────┘ └─────────┘               │
│ │ ─── ─ ││    ┌────┴──────┐                                  │
│ │(将来)  ││ ┌──┴──────┐┌──┴────────┐        ┌──────┐        │
│ │ DFD   ││ │parse_file││validate   │        │ミニ   │        │
│ │フロー  ││ └─────────┘└───────────┘        │マップ │        │
│ │チャート ││                                  └──────┘        │
│ │依存関係││                                                   │
│ │メトリクス│                                                   │
│ │セキュリティ│                                                  │
│ └──────┘ │                                                   │
│          ├───────────────────────────────────────────────────┤
│          │ [C] 詳細パネル                                     │
│          │ 選択: main → calls: parse_file, validate          │
│          │ called by: <module> | 行: 4                       │
├──────────┴───────────────────────────────────────────────────┤
│ ノード: 7 | エッジ: 6 | レイアウト: 階層 | 0.08s               │
└──────────────────────────────────────────────────────────────┘
```

### グラフ種別セレクタ (左サイド)

縦に並んだボタンリスト。選択中の種別はハイライト。
将来の機能はこのリストに追加するだけ。

| 種別 | 状態 | データソース |
|------|------|------------|
| コールツリー | **実装済み** | `extract_call_tree()` |
| データフロー | **実装済み** | `extract_data_flow()` |
| DFD | 将来 | `DFDGenerator` |
| フローチャート | 将来 | `FlowchartGenerator` |
| 依存関係 | 将来 | `DependencyGraphBuilder` |
| メトリクス | 将来 | `MetricsCalculator` |
| セキュリティ | 将来 | `SecurityAnalyzer` |

### グラフキャンバスの比率

- グラフ種別セレクタ 80px (固定) : グラフキャンバス 残り全て
- グラフキャンバス 75% : 詳細パネル 25% (QSplitter で可変)

---

## 5. アーキテクチャ

### 5.1 レイヤー構成

```
┌───────────────────────────────────────────────┐
│  GUI Layer (PySide6 Widgets)                  │
│  ├─ MainWindow (モード切替)                    │
│  ├─ CodeAnalysisView (ソース + サブタブ)        │
│  ├─ GraphAnalysisView (キャンバス + セレクタ)   │
│  └─ 共通 Widgets                              │
├───────────────────────────────────────────────┤
│  ViewModel Layer                              │
│  ├─ AnalysisViewModel (状態管理 + Signal)      │
│  └─ AnalysisWorker (バックグラウンド解析)       │
├───────────────────────────────────────────────┤
│  Service Layer (API ラッパー)                  │
│  ├─ ParserService   → BasePipeline            │
│  ├─ SymbolService   → extract_symbols()       │
│  ├─ CallTreeService → extract_call_tree()     │
│  └─ DataFlowService → extract_data_flow()     │
├───────────────────────────────────────────────┤
│  OrionParser Core (既存)                      │
│  ├─ registry, pipeline, lexer, parser         │
│  └─ analysis (symbols, call_tree, data_flow)  │
└───────────────────────────────────────────────┘
```

### 5.2 ディレクトリ構成

```
src/orionparser/
├── gui/
│   ├── __init__.py
│   ├── app.py                 # QApplication 起動
│   ├── main_window.py         # MainWindow (モード切替 + ファイルツリー)
│   ├── viewmodel.py           # AnalysisViewModel + AnalysisWorker
│   ├── services.py            # Service Layer
│   ├── views/                 # 2大モードのビュー
│   │   ├── __init__.py
│   │   ├── code_analysis.py   # コード解析モード全体
│   │   └── graph_analysis.py  # グラフ解析モード全体
│   ├── panels/                # サブパネル群
│   │   ├── __init__.py
│   │   ├── base_panel.py      # BasePanel (共通インターフェース)
│   │   ├── symbols_panel.py   # シンボル一覧サブタブ
│   │   ├── tokens_panel.py    # トークンサブタブ
│   │   ├── ast_panel.py       # AST サブタブ
│   │   └── graph_panels/      # グラフ種別ごとのパネル
│   │       ├── __init__.py
│   │       ├── base_graph.py  # BaseGraphPanel (共通インターフェース)
│   │       ├── call_tree.py   # コールツリー
│   │       └── data_flow.py   # データフロー
│   ├── widgets/               # 再利用ウィジェット
│   │   ├── __init__.py
│   │   ├── file_tree.py       # ファイルツリー
│   │   ├── source_viewer.py   # ソースコードビューア
│   │   ├── search_bar.py      # フィルタ/検索バー
│   │   └── graph_canvas.py    # QGraphicsView グラフ描画
│   └── resources/
│       ├── icons/
│       └── style.qss
├── core/                      # (既存)
├── languages/                 # (既存)
└── analysis/                  # (既存)
```

### 5.3 拡張メカニズム

#### コード解析サブタブの追加

```python
class BasePanel(QWidget):
    """コード解析サブタブの共通インターフェース"""
    panel_id: str
    panel_name: str

    def on_file_loaded(self, result: ParseResult, source: str, path: str) -> None: ...
    def on_line_selected(self, line: int) -> None: ...
    def clear(self) -> None: ...

    # サブタブがソース行をクリックしたときに発火
    source_line_requested = Signal(int)
```

#### グラフ解析パネルの追加

```python
class BaseGraphPanel(QWidget):
    """グラフ解析パネルの共通インターフェース"""
    graph_id: str
    graph_name: str
    graph_icon: str

    def build_graph(self, result: ParseResult) -> nx.DiGraph | None: ...
    def get_node_label(self, node_id: str) -> str: ...
    def get_node_tooltip(self, node_id: str) -> str: ...
    def get_detail_text(self, node_id: str) -> str: ...

# 新しいグラフ種別を追加する手順:
# 1. BaseGraphPanel を継承した新クラスを graph_panels/ に作成
# 2. app.py で register_graph_panel() で登録
```

---

## 6. 共通コンポーネント

### 6.1 ファイルツリー (`widgets/file_tree.py`)

- `QTreeView` + `QFileSystemModel` ベース
- 対応拡張子のみ表示 (`.py` 等)
- ファイルクリック → ViewModel.load_file() → 両モードに結果配信
- フォルダ選択時はディレクトリ全体を再帰解析

| 状態 | 表示 |
|------|------|
| 起動直後 | プレースホルダ「ファイルまたはフォルダを開いてください」 |
| 単一ファイル | ファイルツリー非表示。ファイル名ラベルのみ |
| フォルダ選択 | ツリー表示。解析状態マーク付き (成功=緑, 失敗=赤) |

### 6.2 ソースビューア (`widgets/source_viewer.py`)

コード解析モードの左半分を占める。全サブタブと連動する中核ウィジェット。

- `QPlainTextEdit` (読み取り専用) + 行番号
- `QSyntaxHighlighter` でキーワード・文字列・コメントを色分け
- 外部から行ハイライト/スクロールを制御可能

| 機能 | 説明 |
|------|------|
| `highlight_line(n)` | 指定行を黄色背景でハイライト + スクロール |
| `highlight_range(start, end)` | 範囲ハイライト |
| `clear_highlight()` | ハイライト解除 |
| 行クリック | `line_clicked` Signal を発火 → サブタブが対応項目を選択 |

### 6.3 グラフキャンバス (`widgets/graph_canvas.py`)

グラフ解析モードのメイン描画エリア。全グラフ種別で共有。

- `QGraphicsView` + `QGraphicsScene`
- NetworkX の `pos` dict を受け取りノードとエッジを描画
- ズーム (ホイール)、パン (中ドラッグ)、ノード選択、ノードドラッグ

| 機能 | 説明 |
|------|------|
| `set_graph(graph, pos)` | グラフデータをセットして描画 |
| `set_layout(layout_name)` | レイアウトアルゴリズムを変更して再描画 |
| `fit_to_view()` | グラフ全体がビューに収まるようズーム |
| `export_png(path)` | 現在の描画を PNG で保存 |
| `to_dot()` | Graphviz DOT 形式テキストを生成 |
| ノードクリック | `node_selected` Signal → 詳細パネル更新 |
| ノードホバー | 接続ノード + エッジをハイライト |

### 6.4 検索バー (`widgets/search_bar.py`)

- `QLineEdit` + フィルタ用ドロップダウン
- 入力 300ms 後にデバウンスしてフィルタ発火
- `Ctrl+F` でフォーカス

---

## 7. メニュー・ツールバー

### 7.1 メニューバー

| メニュー | 項目 | ショートカット | 動作 |
|---------|------|--------------|------|
| ファイル | ファイルを開く | `Ctrl+O` | 単一ファイル選択ダイアログ |
| | フォルダを開く | `Ctrl+Shift+O` | フォルダ選択ダイアログ |
| | 最近開いたファイル | — | 直近 10 件のサブメニュー |
| | 再解析 | `F5` | 現在の対象を再解析 |
| | 終了 | `Ctrl+Q` | アプリケーション終了 |
| 表示 | コード解析モード | `Ctrl+1` | コード解析モードに切替 |
| | グラフ解析モード | `Ctrl+2` | グラフ解析モードに切替 |
| | サイドバー | `Ctrl+B` | ファイルツリーの表示/非表示 |
| | テーマ | — | ライト / ダーク |
| ヘルプ | バージョン情報 | — | バージョン・ライセンス表示 |

### 7.2 ツールバー

```
[ 📂 開く ] [ 📁 フォルダ ] [ 🔄 再解析 ]  |  言語: Python 3  |  [  進捗バー  ]
```

---

## 8. 状態管理 (ViewModel)

### 8.1 AnalysisViewModel

```python
class AnalysisViewModel(QObject):
    """解析状態の一元管理。両モードが共有する。"""

    # --- Signals ---
    file_loaded    = Signal(object, str, str)  # (ParseResult, source_text, file_path)
    dir_loaded     = Signal(list, str)         # ([ParseResult], dir_path)
    file_selected  = Signal(object, str, str)  # ツリーでファイル切替時
    analysis_started  = Signal(str)            # (target_path)
    analysis_progress = Signal(int, int)       # (current, total)
    analysis_error    = Signal(str)            # (error_message)

    # --- State ---
    current_path: str | None
    current_result: ParseResult | None
    current_source: str
    current_results: list[ParseResult]
    is_analyzing: bool
    active_mode: str          # "code" | "graph"

    # --- Methods ---
    def load_file(self, path: str) -> None: ...
    def load_directory(self, path: str) -> None: ...
    def reload(self) -> None: ...
    def switch_mode(self, mode: str) -> None: ...
```

### 8.2 データフロー

```
User: ファイルを開く
  ↓
MainWindow → QFileDialog → path
  ↓
AnalysisViewModel.load_file(path)
  ↓
AnalysisWorker (QThread):  pipeline.analyze_file(path)
  ↓
file_loaded Signal 発火
  ├─ CodeAnalysisView:
  │    ├─ ソースビューア: source_text を表示
  │    ├─ SymbolsPanel: extract_symbols(ast) → テーブル更新
  │    ├─ TokensPanel: result.tokens → テーブル更新
  │    └─ ASTPanel: result.ast → ツリー更新
  └─ GraphAnalysisView:
       └─ 選択中のグラフパネル: build_graph(result) → キャンバス更新
```

---

## 9. テーマ・スタイル

### カラーパレット (ライト / ダーク)

| 用途 | ライト | ダーク |
|------|--------|--------|
| 背景 | `#FFFFFF` | `#1E1E1E` |
| サイドバー | `#F5F5F5` | `#252526` |
| テキスト | `#1A1A1A` | `#D4D4D4` |
| モードタブ (アクティブ) | `#2196F3` | `#1565C0` |
| 関数 | `#4A90D9` | `#569CD6` |
| クラス | `#7B68EE` | `#C586C0` |
| 変数 | `#50C878` | `#6A9955` |
| import | `#FFB347` | `#DCDCAA` |
| エッジ | `#888888` | `#666666` |
| 選択ハイライト | `#E3F2FD` | `#264F78` |
| ソース行ハイライト | `#FFFDE7` | `#3E2723` |

### フォント

| 用途 | フォント |
|------|---------|
| UI テキスト | システムデフォルト |
| ソースコード / テーブル | `Consolas`, `Menlo`, monospace 12px |

---

## 10. エントリポイント

### CLI

```bash
orion-parser gui              # GUI を起動
orion-parser gui file.py      # ファイルを開いた状態で起動
orion-parser gui src/         # フォルダを開いた状態で起動
```

### pyproject.toml

```toml
[project.optional-dependencies]
gui = [
    "PySide6>=6.6",
    "networkx>=3.0",
]
```

---

## 11. 非機能要件

| 項目 | 要件 |
|------|------|
| 起動時間 | 3 秒以内 |
| 解析速度 | 1 ファイル 500ms 以内（1000 行） |
| メモリ | 100 ファイル解析時 500MB 以内 |
| スレッド | UI + 解析ワーカー（UI フリーズなし） |
| OS | Windows 10+, macOS 12+, Linux |
| Python | 3.12+ |

---

## 12. 永続化 (QSettings)

| キー | 説明 |
|------|------|
| `window/geometry` | ウィンドウ位置・サイズ |
| `window/sidebar_visible` | サイドバー表示状態 |
| `window/active_mode` | 最後のモード (code / graph) |
| `code/splitter` | ソース↔サブタブ比率 |
| `graph/splitter` | キャンバス↔詳細パネル比率 |
| `graph/active_type` | 最後のグラフ種別 |
| `graph/layout` | 最後のレイアウト |
| `recent/files` | 最近開いたファイル (10件) |
| `theme` | テーマ |
| `font_size` | フォントサイズ |

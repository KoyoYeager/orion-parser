# OrionParser

ソースコードの構造を丸ごと抜き出す多言語パーサエンジン。

## 何ができるか

- **コード構造の完全抽出** — 関数・クラス・変数の定義と関係をAST（抽象構文木）として取得
- **コールツリー生成** — 関数の呼び出し関係を自動で可視化
- **データフロー追跡** — 変数の定義・使用・伝播パスを追跡
- **エラー耐性** — 構文エラーがあるコードでも最大限の構造情報を抽出

## 対応言語

| 言語 | Lexer | Parser | 解析 | 状態 |
|------|-------|--------|------|------|
| Python | 開発中 | 開発中 | 開発中 | 🔨 |

## インストール

```bash
pip install orion-parser
```

## 使い方

```bash
# ファイルを解析
orion parse example.py

# コールツリーを表示
orion analyze --call-tree example.py

# JSON出力
orion parse --json example.py
```

## プロジェクト構成

```
src/orionparser/
├── core/               # 言語非依存の基盤
│   ├── pipeline.py     # パイプライン基底クラス
│   ├── nodes.py        # AST ノード基底クラス
│   └── visitor.py      # Visitor パターン
├── languages/          # 言語別の実装
│   └── python/         # Python 解析
│       ├── lexer.py    # 字句解析
│       ├── parser.py   # 構文解析
│       └── rules/      # 文法規則
├── analysis/           # 高次解析（NetworkX）
│   ├── call_tree.py    # コールツリー
│   └── data_flow.py    # データフロー
├── cli.py              # CLI エントリポイント
└── registry.py         # 言語レジストリ
```

## 開発

```bash
git clone https://github.com/KoyoYeager/orion-parser.git
cd orion-parser
pip install -e ".[dev]"
pytest
```

## ライセンス

MIT

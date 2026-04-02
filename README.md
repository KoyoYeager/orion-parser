# OrionParser

ソースコードの構造を丸ごと抜き出す多言語パーサエンジン。

## 何ができるか

- **コード構造の完全抽出** — 関数・クラス・変数の定義と関係をAST（抽象構文木）として取得
- **コメント追跡** — `ast` 標準モジュールが捨てるコメントをASTノードに紐づけて保持
- **シンボル一覧** — 関数・クラス・変数・importをスコープ付きで抽出
- **コールツリー生成** — 関数の呼び出し関係を自動で可視化
- **データフロー追跡** — 変数の定義・使用・伝播パスを追跡
- **エラー耐性** — 構文エラーがあるコードでも最大限の構造情報を抽出

## 対応言語

| 言語 | Lexer | Parser | 解析 | 実コードテスト | 状態 |
|------|-------|--------|------|--------------|------|
| Python 3.10-3.12 | ✅ | ✅ | ✅ | 2,458ファイル 100% | ✅ 完成 |

### Python パース実績

| テストコーパス | ファイル数 | パス率 |
|---|---|---|
| TheAlgorithms/Python | 1,375 | 100% |
| Flask | 83 | 100% |
| Python 標準ライブラリ (全パッケージ) | 694 | 100% |
| GitHub 60リポジトリ (Django, FastAPI, pandas, PyTorch 等) | 155 | 100% |
| stdlib トップレベル | 151 | 100% |

## インストール

```bash
git clone https://github.com/KoyoYeager/orion-parser.git
cd orion-parser
pip install -e ".[dev]"
```

## 使い方

```bash
# ファイルを解析（AST出力）
python -m orionparser parse example.py

# JSON出力
python -m orionparser parse --json example.py

# トークン一覧
python -m orionparser tokens example.py

# コールツリー・データフロー・シンボル解析
python -m orionparser analyze example.py
python -m orionparser analyze --call-tree example.py
python -m orionparser analyze --data-flow example.py
python -m orionparser analyze --symbols example.py

# 対応言語一覧
python -m orionparser langs
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
│       ├── lexer.py    # 字句解析 + INDENT/DEDENT + トークン変換
│       ├── parser.py   # LALR(1) 構文解析（PLY yacc）
│       ├── rules/      # 文法規則（6モジュール分割）
│       ├── preprocess/  # 前処理パイプライン（5ステージ）
│       └── comment_attacher.py  # コメント紐づけ
├── analysis/           # 高次解析
│   ├── call_tree.py    # コールツリー（NetworkX）
│   ├── data_flow.py    # データフロー（NetworkX）
│   └── symbols.py      # シンボル抽出
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

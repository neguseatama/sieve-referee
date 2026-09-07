# Sieve Referee

[English](README.md) | 日本語

> **「確率的AIモデルが生成したテキストを、別の確率的AIモデルで評価して本当に良いのだろうか？」**
> 完全ローカル実行・外部依存ゼロ・決定論的（100%再現可能）なテキスト構造・盗用スクリーニングエンジンです。[Sieve-Core](https://github.com/neguseatama/sieve-core) の拡張応用事例として開発しました。

[![PyPI Version](https://img.shields.io/pypi/v/sieve-scope.svg)](https://pypi.org/project/sieve-scope/)
[![Python Version](https://img.shields.io/pypi/pyversions/sieve-scope.svg)](https://pypi.org/project/sieve-scope/)
[![CI](https://github.com/neguseatama/sieve-scope/actions/workflows/test.yml/badge.svg)](https://github.com/neguseatama/sieve-scope/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

---

## 💡 コンセプトと開発思想
「エラトステネスの篩」に着想を得て設計した「集合論の篩」 Sieve-AI の設計思想を、より汎用的なテキスト・データ処理ドメインに適用したコアエンジンが Sieve-Core です。
その Sieve-Core に「組み合わせ論の篩」を追加設計した　`Sieve Referee` は、複数の独立した情報源による裏付けに基づき、ノイズから確かな情報を抽出するゼロディペンデンシーのPythonライブラリです。

LLMなどの確率的モデルが生成した可能性のある文章を評価する際、別の確率的モデルを用いて類似度スコアを計算すると、「なぜその数値になったのか」を数学的に追跡することが難しくなります。

`Sieve Referee` は、すべての判定結果を数学的に追跡可能にし、100%再現可能で、説明責任を果たせるスクリーニングエンジンを目指して開発しました。

- **決定論的アプローチ**: 16状態のルックアップテーブル（LUT、実際に到達可能なのは12状態）に基づいて判定します。同じ入力に対しては、何度実行しても必ず同じ結果になります。
- **説明可能性**: 判定結果には必ず理由（`reason`）と4ビットの仮説マスク（`mask`）が付与され、判定根拠を常に確認できます。
- **冤罪を防ぐ丁寧な分類**: 共通のフォーマットやテンプレートによる一致は、本文の一致とは区別して`COINCIDENTAL_FORMAT_MATCH`（`1100` / `YELLOW`）として分類します。
- **間接連鎖（伝言ゲーム型）の安全設計**: 直接の類似根拠がないペア（例: `A <-> B`と`B <-> C`は一致するが、`A <-> C`自体には直接の一致がない場合）を、クラスタ所属だけを理由に安易に「一致」へ昇格させません。このようなペアは、ダッシュボード上の「間接連鎖（伝言ゲーム）警告」として別枠で報告され、直接比較の結果自体は変更されません。

---

## 🎯 主な活用シーン

外部依存ライブラリなし・メモリ内処理という設計により、`sieve_referee` はプライバシー重視の組み込み型スクリーニングエンジンとして様々な場面で活用できます。

### 1. 教育・学習管理システム（EdTech / LMS）
学生の提出物を、個人情報や著作物を外部クラウドにアップロードすることなくチェックできます。共通の課題テンプレートは`YELLOW`、無断のコピー・言い換えは`RED`として検知します。

### 2. デジタルメディア・CMS
外部ライターから納品された記事のリライトや使い回しを、下書き保存のタイミングでリアルタイムに検知します。LLM APIのコストをかけずに済みます。

### 3. LLM学習用データセットの重複排除
ファインチューニング前のデータクレンジング工程として、近似重複や言い換えデータをGPUを使わず高速に除去します。

### 4. 法務・契約書・提案書（RFP）の比較審査
契約改訂版やベンダー提案書において、定型文（`COINCIDENTAL_FORMAT_MATCH`）と意図的に変更された条項を区別します。

### 5. CI/CDでのドキュメント監査
GitHub Actionsやpre-commitフックに組み込み、社内Wikiや仕様書間の無断コピー＆ペーストを検知します。

---

## ⚡ 技術的な利点

1. **コールドスタートがほぼゼロ** — PyTorchやTransformers等のモデルロードが不要なため、AWS Lambda等のサーバーレス環境に適しています。
2. **API利用コストがゼロ** — ローカルのCPUのみで完結します。
3. **保守負担がゼロ** — サードパーティ依存がゼロのため、脆弱性（CVE）対応や破壊的変更に巻き込まれません。

---

## 📦 インストール

```bash
pip install git+https://github.com/neguseatama/sieve-referee.git
```

またはローカルのクローンから:

```bash
git clone https://github.com/neguseatama/sieve-referee.git
cd sieve-referee
pip install .
```

---

## 🐍 使い方（Pythonライブラリ）

```python
from sieve_referee import batch_evaluate, EvaluationResult

# 1. 評価対象のテキストをメモリ上の辞書として用意
documents = {
    "report_a.txt": "本研究の分析結果は以下の通りである。主要なデータを示す。",
    "report_b.txt": "本研究の分析結果は次の通りである。主要なデータを提示する。"
}

# 2. スクリーニングを実行
results: list[EvaluationResult] = batch_evaluate(documents)

# 3. 判定結果の受け取りと利用
for res in results:
    print(f"ペア:     {res.item_id} <-> {res.matched_peer_id}")
    print(f"シグナル: {res.evaluation_signal.value}")  # -> RED
    print(f"マスク:   {res.mask}")                     # -> 1010
    print(f"パターン: {res.pattern_name}")              # -> PARAPHRASE_DETECTED
    print(f"理由:     {res.reason}")
    print("-" * 40)
```

### `EvaluationResult` の属性

| プロパティ | 型 | 説明 |
|---|---|---|
| `item_id` | `str` | 評価対象の文書ID |
| `matched_peer_id` | `str` | 比較相手の文書ID |
| `evaluation_signal` | `SignalColor` | 判定シグナル（`.value`で`"GREEN"`, `"YELLOW"`, `"RED"`を取得） |
| `mask` | `str` | 4ビット仮説マスク（例: `"1010"`） |
| `pattern_name` | `str` | LUTパターン名（例: `"PARAPHRASE_DETECTED"`） |
| `reason` | `str` | 判定理由の説明文 |

---

## 💻 使い方（CLIツール）

```bash
# 基本的なディレクトリ判定（reports/sieve_dashboard.htmlを生成）
sieve-referee ./target_documents

# 単一の独立HTMLレポートを生成（diff_htmls/フォルダを作らない）
sieve-referee ./target_documents --standalone --output-dir ./reports

# 自動化パイプライン向けのJSON出力、REDがあれば非ゼロ終了コード
sieve-referee ./target_documents --json --fail-on-risk

# マルチコアでの並列評価
sieve-referee ./target_documents -j 4
```

| オプション | 型 | 説明 |
|---|---|---|
| `target_dir` | 位置引数 | 評価対象の`.txt`ファイルが格納されたディレクトリ |
| `--output-dir` | 文字列 | レポート出力先（デフォルト: `reports`） |
| `--standalone` | フラグ | `diff_htmls/`フォルダを作らず、単一の自己完結型HTMLレポートを出力 |
| `--json` | フラグ | 判定結果をJSON形式で標準出力へ出力 |
| `--json-file` | 文字列 | 判定結果を指定パスのJSONファイルへ保存 |
| `--fail-on-risk` | フラグ | `RED`シグナルが1件でもあれば終了コード`1`で終了 |
| `-j`, `--jobs` | 整数 | 評価に使うワーカープロセス数（デフォルト: CPUコア数） |

---

## 📊 16状態ルックアップテーブル（LUT）

4つの独立した仮説（`H1`〜`H4`）を組み合わせた4ビットマスクが、決定論的にシグナル・パターン名・判定理由へマッピングされます。

| マスク | シグナル | パターン名 | 説明 |
|:---:|:---:|:---|:---|
| `1000` | 🟢 GREEN | `STANDARD_STRUCTURE_UNIQUE` | 構造・内容ともに独立した文書。 |
| `1100` | 🟡 YELLOW | `COINCIDENTAL_FORMAT_MATCH` | 共通フォーマット/テンプレートの一致のみ（内容は独自）。 |
| `1010` | 🔴 RED | `PARAPHRASE_DETECTED` | 構造は異なるが内容が一致（言い換え）。 |
| `1011` | 🔴 RED | `CLUSTER_PARAPHRASE_GROUP` | 3件以上のクラスタ内での組織的な言い換え。 |
| `1111` | 🔴 RED | `CLUSTER_EXACT_COPY` | 3件以上のクラスタ内での完全一致・テンプレート複製。 |

（16通りのうち実際に到達可能なのは12状態です。残り4状態——直接の類似根拠なしにクラスタ所属だけが立つ状態——は、設計上構造的に到達不能です。）

> **`H4`（クラスタ所属）と間接連鎖についての注記**
> `H4`は、そのペア自身に直接の類似根拠（`H2`または`H3`）があり、かつサイズ3以上のクラスタに属している場合にのみ立ちます。直接の根拠がないペアが、クラスタ所属だけを理由に昇格することはありません。そのような「伝言ゲーム型」の連鎖は、ダッシュボード上の間接連鎖警告として別枠で報告され、直接比較のペア自体の判定は変更されません。

---

## 📚 ドキュメント

- 🔌 [API & 統合ガイド](docs/INTEGRATION.md) — Pythonライブラリ、またはFastAPIマイクロサービスとしての利用方法
- 🚀 [デプロイメントガイド](docs/DEPLOYMENT.md) — DockerとTerraformによるGoogle Cloud Runへの構築
- 🔐 [CI/CD & セキュリティガイド](docs/CI_CD_SETUP.md) — Workload Identity Federationによる鍵なしGCPデプロイ
- 🏛️ [アーキテクチャ仕様書](docs/ARCHITECTURE.md) — 数理モデルと安全不変式の詳細

## 📄 ライセンス

MIT License。詳細は [LICENSE](LICENSE) を参照してください。

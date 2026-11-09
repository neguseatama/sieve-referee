# Sieve Referee v1.6.0

[English](README.md) | 日本語

> **「確率的AIモデルが生成したテキストを、別の確率的AIモデルで評価して本当に良いのだろうか？」**
> 完全ローカル実行・外部依存ゼロ・決定論的（100%再現可能）なテキスト構造・盗用スクリーニングエンジンです。[Sieve-Core](https://github.com/neguseatama/sieve-core) の拡張応用事例として開発しました。

[![PyPI Version](https://img.shields.io/pypi/v/sieve-referee.svg)](https://pypi.org/project/sieve-referee/)
[![Python Version](https://img.shields.io/pypi/pyversions/sieve-referee.svg)](https://pypi.org/project/sieve-referee/)
[![CI](https://github.com/neguseatama/sieve-referee/actions/workflows/tests.yml/badge.svg)](https://github.com/neguseatama/sieve-referee/actions/workflows/tests.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)

---

## 💡 コンセプトと開発思想
「エラトステネスの篩」に着想を得て設計した「集合論の篩」 Sieve-AI の設計思想を、より汎用的なテキスト・データ処理ドメインに適用したコアエンジンが Sieve-Core です。
その Sieve-Core に「組み合わせ論の篩」を追加設計した　`Sieve Referee` は、複数の独立した情報源による裏付けに基づき、ノイズから確かな情報を抽出するゼロディペンデンシーのPythonライブラリです。

LLMなどの確率的モデルが生成した可能性のある文章を評価する際、別の確率的モデルを用いて類似度スコアを計算すると、「なぜその数値になったのか」を数学的に追跡することが難しくなります。

`Sieve Referee` は、すべての判定結果を数学的に追跡可能にし、100%再現可能で、説明責任を果たせるスクリーニングエンジンを目指して開発しました。

- **決定論的アプローチ**: 16状態のルックアップテーブル（LUT、分類されるのは15状態）に基づいて判定します。同じ入力に対しては、何度実行しても必ず同じ結果になります。
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

### 6. LLM 生成記事の公開前スクリーニング（ハルシネーションゲート）
AI が関与した下書きの公開前に量化子監査レーンを実行し、証明も全件列挙もない全称主張（「必ず」「決して」「すべての〜」）——ハルシネーションの決定論的な足跡——を検知します。

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

### ライブラリからディスク上のファイルを読む

CLI と同じ判定でディレクトリを読むには `collect_txt_documents` を使います。
空や解読不能のファイルは黙って消えるのではなく、`skipped` として報告されます
（閉じた語彙 `empty_input` / `unreadable`・path 昇順）。

```python
from sieve_referee.io_utils import collect_txt_documents

documents, skipped = collect_txt_documents("path/to/dir")
for entry in skipped:
    print(entry["path"], entry["reason"])   # 例: empty.txt empty_input
```

### `EvaluationResult` の属性

10 個の dataclass 属性をすべて掲載します。判定そのものは
`evaluation_signal` / `mask` / `pattern_name` / `reason` が担い、4 つの
スコア属性が判定に至った根拠を示します。

| プロパティ | 型 | 説明 |
|---|---|---|
| `item_id` | `str` | 評価対象の文書ID |
| `matched_peer_id` | `str` | 比較相手の文書ID |
| `evaluation_signal` | `SignalColor` | 判定シグナル（`.value`で`"GREEN"`, `"YELLOW"`, `"RED"`を取得） |
| `mask` | `str` | 4ビット仮説マスク（例: `"1010"`） |
| `pattern_name` | `str` | LUTパターン名（例: `"PARAPHRASE_DETECTED"`） |
| `reason` | `str` | 判定理由の説明文 |
| `structural_density` | `float` | H1: 主文書の異なる文字の密度 |
| `max_structure_similarity` | `float` | H2: 比較相手との骨格 n-gram 類似度の最大値 |
| `max_content_similarity` | `float` | H3: 比較相手との内容語類似度の最大値 |
| `coverage` | `float` | 主文書の文のうち H3 判定の根拠となった割合 |

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
| `--spans` | フラグ | 説明層: `--json` / `--json-file` の payload に `spans` キーを追加し、ペアごとに依頼書 §3.2 の winnowing 指紋が見つけた一致区間（k=8 文字・w=5・最小 16 文字・blake2b・PYTHONHASHSEED 非依存）を RAW ファイル原文の位置（NFKC 対応表で逆引き）で示す。本文を変えるフラグ（`--exclude-quotes` / `--exclude-bibliography` / `--base`）とは併用不可。指定しない限り出力は1バイトも変わらない |
| `--base` | 文字列 | 基準文書ディレクトリ（`.txt`）。依頼書 §3.3 の 2 義務: （1）ここにある文書は評価宇宙から完全に除外される（結果・クラスタに現れないため、共通テンプレートによる無実のペアのクラスタ昇格が起きない）＋（2）各提出物の中にある基準文書と一致する区間（§3.2 winnowing 指紋が見つけた一致を完全一致域まで延長・16 文字以上）を評価の前に取り除く（課題文を引用しているだけの提出物どうしが似ていると判定されなくなる）。fail-closed: ディレクトリが不在・空・読めないファイルを含む、または対象文書と名前が衝突する場合は終了コード`2` |
| `--exclude-quotes` | フラグ | 比較前に引用（内側10文字以上の「…」対）を除去する。既定は無効（指定しない限り出力は1バイトも変わらない） |
| `--exclude-bibliography` | フラグ | 比較前に参考文献節（参考文献 / 引用文献 / References / Bibliography / Works Cited / Literature Cited の6種見出し語彙・Latinは大文字小文字を無視して一致、その行から文書末尾まで）を除去する。既定は無効（指定しない限り出力は1バイトも変わらない）。2つの除外は独立したフラグ（結合エイリアス無し）。両方指定時は参考文献を先に、次に引用を除去する |

出力はデフォルトで安全です: すべての HTML 出力でファイル名と本文は escape され、
スタンドアロンレポートは悪意あるファイル名でもページを壊さない形で JSON を埋め込み、
ダッシュボードは直接の RED ペアと間接チェーン警告を区別して表示し、評価できなかった
ファイル（空・読み取り不可）は黙って消えるのではなく、閉じた語彙の理由
（`empty_input` / `unreadable`）つきで JSON の `skipped` キーに列挙されます。

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
| `0111` | 🔴 RED | `CLUSTER_FORMATTED_PARAPHRASE` | 3件以上のクラスタ内での、共通構造を用いた言い換え再利用。 |
| `0101` | 🟡 YELLOW | `CLUSTER_FORMAT_ONLY_MATCH` | 3件以上のクラスタ内での共通テンプレート/構造の一致のみ（内容は独自）。 |
| `0011` | 🔴 RED | `CLUSTER_UNFORMATTED_CONTENT_COPY` | 3件以上のクラスタ内での、構造的共通性のない内容複製。 |

（16通りのうちLUTに分類されるのは15状態です。このうち `0001` と `1001` の2状態——直接の類似根拠なしにクラスタ所属だけが立つ状態——は構造的に到達不能で、`1001` は定義こそ存在するものの現在の実装経路では生成されず、`0001` は表に定義のない唯一の状態です。さらに `0011`・`0101`・`0111` の3状態はクラスタ昇格で発生し、専用のLUTエントリで分類されます。）

> **`H4`（クラスタ所属）と間接連鎖についての注記**
> `H4`は、そのペア自身に直接の類似根拠（`H2`または`H3`）があり、かつサイズ3以上のクラスタに属している場合にのみ立ちます。直接の根拠がないペアが、クラスタ所属だけを理由に昇格することはありません。そのような「伝言ゲーム型」の連鎖は、ダッシュボード上の間接連鎖警告として別枠で報告され、直接比較のペア自体の判定は変更されません。

---

## 🔍 量化子監査レーン（v1.3.0 で導入）

ペア評価とは別軸の監査レーンとして、**裏付けのない全称命題**——LLM のハルシネーションの決定論的な足跡——を公開前にスクリーニングできます。

> **運用定義**
> *⊢（形式的導出）による裏付けも、⊨_fin（有限モデルの網羅的確認——実際に実行された全件列挙）による裏付けもないまま全称的スコープを閉じることは、**非根拠的普遍化**である。監査レーンはこれを決定的に検出する。検出された普遍化がハルシネーションであるかどうかの処分は Human にある。*

エンジンは**文の真偽を一切評価しません**。著者が裏付けタグを付けたかどうかだけを見ます。そのため空虚な真（空ドメイン上の全称が形式的に真となる現象）に構造的に免疫を持ち、すべての判定が 100% 再現可能です。

**パイプライン（全段階が決定論的）:**

1. 文分割（`ja`: 。「！」「？」+ 改行 / `en`: 小数・次文字・省略形ガードつきの `.` + `!` `?` 改行）
2. 全称量化語彙の全列挙（`ja`: 21 パターン・recall 重視 / `en`: 17 パターン・小文字宣言・単語境界照合）
3. `sentence_sha256` による指紋化（tagfile の鍵）
4. Human tagfile（`backing` / `scope`）— エンジンは推測しない
5. 8 状態監査 LUT + `--fail-on-unverified` CI ゲート

**裏付けの意味論（近代論理学のセマンティクスに整合）:**

| タグ | 論理学的意味 | シグナル（全称スコープ時） |
|---|---|---|
| `theorem` | `⊢` — 宣言された形式体系内での導出可能性 | 🟢 GREEN |
| `enumerated` | `⊨_fin` — 有限モデルの網羅的充足（実行済み） | 🟢 GREEN |
| `sample` | 有限標本 + 明示的スコープ宣言 | 🟡 YELLOW |
| （無タグ） | 上記のいずれでもない | 🔴 RED（`UNBACKED_UNIVERSAL`） |

無限定の ⊨ は決定不能であるため（Church の定理）、エンジンが受理するのは決定可能な断片——⊢ と ⊨_fin——のみです。これが「エンジンは推測しない」原則の理論的な形です。

**v1.3.0 で追加 — 確信度マーカー:** 全称語彙と認識的強意語（「確実に」「明白に」等）の同一文内での共起は、`certainty_markers` としてワークシートに注記されます。注記は判定を一切変更しません。GREEN/YELLOW/RED を決めるのはタグのみです。

**v1.4.0 で追加 — 英語プロファイル（`--lang`）:** 監査レーンに英語専用プロファイルが加わりました。`--lang {ja,en,auto}` が語彙・文分割・照合・理由文を 1 セットで切り替えます（既定 `ja` は v1.3.1 と 1 バイトも変わりません）:

- **`en` 語彙（17 パターン・小文字宣言）:** all / every / everyone / everybody / everything / each / any / none / neither / both / no / must / without exception に、v1.5.0 で低リスク時間絶対語 4 語（invariably / without fail / around the clock / 24/7）を追加。always / never / permanently は日本語側と同じ誤検出リスクの理由（*not always / never mind / as always* 等の非主張用法が体系的に多い）で恒久不採用 — v1.5.0 で恒久決定として決着しました。
- **単語境界照合**（大文字小文字を無視・長さ保存の小文字化）: all は *ballot / allow / small / alloy* の内部に一致しなくなり、no は *notify / nobody* の内部に、every は *everywhere* の内部に一致しません。
- **除外フレーズ（34・決定論的）:** 語境界一致した除外フレーズ（*not all, at all, after all, all but, all rights, each other, every now and then, if any, no longer, no doubt, no.* 等）と重なる出現だけが除外され、文自体は対象に残ります。`All rights are reserved.` は候補にならず、`All nodes must sync.` は候補になります。
- **疑問文除外:** `?` で終わる文は `en` では監査対象外です（疑問は全称主張ではない）。日本語の `？` 終端文は従来どおり候補になります（変更なし）。
- **理由文:** 監査レーンの `reason` は英語テーブル（`AUDIT_LUT_REASONS_EN`）を持ち、8 状態・シグナル・`pattern_name` は日本語 LUT と完全に同一です。
- **`auto`**: 読み込んだ全文書のかな文字（ひらがな+カタカナ）比率による決定論的判定（比率 ≥ 0.05 なら `ja`、それ以外 `en`）。CI では `--lang` の明示指定を推奨（`auto` は利便性用）。
- 日英 54 ケースの対訳コーパス（等価全称・除外フレーズ罠・単語境界罠・疑問文・強意語共起・裏づけつきペア）が `tests/test_quantifier_audit_en.py` に cross-lingual 動作を機械固定しています。

**v1.5.0 で追加 — 様相・時間スコープ拡張（`#1`）:** 語彙に承認済み低リスク子集を追加しました:

- **ja 量化子 +3（18 → 21）:** 絶えず / 四六時中 / 24時間365日。不採用（誤検出リスク）: 常時（非常時との部分文字列衝突）・24時間（24時間以内等の期限用法）・全く（裸強調）。既存 18 語は 1 語も変更していません。
- **en 量化子 +4（13 → 17）:** invariably / without fail / around the clock / 24/7。forever は慣用衝突（*nothing lasts forever* 等）で不採用、*at all times* / *every time* は既存 all / every が単語境界で捕捉済みのため重複登録せず。既知の衝突: 日付表記（24/7/2025 等）が候補になり得ます（recall 重視・Human が数秒で処分）。
- **ja 修飾語 +7（10 → 17）/ en 修飾語 +8（9 → 17）・注記専用:** 必然的に / 不可避的に / 自ずと / おのずと / 疑いようがない / 疑いようもない / 言うまでもなく および unquestionably / indisputably / beyond doubt / by definition / self-evidently / manifestly / as everyone knows / it goes without saying。認識的必然マーカーは GREEN/YELLOW/RED を一切変えません（LUT 意味論は無変更）。構造必然表現（構造上 / *by design* / *structurally*）は設計制約の叙述であり認識的過剰主張でないため不採用。日本語は副詞形のみ採用し、「必然ではない」等の否定形を注記しません。
- **コーパス +24 ケース（F/G/H 区分）:** 時間絶対語の対訳等価（両言語 RED）・新マーカー注記（シグナル不変・定理タグで GREEN）・不採用語トリップワイヤと極性ガード（「疑問の余地がある」は注記しない）— 合計 78 ケース（セクション 74 項目 + 裏づけつきペア 4）。

**v1.5.0 で追加 — 位置ベース Audit Risk Index（`--risk-index`・`#4`）:** RED の処分順序を、位置ベースの 3 シグナルのみ（文依存案は破棄済み）から決定論的に整序します:

- **見出し階層深度** — markdown ATX 見出し（`#`〜`######`・フェンス内は無視）を決定論的に走査し、候補の直前の最後の見出しの深度を引き継ぐ。深度 0（冒頭サマリ）が最重視。番号付き見出し（「1.1」「第 1 章」）は平文扱い。
- **セクション内出現順** — 同一セクション内での出現順（最初の主張がセクションの論点）で、1 番目が最重視。
- **節内密度** — 当該文に含まれる全称語パターン数（1 / 2 / 3+）。

`risk_index = round_half_up(0.40·H(d) + 0.30·O(rank) + 0.30·D(n))`、35–100 の整数。重みはすべて固定の千分率定数として receipt に記録され、計算は純粋な整数演算（round-half-up・浮動小数の丸め込みなし）。`--risk-index` は**既定 OFF**: 指定しない限り receipt もレポートも従来版と 1 バイトも変わりません。指定すると各候補に `risk_index` + `risk_factors` が付き、人間用レポートに RED を降順で並べた `PRIORITY` セクションが追加されます。シグナルは一切変わりません。

```bash
# 英語の下書きディレクトリを監査
sieve-referee ./draft_en --audit --lang en --fail-on-unverified

# 文書群自身から言語を決定論的に判定
sieve-referee ./mixed_dir --audit --lang auto
```

**監査レーンの CLI オプション:**

| オプション | 説明 |
|---|---|
| `--audit` | 監査レーンを有効化 |
| `--audit-vocab PATH` | 全称語彙ファイル（未指定: 内蔵 21 パターン） |
| `--audit-tags PATH` | tagfile（JSON・`sentence_sha256` を鍵） |
| `--audit-modifier-vocab PATH` | 強意語彙ファイル（v1.3.0） |
| `--lang ja\|en\|auto` | 監査レーンの言語プロファイル（v1.4.0・既定 `ja`） |
| `--risk-index` | 位置ベース Audit Risk Index（v1.5.0・`risk_index`/`risk_factors` 付与 + RED `PRIORITY` セクション・既定 OFF） |
| `--fail-on-unverified` | 裏付けのない全称（RED）が 1 件でも残れば終了コード `1` |

```bash
# 下書きディレクトリを監査（RED 残留なら非ゼロ終了）
sieve-referee ./draft_dir --audit --fail-on-unverified

# Human によるタグ付け後の再監査（worksheet の sha256 → tags.json → 再実行）
sieve-referee ./draft_dir --audit --audit-tags tags.json --fail-on-unverified
```

既知の限界: 語彙にない全称表現は拾えません（偽陰性クラス）。タグ自体の真偽は検証者の責任です（tagfile の `evidence` フィールドに出所を記録）。英語固有の限界: `en` 語彙は表層一致・小文字宣言のため、*anybody / nobody* のような形態変化形は列挙しておらず取りこぼします。省略形ガードは固定リストのため万能ではありません。除外フレーズは経験的なリストであり、文法から導出されるのではなく対訳コーパスで固定・拡張されます。v1.5.0 追加分: `--risk-index` の見出し走査は markdown ATX のみ（番号付き・日本語様式の見出しは平文扱い）。修飾語（強意語）レーンには否定ガードがなく、"not necessarily" 等は誤注記になります（recall 重視）。`24/7` は日付表記と衝突し得ます。時間絶対語 always / never は `en` 側では恒久不採用のため拾えません（ja 側は v1.3.0 coverage の常時系 = 常に / 決して等を維持）。

---

## 📚 ドキュメント

- 🔌 [API & 統合ガイド](docs/INTEGRATION.md) — Pythonライブラリ、またはFastAPIマイクロサービスとしての利用方法
- 🚀 [デプロイメントガイド](docs/DEPLOYMENT.md) — DockerとTerraformによるGoogle Cloud Runへの構築
- 🔐 [CI/CD & セキュリティガイド](docs/CI_CD_SETUP.md) — Workload Identity Federationによる鍵なしGCPデプロイ
- 🏛️ [アーキテクチャ仕様書](docs/ARCHITECTURE.md) — 数理モデルと安全不変式の詳細

## 📄 ライセンス

MIT License。詳細は [LICENSE](LICENSE) を参照してください。

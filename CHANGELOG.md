# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.6.0] - 2026-11-09

### Added
- **Explanation layer (`--spans`, `sieve_referee.explain`)**: every pair can
  now be explained against the ORIGINAL text without changing any judgment.
  `nfkc_starts(original)` builds the deterministic NFKC position map
  (normalized position → original start position, non-decreasing, with a
  sentinel; verified against the true normalization with an exact
  prefix-length fallback), covering both NFKC shapes: decomposition
  (か + combining dakuten → が, 2 → 1) and expansion (U+FB01 ligature → "fi",
  1 → 2). `explain_results(documents, results)` returns, per pair, the
  matched spans found by the M2 request §3.2 winnowing fingerprint
  (k=8 characters, w=5, minimum match length 16 characters —
  `sieve_referee.fingerprint`, blake2b digests so the output is
  independent of PYTHONHASHSEED; each reported span is a verbatim exact
  match on both sides, extended around its fingerprint seed, and spans are
  reported regardless of the judgment, so a GREEN pair sharing a
  >=16-character run is reported as well), with positions into the texts
  as passed in. This is the same mechanism and span contract Scope 1.5.0
  uses, so Tray's Cohort can treat both engines in one shape (design
  review round 3: the first draft used sentence-level H3 pairs, which
  did not follow §3.2). `EvaluationResult` keeps exactly its ten
  fields; results are identical with or without the layer. The CLI
  `--spans` flag adds a `spans` key to the `--json` / `--json-file` payload
  (`{"pair_key": [{"a_start", "a_end", "b_start", "b_end"}]}`, positions
  composed back to the RAW file text through the same map; the file is
  re-read and must be unchanged, otherwise exit 2). `--spans` cannot be
  combined with any flag that changes the judged text —
  `--exclude-quotes` / `--exclude-bibliography` / `--base` (exit 2). Without
  the flag every output stays byte-identical (pinned molds).
- **Fingerprint module (`sieve_referee.fingerprint`)**: the §3.2 winnowing
  fingerprint as a public, reusable layer — `kgram_hashes` (blake2b,
  digest 8 bytes, salted `hash()` never used), `winnowing_fingerprints`
  (leftmost minimum per w-wide window, deterministic), and
  `fingerprint_match_spans` (shared exact-match spans recovered from the
  fingerprints: pairs grouped by relative offset, coverage spans merged,
  extension over the surrounding verbatim match, minimum length
  `MIN_FINGERPRINT_SPAN = 16`). A complete exact match of >= 16 characters
  is always recovered in full (winnowing guarantee: matches of length
  >= w+k-1 = 12 share a fingerprint); shared runs shorter than 16
  characters never appear (pinned by RF-T11a..c).
- **Base documents (`--base`, `base_documents=`) — both §3.3 obligations**:
  (1) documents given as base (e.g. the assignment text) are excluded from
  the evaluation universe entirely — they never appear as
  `item_id`/`matched_peer_id`, never form candidate pairs and never enter
  clusters, so they can no longer escalate innocent pairs through H4
  cluster promotion (measured on 1.5.2: a shared template turned a direct
  `1010` PARAPHRASE_DETECTED into `1011` CLUSTER_PARAPHRASE_GROUP for a
  pair whose own content only shared the template's format); AND (2) spans
  of each submission that match a base document are removed BEFORE the
  comparison (`sieve_referee.base_strip.strip_base_segments`: matches
  found through the §3.2 winnowing fingerprint spans in NFKC space and
  extended to the full verbatim run, minimum span 16 characters — §3.2's
  fingerprint minimum, raised from the first draft's 10 per the design
  review round 3, single pass — so submissions sharing only the
  assignment text no longer look similar to each other). The removal
  report maps every removed span back to the text as passed in
  (`{"start", "end", "length", "text"}` through the NFKC position map); a
  submission left empty by the removal flows through the existing GREEN
  vocabulary. The CLI is fail-closed: a missing, empty or partially
  unreadable base directory, or a base file name colliding with a target
  document, exits with status 2 and an `Error:` line.
- **Quote exclusion (`--exclude-quotes`, `exclude_quotes=`, default OFF)**:
  before comparison, removes 「…」 quotation pairs whose inner text is at
  least 10 characters (single left-to-right pass, brackets included;
  shorter pairs are kept). With the flag absent nothing changes
  (byte-identical, pinned).
- **Bibliography exclusion (`--exclude-bibliography`,
  `exclude_bibliography=`, default OFF)**: before comparison, removes
  bibliography sections — a heading line equal to one of
  参考文献 / 引用文献 / References / Bibliography / Works Cited /
  Literature Cited (Latin words case-insensitively), from that line to the
  end of the document. With the flag absent nothing changes
  (byte-identical, pinned). The two exclusions are independent flags per
  the M2 request §3.4 (the design-review round split the single
  `--exclude-citations` flag of the first draft; no combined alias is
  kept, so the Tray checkboxes can map 1:1). When both are requested the
  bibliography is removed first, then the quotes (order fixed at the red
  stage); a pair whose only overlap was a long quotation or a shared
  bibliography becomes GREEN while short quotation pairs keep the
  original judgment.

### Changed
- **The `sieve-core-engine` dependency declaration is removed**
  (`dependencies = []`): the package imports no `sieve_core` module and
  references none by string (re-measured in this lane); Referee has been
  zero-dependency in fact, and is now zero-dependency in metadata as well.
  The PEP 639 license form is untouched
  (`license = "MIT"` + `license-files = ["LICENSE"]` + `setuptools>=77.0`,
  no License classifier — measured on PyPI 1.5.2 as
  `license_expression`/`license_files`).
- **Version bumped to 1.6.0**; README (en/ja) headers updated and the
  `EvaluationResult` attribute table now lists all ten fields (previously
  six of ten).

## [1.5.2] - 2026-11-07

### Added
- **`skipped` from the library**: the file-reading path is now available as a
  library API, `sieve_referee.io_utils.collect_txt_documents(directory)`,
  returning `(documents, skipped)` with the exact same judgment and the same
  closed vocabulary (`empty_input` / `unreadable`) as the CLI — so library
  consumers (e.g. Sieve-Tray) can receive the engine's skip report without
  going through the CLI. `batch_evaluate`, which receives already-read text,
  keeps its existing return type and keys unchanged: nothing it receives is
  unread, so it has no skipped entries by construction. The CLI now delegates
  its own reading loop to the same function; outputs are byte-identical to
  1.5.1 (pinned molds cover the `--json` stdout and the standard dashboard,
  with and without skipped files).

### Changed
- **Version bumped to 1.5.2** (library reporting addition only; no change to
  already-observed evaluation results, exit codes, or existing output keys).

## [1.5.1] - 2026-11-06

### Fixed
- **HTML output safety**: file names interpolated into the standard
  dashboard's alert cards and into the diff reports' `<title>`/`<h2>` are now
  passed through `html.escape`, and diff report bodies are escaped
  (`&`/`<`/`>`) — a name or document containing `<script>` can no longer
  inject markup into the generated pages. The standalone dashboard embeds its
  JSON with `<`, `>`, `&`, U+2028 and U+2029 rewritten to JS escapes
  (`\u003c` …), so a file name containing `</script>` can no longer close the
  script block; the value JS parses is unchanged. Outputs for inputs without
  these characters are byte-identical to 1.5.0 (pinned molds).
- **Direct RED pairs were hidden behind "NO_ALERTS"**: when a direct RED pair
  exists, the standard dashboard now prints the count and the list of direct
  RED pairs in addition to any indirect ("telephone game") chain warnings.
  "NO_ALERTS" appears only when there is neither a direct RED pair nor an
  indirect chain.
- **Silent file skipping**: empty, blank, undecodable and permission-denied
  `.txt` files are now reported. Permission-denied files previously crashed
  the CLI with a traceback. When files are skipped, the JSON payload carries
  an added `skipped` list (`path` + closed-vocabulary `reason`:
  `empty_input` / `unreadable`) — with zero skipped files the payload stays
  byte-identical to 1.5.0 — a `Skipped N file(s): …` summary line is printed
  to stderr, and the dashboard gains one `Skipped N file(s)` line. Exit codes
  and the existing result keys are unchanged.

### Changed
- **Version bumped to 1.5.1** (output safety and reporting fixes; no
  observable change to already-observed evaluation results).
- **Docs alignment**: `docs/ARCHITECTURE.md` said the LUT has 12 states; the
  measured table holds 15 classified states (as README and the pinned tests
  already stated). The architecture document now matches the code; the code
  itself is unchanged.

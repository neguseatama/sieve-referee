# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

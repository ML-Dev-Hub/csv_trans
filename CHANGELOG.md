# Changelog

All notable changes to `csv-trans` are documented here. The project follows
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.1] - 2026-07-23

### Changed

- The `Documentation` project URL now points to the hosted documentation site
  at <https://ml-dev-hub.github.io/csv_trans/>.

### Removed

- Outdated internal documentation files `PRODUCT_DIRECTION.md`,
  `RELEASING.md`, and `REPOSITORY_AUDIT.md`.
- The `Security` project URL from packaging metadata.

## [2.0.0] - 2026-07-23

### Added

- A provider boundary for the built-in no-key Google web translator,
  OpenAI-compatible endpoints, and Anthropic's Messages API.
- Explicit `public`, `restricted`, and `local-only` privacy modes.
- Structured translation results with `success`, `partial`, `cancelled`, and
  `dry-run` outcomes and per-cell failure details that do not contain source
  text. `RunStatus.FAILED` is reserved; fatal v2 errors raise to the caller.
- Automatic text-column selection, explicit column overrides, optional header
  translation, bounded recovery, adaptive context splitting, and atomic output.
- Both `csv-trans` and the historical `csv_trans` console commands.
- Complete type information and a `py.typed` marker.
- Offline standard-library tests across Python 3.11-3.14 on Linux, macOS, and
  Windows, plus wheel and source-distribution installation smoke tests.

### Changed

- CSV parsing, writing, HTTP transport, retries, and provider orchestration now
  use only the Python standard library.
- Python 3.11 is now the minimum supported version.
- Headers are preserved unless header translation is explicitly requested.
- When columns are omitted, identifier-like and numeric fields are skipped and
  text-like fields are selected automatically.
- Failed cells preserve their original value while processing continues safely;
  the result and CLI exit status expose partial completion.
- Provider responses are mapped by exact stable IDs, reject empty translations
  by default, and preserve an encodable original when translated text cannot be
  represented in the requested output encoding.
- Packaging is declarative through `pyproject.toml`, with no mandatory runtime
  dependencies.
- Release builds use pinned build tooling and immutable GitHub Action commits.

### Fixed

- Provider failures can no longer add values or shift CSV row alignment.
- Long-text chunking no longer deletes boundary characters or whitespace.
- CSV dialects and separators are preserved on output.
- Single-column and duplicate-header CSV files no longer rely on pandas label
  behavior.
- Provider work no longer creates multiprocessing spawn loops on Windows
  ([#14](https://github.com/ML-Dev-Hub/csv_trans/issues/14)).
- Provider exceptions no longer cross process boundaries or fail to deserialize
  ([#15](https://github.com/ML-Dev-Hub/csv_trans/issues/15)).

### Removed

- The pandas/PyArrow data path and all 19 historical mandatory requirements.
- `deep-translator`, `googletrans`, process pools, global warning suppression,
  and provider-specific exceptions from the public workflow.
- The repository's third-party license notices for the removed 1.x runtime
  stack; the v2 distribution contains only the project's MIT-licensed,
  standard-library implementation.
- The inaccurate Python 3.6 compatibility claim.

### Security

- Credentials are read from explicit configuration or environment variables
  and are never written to reports.
- `local-only` policy rejects non-local endpoints before translation data is
  submitted and never falls back to a public provider.
- Provider reports record destinations and error categories without storing
  cell contents, translated values, credentials, or header names by default.
- Endpoint recipients are revalidated before every request, redirects and
  ambient proxies are disabled in the built-in transport, and reports publish
  through collision-safe atomic writes.
- Official vendor credentials are isolated from compatible/custom destinations;
  spreadsheet formula handling and plaintext crash-residue boundaries are
  documented explicitly.

See [Migrating to v2](docs/internal/MIGRATION_V2.md) for compatibility details.

## [1.1.4] - 2023-03-29

- Last release of the pandas/PyArrow and `deep-translator` implementation.
- Added command-line and Python entry points for whole-file CSV translation.

[2.0.1]: https://github.com/ML-Dev-Hub/csv_trans/compare/v2.0.0...v2.0.1
[2.0.0]: https://github.com/ML-Dev-Hub/csv_trans/compare/1.1.4...v2.0.0
[1.1.4]: https://github.com/ML-Dev-Hub/csv_trans/releases/tag/1.1.4

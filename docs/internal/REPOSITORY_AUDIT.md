# csv_trans repository audit and modernization plan

> **Historical pre-v2 snapshot:** This document records the repository at the
> audited commit below, before the version 2 rewrite. Statements about the
> "present implementation," the 21-test baseline, dependencies, and unresolved
> defects describe version 1.1.4 at that commit—not the current v2 source tree.
> See [`ARCHITECTURE_V2.md`](ARCHITECTURE_V2.md), the
> [`CHANGELOG.md`](../CHANGELOG.md), and [`TESTING.md`](../TESTING.md) for the
> implemented v2 behavior and test bed.

Audit date: 2026-07-17  
Audited branch: `main`  
Audited commit: `67cf6a24dcf6c2e8d7f9e8e029cbcd6b13690808`

The maintainer's post-audit provider, dependency, privacy, and recovery
decisions are recorded in [PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md).

## Scope and method

This audit covers the complete tracked repository, its Git history, published
package metadata, public GitHub issues, packaging behavior, dependency
resolution, and executable behavior on Windows with Python 3.12.9.

The local commit was verified against GitHub's current `main` branch. The
working tree was clean before the audit. The runtime code was not changed as
part of this pass; only this report and an offline test bed were added.

Evidence gathered during the audit includes:

- All tracked source, metadata, documentation, sample data, and GitHub files.
- All 104 local commits and the four release tags.
- Public GitHub issue, pull request, release, and branch metadata.
- Current PyPI metadata and an isolated editable installation of 1.1.4.
- Focused local probes for chunking, failures, DataFrame invariants, CLI exit
  behavior, dependency exception serialization, and HTTP timeout propagation.
- A deterministic 21-test baseline that makes no live translation request.

## Executive conclusion

The repository is small and understandable: 337 source lines, 11 functions,
one public Python function, and one CLI entry point. Its present implementation
is nevertheless unsafe for production CSV data.

Three problems deserve immediate priority:

1. A handled timeout or missing translation adds an extra output value. This
   shifts later rows in one column and can silently break record alignment.
2. Long-text chunking can delete a source character or whitespace.
3. Multiprocessing around provider calls causes both open GitHub issues on
   Windows and turns ordinary provider errors into hangs or obscure
   deserialization failures.

The package also installs 19 direct requirements that resolve to 29 production
distributions on Python 3.12. Most are unused transitives. The observed local
`site-packages` occupied 233.6 MB including pip, while the published
`csv_trans` wheel itself is 7.8 KB.

The recommended direction is a streaming standard-library CSV core, a small
provider protocol, deterministic error/result models, and optional provider or
server extras. The CLI, Python API, and a later HTTP API should all call the
same orchestration service.

## Current package status

| Item | Verified state |
|---|---|
| Published version | 1.1.4 |
| PyPI upload | 2023-03-29 |
| GitHub release tags | 1.0.1, 1.1.2, 1.1.3, 1.1.4 |
| Current `main` | `67cf6a2`, pushed 2024-07-02 |
| Runtime changes after 1.1.4 | None; only a README contributor link changed |
| Public issues | 2 open, 0 closed issues |
| Pull requests | 13 historical, all merged; none open |
| Active CI | None |
| Existing tests before this audit | None |
| Declared runtime requirements | 19 |
| Python 3.12 resolved production distributions | 29 including `csv-trans` |

The published package and setup metadata still point to the old
`universal-translator-for-csv-files` repository even though the canonical
repository is now `ML-Dev-Hub/csv_trans`.

## Repository map

### Runtime package

- `csv_trans/__init__.py`
  - Eagerly imports and exposes only `translate`.
  - Does not expose `__version__` or an explicit public API list.

- `csv_trans/cli.py`
  - Defines the installed `csv_trans` console command.
  - Uses standard-library `argparse`, not the declared `click` dependency.
  - Parses four arguments and calls the public `translate()` directly.
  - Does not validate languages or produce meaningful nonzero failure codes.

- `csv_trans/translate.py`
  - Coordinates detection, reading, validation, header mutation, translation,
    progress display, and saving.
  - Also contains a second function named `main()` that is not the installed
    CLI. It performs language validation but is not used by either public path.

- `csv_trans/utils.py`
  - Combines encoding detection, CSV I/O, provider calls, text chunking,
    concurrency, DataFrame reconstruction, output naming, and error display.
  - Globally disables all warnings as an import side effect.

### Packaging and project files

- `setup.py`
  - Legacy imperative packaging, version, console entry point, stale links, an
    embedded copy of the README, and all 19 requirements.

- `README.md`
  - Contains installation and minimal CLI/Python examples, but does not explain
    actual provider behavior, column selection, privacy, output, overwriting,
    error semantics, service reliability, or limits.

- `data/test.csv`, `data/english.csv`
  - Two tracked `id,eng` samples with 52 and 502 lines respectively, including
    the header.
  - The entire `data/` directory is also ignored, an inconsistent policy.

- `LICENSES/`
  - Hand-copied licenses for part of the old dependency graph. They do not
    replace automated dependency and license inventory.

- `.github/dependabot.yml`
  - Inert because `package-ecosystem` is an empty string.

- `.github/ISSUE_TEMPLATE/bug_report.md`
  - Requests browser and smartphone details rather than Python version,
    package version, command, traceback, input shape, and encoding.

- `CODE_OF_CONDUCT.md`
  - Leaves the enforcement contact blank.

## Actual execution flow

```text
Python API or installed CLI
          |
          v
read first 200 bytes -> chardet encoding guess
          |
          v
pandas.read_csv(..., engine="pyarrow")
          |
          v
reject empty DataFrame
          |
          v
rename only column index 1 to the target-language argument
          |
          v
spawn up to one process per column
          |
          v
translate every string cell using a new GoogleTranslator per cell/chunk
          |
          v
rebuild columns with new Series and a new RangeIndex
          |
          v
write translated_<target>_<original-name> using comma delimiter
```

Important consequences of that flow:

- Every column is processed, even though only the second header is renamed.
- String IDs, URLs, formulas, names, codes, and notes are sent to the remote
  provider along with intended prose.
- Numeric-looking cells may or may not be sent depending on pandas type
  inference, so behavior changes with the data in the same column.
- The complete input and output are held in memory.
- The output silently overwrites an existing file of the same name.
- A non-comma input is always saved as comma-separated data.
- CSV type inference can alter leading zeros, missing-value spellings, numeric
  formatting, quoting, line endings, and other round-trip details.

## Public API and CLI contract

### Python API

```python
from csv_trans import translate

translate(file, source_lang, target_lang, sep=",")
```

The function always advertises a `None` return. On several read and save
failures it prints a message and returns normally, so a caller cannot reliably
distinguish success, partial success, or failure. It does not report the output
path, failed cells, encoding fallback, row count, or provider.

### Installed CLI

```text
-f  / --file_path
-fs / --file_separator      default: ,
-sl / --source_language
-tl / --target_language
```

The README instead documents `--file` and `--sep`. The unused
`translate.main()` defines a third spelling with hyphens such as `--file-path`.

An empirical invocation with a missing file and invalid languages printed
three errors and exited with status 0. The installed CLI never reaches the only
language-validation code in the repository.

### Provider identity mismatch

The README describes the Google Translate API and links to Google Cloud's
language list. The package actually:

- Uses `deep_translator.GoogleTranslator` to scrape/call a free Google web
  translation endpoint.
- Installs `googletrans` only to obtain a different `LANGUAGES` dictionary in
  the unused `translate.main()` function.
- Does not use Google Cloud Translation or accept Google Cloud credentials.

This distinction matters for supported languages, reliability, quotas,
privacy, terms, and the planned API work.

## Confirmed defects

### P0: provider failures corrupt row alignment

`translate_text()` appends the original cell in its `TranslationNotFound` and
`Timeout` handlers, then unconditionally appends the translation variable a
second time.

Verified behavior:

```text
input:  ["a", "failed", "c"]
output: ["<a>", "failed", "", "<c>"]
```

A single failed cell therefore changes one column's length. Pandas aligns that
column with unchanged columns, shifting records and introducing missing values.
This is silent data corruption, not only an error-reporting problem.

Required invariant: every input cell must produce exactly one output cell,
including every failure path.

### P0: long-text chunking deletes content

The split function assigns `start = end + 1` after every chunk. At a normal
word boundary it discards the separating space. If no space exists within the
ten-character search window it discards a non-space character.

Verified examples:

```text
source:  abcdefghijklmno
chunks:  [abcdefghij, lmno]
missing: k

source:  abcdefghij klmnop
joined:  abcdefghijklmnop
missing: separating space
```

It also ignores non-space whitespace, accepts invalid chunk sizes, loses
translation context, and joins translated chunks without restoring boundaries.

### P0: GitHub issue #14, Windows spawn loop

[Issue #14](https://github.com/ML-Dev-Hub/csv_trans/issues/14) reports an
endless loop and the standard Windows multiprocessing bootstrap error when the
library is called at module top level.

Root cause:

- `translate_dataframe()` uses `multiprocessing.Pool` despite comments calling
  it a thread pool.
- Windows starts workers with `spawn`; a worker re-imports the calling main
  module.
- A user's top-level call runs again during that import and attempts to create
  another pool before bootstrap has completed.

Adding `if __name__ == "__main__"` to every caller is an unsuitable library
requirement. The package should not create process workers for network I/O.

Resolution acceptance criteria:

- Translation works from imported modules, notebooks, tests, a CLI, and a
  future server without caller-specific multiprocessing guards.
- Windows CI executes a subprocess regression reproducing the original usage.
- Normal provider tests run without child processes.

### P0: GitHub issue #15, worker exception deserialization

[Issue #15](https://github.com/ML-Dev-Hub/csv_trans/issues/15) reports this on
Windows 11 and Python 3.12:

```text
TypeError: NotValidPayload.__init__() missing 1 required positional argument: 'val'
```

The root-cause chain is concrete:

1. All string columns are translated, including identifier-like values.
2. Pinned deep-translator rejects digit-only strings with `NotValidPayload`.
3. `csv_trans` does not catch or normalize that exception.
4. The worker process serializes it back to the parent.
5. The upstream exception stores no positional exception arguments even though
   its constructor requires `val`.
6. Deserialization calls the constructor without `val`, causing the reported
   `TypeError` inside the pool's result-handler thread.

A local pickle round trip of the installed `NotValidPayload("x")` reproduces
the same `TypeError` without a network request.

Resolution acceptance criteria:

- Numeric identifiers are not submitted as translation payloads by default.
- Provider exceptions are normalized inside the provider adapter and never
  cross a process boundary.
- A failed cell follows the chosen policy without changing shape or order.
- Windows CLI and Python API regression tests cover invalid payloads.

### P1: one-column files crash

The workflow always accesses `data.columns[1]`. A nonempty one-column CSV raises
`IndexError` before translation.

### P1: header and value behavior disagree

For a three-column CSV, only the second header is changed to the target language
while string values in all three columns are translated. The package needs an
explicit column-selection contract and a separate header-translation option.

### P1: requested input delimiter is not used for output

`read_csv_file()` receives the separator, but `save_csv_file()` does not. A
semicolon or tab input becomes comma-separated output.

### P1: DataFrame index is reset

`translate_dataframe()` rebuilds each result using a new Series without the
source index. Custom indexes become `0..n-1`.

### P1: duplicate headers corrupt shape and values

With duplicate labels, `df[column]` returns a DataFrame rather than a Series.
`translate_text()` then iterates column labels instead of cells. A verified
three-row/two-column input became a two-row/two-column output.

### P1: the configured timeout does not reach HTTP

`timeout=10` is passed to the deep-translator constructor. In pinned 1.10.1,
arbitrary constructor keywords become URL query parameters. Its `requests.get`
call has no `timeout` keyword. A local patched-HTTP probe confirmed `timeout`
appears in request parameters but not in the HTTP client's options.

Requests can therefore hang indefinitely, and the timeout handler does not
provide the stated guarantee.

### P1: failures frequently look successful

- Detection, reading, and saving catch broad exceptions, print text, and return.
- The CLI does not map those failures to nonzero status codes.
- Only two provider exception types are handled.
- Rate limits, connection failures, unsupported languages, HTTP/server errors,
  malformed responses, and invalid payloads can abort the operation.
- No structured partial-failure report exists.

### P1: global warnings are suppressed

Importing `csv_trans` installs a process-wide `warnings.filterwarnings("ignore")`.
This can hide warnings from the host application and every other dependency.

### P2: operational limitations

- One provider object is created per translated cell or chunk.
- The random delay is 10-100 microseconds and provides no useful throttling.
- There is no batching, connection reuse, deduplication, cache, retry/backoff,
  checkpoint, resume, cancellation, or rate-limit coordination.
- Output writes are not atomic.
- Output paths and overwrite policy are not configurable.
- Raw target input is incorporated into a path without sanitization.
- Empty/header-only files are treated as unreadable.

## Dependency analysis

### Declared and resolved footprint

The package declares these 19 mandatory requirements:

```text
click, beautifulsoup4, certifi, chardet, charset-normalizer, colorama,
deep-translator==1.10.1, googletrans, idna, numpy, pandas, pyarrow,
python-dateutil, pytz, requests, six, soupsieve, tqdm, urllib3
```

On Windows/Python 3.12, a clean install resolved to 29 production
distributions including `csv-trans`. `numpy`, `pandas`, and `pyarrow` alone
downloaded about 50.1 MB of compressed wheels. The observed installed
`site-packages` tree was 233.6 MB including 10.8 MB of pip.

### What the code actually needs today

| Requirement | Current use | Recommendation |
|---|---|---|
| `deep-translator` | Actual web translation provider | Adapter/optional extra |
| `googletrans` | Language dictionary in unused function | Remove |
| `pandas` | In-memory representation and CSV I/O | Replace with stdlib streaming core |
| `pyarrow` | Only because the engine is forced | Remove immediately |
| `chardet` | Guesses from a 200-byte sample | Optional detection; prefer explicit encoding |
| `tqdm` | One progress tick for whole operation | Callback or optional UI extra |
| `requests` | Only catches one provider timeout class | Normalize errors inside adapter |
| `click` | Never imported | Remove |
| Remaining 11 | Transitive implementation details | Do not declare directly |

`googletrans` alone adds the async/HTTP2 stack `httpx`, `httpcore`, `anyio`,
`h11`, `h2`, `hpack`, and `hyperframe`, even though the installed CLI bypasses
the only function that references `googletrans`.

### Compatibility metadata is inaccurate

`setup.py` advertises Python `>=3.6`, but pinned deep-translator 1.10.1 requires
Python `>=3.7`. Current unconstrained dependency releases have higher minimums,
causing pip to select different, untested old stacks on old Python versions.

As of this audit, supported upstream Python branches are centered on 3.11-3.14.
The recommended next-release matrix is Python 3.11 through 3.14. Python 3.10
support should be retained only if users require it and it receives explicit CI
and constraints testing.

### Dependency provenance advisory

An OSV scan flags pinned deep-translator 1.10.1 under
[PYSEC-2022-252](https://osv.dev/vulnerability/PYSEC-2022-252). This requires
careful interpretation:

- The PyPA source advisory explicitly lists malicious version 1.8.5 after a
  maintainer account compromise.
- Its ecosystem range has an introduction but no fixed event, so OSV expands
  the affected list to later versions including 1.10.1 and 1.11.4.

This is not evidence that the installed 1.10.1 code is itself malicious. It is
a real supply-chain/provenance and scanner-policy issue that must be reviewed if
deep-translator is retained. A provider abstraction limits future replacement
cost and allows official keyed providers for sensitive use cases.

## Packaging, CI, and maintenance findings

- No `pyproject.toml`, test configuration, or modern build declaration exists.
- The long description is duplicated inside `setup.py` rather than reading the
  README and has already diverged from it.
- Metadata uses stale project URLs and only a generic Python 3 classifier.
- Version 1.1.4 is maintained manually and is not exposed at runtime.
- No changelog, deprecation policy, `SECURITY.md`, or support policy exists.
- There is no active GitHub Actions workflow.
- The deleted workflow referenced a nonexistent `environment.yml`, only used
  Linux/Python 3.10, and would have discovered no tests.
- There are no format, lint, type, coverage, build, wheel-install, vulnerability,
  SBOM, or license gates.
- Release artifacts are not built through PyPI Trusted Publishing.

## Privacy and API-readiness risks

Today, all inferred string cells are sent to an unofficial remote web endpoint.
The package does not disclose that clearly or let a caller select fields. This
is unsuitable for confidential/customer data without an explicit provider and
privacy decision.

A future HTTP API must not wrap the current function directly. The current
function is blocking, loads an entire file, creates child processes, has no
request budget, has no cancellation, writes unsanitized output names, and
cannot report partial failures.

API readiness should include:

- Maximum upload bytes, rows, columns, and per-cell length.
- Explicit accepted encodings and delimiters.
- Authentication, quotas, rate limits, and provider cost controls.
- Synthetic request IDs and structured logs that never contain cell text.
- Temporary-file isolation, sanitized names, atomic writes, and retention rules.
- Job/cancellation semantics for files too large for a synchronous request.
- A stable result schema and downloadable artifact lifecycle.
- Provider credentials kept server-side and provider-specific extras isolated.

If "API" means official translation-provider support rather than an HTTP
server, the same provider boundary still solves the problem. If it means both,
the provider work should come first.

## Recommended target architecture

```text
                       +------------------+
CLI ----------------->|                  |
Python API ---------->| Translation      |----> structured result/errors
Future HTTP API ----->| service          |
                       +--------+---------+
                                |
                  +-------------+-------------+
                  |                           |
          streaming CSV I/O           Translator protocol
          dialect/encoding             translate_batch()
          atomic output                supported_languages()
                                              |
                         +--------------------+--------------------+
                         |                    |                    |
                  free web adapter     official cloud API    fake test provider
                  optional extra       optional extra         no network
```

Suggested internal boundaries:

- `models.py`: immutable options, result, warning, and cell-failure records.
- `csvio.py`: streaming reads/writes, dialect, encoding, and atomic replacement.
- `chunking.py`: lossless provider-limit handling.
- `core.py`: orchestration, selection, batching, order preservation, and policy.
- `providers/base.py`: provider protocol and normalized exceptions.
- `providers/deep_translator.py`: lazily imported compatibility provider.
- `cli.py`: arguments, presentation, and exit-code mapping only.
- A later `api/` package: optional server wiring only, never core logic.

### Core behavioral contract

The new core should guarantee:

- Row count, column count, order, and selected-field identity never change.
- Columns are selected explicitly by name or index.
- Header translation is a separate opt-in option.
- Nonselected cells are preserved as strings without pandas inference.
- Each failed cell follows one documented policy and produces one result cell.
- Provider clients are reused and batches preserve input order.
- Retries are bounded, backoff-aware, and do not retry permanent errors.
- Output is atomic and overwrite behavior is explicit.
- Normal tests are offline; live provider tests are opt-in and synthetic.

## Dependency-reduction options

### Option A: low-risk 1.x cleanup

Preserve the public wrapper and pandas implementation temporarily:

- Remove `click`, `googletrans`, and every explicitly declared transitive.
- Remove the forced PyArrow engine and `pyarrow` requirement.
- Validate languages through the actual provider.
- Keep only genuinely direct dependencies with compatible bounds.

This is the smallest release change, but pandas/numpy remain the majority of the
installation and CSV round-trip behavior remains lossy.

### Option B: recommended lean core

- Use the standard-library `csv` module with streaming rows.
- Default to UTF-8/UTF-8-SIG and accept an explicit encoding; make heuristic
  detection optional.
- Replace tqdm with a progress callback that the CLI may render.
- Put provider packages behind extras and lazy imports.

The CSV/core package can then have zero mandatory third-party dependencies. A
compatibility installation can include one free provider extra. A future server
stack must live in a separate `[server]` extra rather than the base package.

## Phased implementation plan

### Phase 0: decide the product contract — completed

The compatibility, provider, privacy, recovery, column-selection, header,
versioning, and local-model decisions are now accepted in
[PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md).

### Phase 1: safety baseline and release engineering

The local characterization suite created by this audit is the starting point.
Next:

- Add Python 3.11-3.14 CI on Windows, Linux, and macOS.
- Add deterministic provider doubles and subprocess CLI tests.
- Add build/sdist/wheel installation smoke tests.
- Introduce declarative `pyproject.toml`, correct URLs, and a development extra.
- Fix Dependabot and add lint, type, and advisory gates with documented
  exceptions for disputed/overbroad advisories.

Acceptance: every supported interpreter/OS installs the built wheel and runs
offline tests with no network access.

### Phase 2: resolve P0 defects and GitHub issues

- Remove `multiprocessing.Pool`; begin with sequential correctness or bounded
  thread/batch I/O only after the provider boundary exists.
- Reuse one provider client and normalize all provider exceptions locally.
- Guarantee exactly one output per input on every path.
- Replace chunking with a lossless algorithm and provider-aware limits.
- Preserve numeric identifiers and nonselected cells without provider calls.
- Add Windows regressions for issues #14 and #15.

Acceptance: all current expected-failure tests for those defects become normal
passing regressions; issue reproduction scripts pass on Windows; shape/order
invariants hold under injected timeouts and invalid payloads.

### Phase 3: correct CSV and error semantics

- Add explicit column selection and optional header translation.
- Support one-column, duplicate-header, empty/header-only, and ragged inputs
  under documented policies.
- Preserve the selected delimiter and deliberate CSV dialect settings.
- Add explicit input/output encoding, atomic output, output path, and overwrite
  policy.
- Replace prints with typed exceptions and structured results.
- Map CLI usage, partial failure, input failure, and provider failure to
  documented nonzero exit codes.

Acceptance: no input shape changes, separator/encoding tests pass, failed writes
leave no partial final artifact, and callers can determine success without
parsing stdout.

### Phase 4: remove the heavy data stack

- Migrate orchestration to streaming stdlib CSV rows.
- Make pandas support an optional integration only if users need it.
- Remove PyArrow, pandas, numpy, tqdm, default chardet, googletrans, and all
  direct transitive declarations from the base install.
- Add batching, bounded retry/backoff, deduplication, optional cache/checkpoint,
  progress events, and cancellation hooks.

Acceptance: base installation has zero mandatory third-party dependencies, or
one explicitly chosen provider dependency if compatibility requires it; large
fixtures run with bounded memory.

### Phase 5: provider APIs and optional HTTP service

- Add official provider adapters as optional extras with contract tests.
- Decide whether the free web adapter remains a default or only an extra.
- If an HTTP API is wanted, add a separate server extra and implement upload,
  job/result, limits, auth, retention, and cancellation around the same core.
- Add cost, privacy, secret-handling, and observability documentation.

Acceptance: Python, CLI, and HTTP surfaces return equivalent structured results
for the same fake provider and fixture; base users do not install server or
cloud SDK dependencies.

### Phase 6: compatibility release and issue closure

- Keep a compatibility wrapper for
  `translate(file, source_lang, target_lang, sep=',')` where practical.
- Deprecate ambiguous defaults before removing them, unless a deliberate 2.0
  break is selected.
- Publish a changelog, migration guide, supported-version policy, security
  policy, signed/attested artifacts, and verified dependency inventory.
- Post reproduction, fix, and regression evidence to issues #14 and #15 before
  closing them.

## Local test bed delivered

See `TESTING.md` for cross-platform setup commands.

Current baseline:

```text
21 tests
 9 passing characterization tests
12 expected-failure regression specifications
 0 live translation requests
result: OK (expected failures=12)
```

The passing layer covers current CLI parsing, encoding sampling, CSV reading and
historical output naming, DataFrame validation, basic translation behavior,
all-column processing, short-text behavior, and second-header mutation.

The expected-failure layer covers issues #14 and #15, duplicate headers, index
preservation, one-column input, separator preservation, actual HTTP timeout
propagation, failure alignment, language validation, and both known chunk-loss
paths.

This is a foundation, not the final matrix. The next test expansion should add
UTF-8 BOM, UTF-16, Latin-1, embedded newlines, malformed/ragged rows, leading
zeros, missing-value tokens, atomic write failure, provider rate limits/retries,
packaged-wheel CLI smoke tests, and bounded-memory large fixtures.

## Product decisions received

The maintainer clarified that:

- "API" means LLM translation providers such as OpenAI, Claude, Qwen, and
  DeepSeek, not an immediate hosted CSV REST service.
- Deep-translator should be removed.
- CSV translation responsibilities should be implemented internally with no
  mandatory third-party dependencies.
- A no-key provider should be available by default.
- Partial failures should be reported after bounded internal recovery attempts.
- Confidential data and local models are required use cases.
- Python 3.11-3.14 is an acceptable target.

The resulting provider protocols, privacy profiles, recovery ladder, result
schema, compatibility policy, and final defaults are specified in
[PRODUCT_DIRECTION.md](PRODUCT_DIRECTION.md).

## External references

- Repository: https://github.com/ML-Dev-Hub/csv_trans
- Issue #14: https://github.com/ML-Dev-Hub/csv_trans/issues/14
- Issue #15: https://github.com/ML-Dev-Hub/csv_trans/issues/15
- Published package: https://pypi.org/project/csv-trans/
- Deep-translator: https://pypi.org/project/deep-translator/
- Googletrans disclaimer and metadata: https://pypi.org/project/googletrans/
- Python version status: https://devguide.python.org/versions/
- Dependency advisory: https://osv.dev/vulnerability/PYSEC-2022-252

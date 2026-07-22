# Migrating from csv-trans 1.x to 2.0

Version 2 is a deliberate safety and architecture break. It retains the common
four-argument `translate(...)` call and the `csv_trans` executable alias, but it
does not preserve behaviors that could corrupt rows, expose unintended columns,
or hide provider failures.

## Upgrade in a clean environment

Version 2 requires Python 3.11 or newer and has no mandatory runtime
dependencies:

```bash
python -m venv .venv
python -m pip install --upgrade csv-trans
```

Pip does not remove packages that were requirements of an older release. A new
virtual environment is the simplest way to ensure pandas, PyArrow,
deep-translator, googletrans, and their transitives are no longer present merely
because v1 installed them.

The repository's `LICENSES/` notices described that removed 1.x dependency
stack and have therefore also been removed. This is housekeeping, not a change
to the project's license: csv-trans remains distributed under the MIT License.

## Compatibility summary

| Area | 1.1.4 | 2.0 |
| --- | --- | --- |
| Python | Advertised 3.6+ but dependency-incompatible | Tested on 3.11-3.14 |
| Runtime dependencies | 19 declared; 29 resolved on Python 3.12 | None |
| CSV engine | pandas with forced PyArrow | Streaming standard-library `csv` |
| Translation backend | deep-translator Google scraper | Replaceable provider protocol |
| Default provider | Implicit unofficial Google request | Explicitly documented `google-free` |
| Columns | Every inferred string column | Conservative text-column detection or explicit selection |
| Headers | Renamed only the second header | Preserved unless explicitly requested |
| Failures | Printed/swallowed or row-shifting | Original cell preserved; structured partial result |
| Concurrency | Multiprocessing per column | No process pool |
| Output delimiter | Always comma | Input dialect preserved unless explicitly overridden |
| Return value | `None` | `TranslationResult` |
| CLI | `csv_trans` | `csv-trans` and `csv_trans` |
| Confidential data | No enforceable network policy | `public`, `restricted`, and `local-only` |

## Historical Python call

This still runs:

```python
from csv_trans import translate

result = translate("source.csv", "en", "fr", sep=",")
```

The important difference is the return value. Code that ignored the v1 `None`
return remains valid. New code should inspect the result:

```python
if not result.succeeded:
    result.write_json("source.translation.json")
    raise RuntimeError(
        f"translation ended as {result.status.value}: "
        f"{result.failed_cells} failed cells"
    )
```

Use `translate_csv` for all new integrations:

```python
from csv_trans import TranslationConfig, translate_csv

config = TranslationConfig(
    source_language="en",
    target_language="fr",
    columns=("title", "description"),
    translate_headers=False,
    privacy="restricted",
    allowed_providers=("google-free",),
    overwrite=False,
)

result = translate_csv(
    "source.csv",
    config,
    output_path="source.fr.csv",
)
```

Provider objects implement the protocol exported by `csv_trans.providers` and
are passed through `TranslationConfig(provider=...)`. `provider=None` selects
the built-in `google-free` adapter.

## Column and header behavior

V1 translated values in every column that pandas inferred as strings, including
identifiers, URLs, codes, and names. It then renamed only the second header.

V2 separates both decisions:

- `columns=None` samples rows and selects text-like columns conservatively.
- `columns=("description", 4)` selects exact names or zero-based indexes.
- `translate_headers=False` preserves the schema by default.
- `translate_headers=True` explicitly translates selected headers.
- `result.selected_columns` records every selection decision and reason.

Applications with a known schema should always specify columns. Review the
first v2 result before making automatic selection part of a production job.

## Output and overwrite behavior

V1 always generated `translated_<target>_<input-name>`, silently overwrote an
existing file, and wrote comma-separated output even when another input
separator was supplied.

V2 preserves the detected or configured dialect, writes through a temporary
file, and replaces the destination only after a complete write. Existing output
is rejected unless `overwrite=True`. Supply `output_path` whenever stable
application-controlled naming matters.

Encoding is explicit in `TranslationConfig`. When no input encoding is given,
the standard-library detector handles supported Unicode BOMs and otherwise
requires strict UTF-8; it does not guess arbitrary legacy encodings from a
200-byte sample.

## Provider configuration

### Default no-key provider

The default remains easy to start but is now identified as `google-free`. It is
remote, experimental, undocumented, and unsuitable for confidential data. It
can change or stop working without notice. The CLI also defaults to `public`
privacy and warns before an implicit non-quiet `google-free` run. `--quiet`
suppresses presentation only, not network transfer; use `--dry-run` to inspect
selection without contacting a provider.

### OpenAI-compatible endpoints

Use `openai` for the official service and `openai-compatible` for another
hosted API or a local server exposing the same protocol. Configure a base URL
and model for compatible endpoints; no model runtime is installed or launched
by `csv-trans`.

The CLI also provides `openai`, `qwen`, and `deepseek` names. Only `openai`
defaults to its official public base URL. Every compatible or local alias
requires an explicit base URL, preventing a local-model typo from sending text
to a public service. Qwen and DeepSeek use their matching
`CSV_TRANS_QWEN_*` and `CSV_TRANS_DEEPSEEK_*` variable families.

The local-compatible aliases use these exact environment-variable prefixes;
each family supplies `_BASE_URL`, `_MODEL`, and an optional `_API_KEY`:

| Provider ID | Environment-variable family |
| --- | --- |
| `local` | `CSV_TRANS_LOCAL_*` |
| `ollama` | `CSV_TRANS_OLLAMA_*` |
| `llama.cpp` | `CSV_TRANS_LLAMA_CPP_*` |
| `vllm` | `CSV_TRANS_VLLM_*` |
| `lm-studio` | `CSV_TRANS_LM_STUDIO_*` |
| `localai` | `CSV_TRANS_LOCALAI_*` |

The official `openai` provider ID uses:

```text
CSV_TRANS_OPENAI_API_KEY
CSV_TRANS_OPENAI_BASE_URL
CSV_TRANS_OPENAI_MODEL
```

The generic `openai-compatible` provider ID instead uses the isolated family:

```text
CSV_TRANS_OPENAI_COMPATIBLE_API_KEY
CSV_TRANS_OPENAI_COMPATIBLE_BASE_URL
CSV_TRANS_OPENAI_COMPATIBLE_MODEL
```

If `openai` is deliberately pointed at a non-OpenAI host, its credential must
come from `CSV_TRANS_OPENAI_CUSTOM_API_KEY` or `--api-key-env`. The ambient
`OPENAI_API_KEY` fallback is used only for the exact official OpenAI host and is
never forwarded automatically to a compatible or custom destination.

### Anthropic

Use `anthropic` for the Claude Messages API. Configure:

```text
CSV_TRANS_ANTHROPIC_API_KEY
CSV_TRANS_ANTHROPIC_BASE_URL
CSV_TRANS_ANTHROPIC_MODEL
```

For a non-Anthropic base URL, use `CSV_TRANS_ANTHROPIC_CUSTOM_API_KEY` or
`--api-key-env`. `ANTHROPIC_API_KEY` is a lower-precedence fallback only for the
exact official Anthropic host.

The CLI reads keys only from environment variables. `--api-key-env NAME`
selects a custom variable; v2 deliberately has no `--api-key` option that would
place a secret in shell history or process listings. Credential-bearing
literal headers are likewise rejected by the CLI; Python provider objects can
still receive advanced header configuration in memory.

## Privacy is now an input

Choose a privacy mode before the file is processed:

- `public` permits explicitly configured internet providers and fallbacks.
- `restricted` uses only the explicit provider chain and never changes vendors
  automatically.
- `local-only` permits loopback or approved local endpoints only and never
  falls back to the internet.

Changing privacy mode never silently broadens access. A policy failure is not a
retryable provider failure.

`local-only` verifies the configured destination; it does not make a local
model server trustworthy. Operators must review that server's access controls,
prompt logs, retention, administration interface, network exposure, and model
provenance.

## CSV and temporary-file security boundaries

V2 preserves field values and does not neutralize spreadsheet formulas. Values
or translations beginning with `=`, `+`, `-`, or `@` may execute as formulas
when a CSV is opened by spreadsheet software; CSV quoting is not a mitigation.
Sanitize for the intended consumer after translation when that threat applies.

V2 takes a full plaintext snapshot beside the source by default so sampling and
translation use one stable byte sequence without silently crossing storage
boundaries. Set `snapshot_directory` or `--snapshot-directory` to choose another
protected location. Atomic output/report publication also creates plaintext
staging or rollback files beside their destinations. Normal paths clean them
up, but a crash or forced termination may leave residue. Secure those
directories and include orphaned temporary files in confidential-data retention
procedures.

## Partial results replace silent success

V1 could print an error and exit successfully, or append both an original value
and an empty value after a timeout. V2 enforces one output for every input cell.

After bounded retries, batch splitting, lossless cell splitting, and permitted
fallbacks are exhausted, v2:

1. Preserves the original cell.
2. Continues with unrelated cells when safe.
3. Records a `TranslationFailure` without source text.
4. Returns `RunStatus.PARTIAL` if an output file was produced with failures.
5. Makes the CLI exit nonzero.

Treat a partial output as mixed-language data until its JSON report has been
reviewed.

`RunStatus.FAILED` is reserved in the enum for forward compatibility. Fatal
input, configuration, privacy-preflight, and write errors raise to Python
callers in v2 rather than returning that status. Completed API calls return
`success`, `partial`, `cancelled`, or `dry-run`.

## CLI migration

The historical short options remain:

```bash
csv_trans -f source.csv -sl en -tl fr -fs ","
```

The preferred spelling is now:

```bash
csv-trans -f source.csv -sl en -tl fr
```

Select providers with repeatable or comma-separated `--provider`, configure
OpenAI-compatible endpoints with `--base-url` and `--model`, and select a custom
credential variable with `--api-key-env`. Run `csv-trans --help` for the full
set of column, header, output, report, privacy, and recovery options.

Bare numeric `--columns` values are treated as literal header names. Prefix an
index with `#` (for example, `--columns '#0'`) so a CSV whose header is `0`
remains addressable without ambiguity.

Automation must now treat nonzero partial-result exits as meaningful rather
than assuming an output file is complete. Exit code 0 means success or dry run,
1 means failure/cancellation/runtime error, and 2 means a partial output (or an
`argparse` syntax error before a run starts).

## Removed implementation imports

Anything imported from `csv_trans.utils`, pandas-backed helper functions, or
deep-translator internals was never part of the documented public API and is not
preserved. Supported public types are exported from `csv_trans`, and provider
types are exported from `csv_trans.providers`.

## No REST server in 2.0

"API provider" means an outbound translation provider. Version 2.0 does not
listen for HTTP requests or expose a CSV upload service. A future server can use
the same `translate_csv` service without adding a web framework to the base
package.

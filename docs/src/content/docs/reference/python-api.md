---
title: Python API
description: Entry points, TranslationConfig, TranslationResult, and the exception hierarchy for csv-trans.
---

The complete Python reference. `csv_trans` exposes two entry points, a typed
[`TranslationConfig`](#translationconfig), a content-free
[`TranslationResult`](#translationresult), and a small
[exception hierarchy](#exceptions). Everything below is importable from the
top-level `csv_trans` package unless noted.

## Entry points

Use [`translate_csv`](#translate_csv) when you hold a typed `TranslationConfig`;
use [`translate`](#translate) for the ergonomic string-language form. Both return
a [`TranslationResult`](#translationresult) — check
[`succeeded`](#properties-and-methods) or inspect [`status`](#runstatus).

### `translate_csv`

```python
def translate_csv(
    input_path: str | Path,
    config: TranslationConfig,
    *,
    output_path: str | Path | None = None,
) -> TranslationResult
```

The single typed engine entry point. Samples the input for column selection,
processes it in bounded row groups, and publishes the output atomically after the
final row is written. Failed cells retain their complete original value and appear
in `failures`.

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `input_path` | `str \| Path` | — | Path to the input CSV. |
| `config` | `TranslationConfig` | — | Fully-typed configuration. A non-`TranslationConfig` raises `TypeError`. |
| `output_path` | `str \| Path \| None` | `None` | Output CSV path. When `None`, defaults to `translated_<target>_<name>` beside the input (`<target>` is sanitized to filesystem-safe characters). |

Raises on fatal input, configuration, privacy-preflight, and write errors — e.g.
[`CsvInputError`](#input-output-and-configuration-errors),
[`OutputExistsError`](#input-output-and-configuration-errors),
[`PrivacyViolation`](#privacyviolation).

```python
from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import EchoProvider

config = TranslationConfig(
    source_language="en",
    target_language="fr",
    provider=EchoProvider(),
)
result = translate_csv("catalog.csv", config, output_path="catalog.fr.csv")
print(result.status.value, result.output_path)
```

### `translate`

```python
def translate(
    input_path: str | Path,
    source_language: str,
    target_language: str,
    sep: str | None = None,
    *,
    output_path: str | Path | None = None,
    **options: Any,
) -> TranslationResult
```

An ergonomic wrapper. It builds a `TranslationConfig` from `source_language`,
`target_language`, and any keyword `options` — **every** `TranslationConfig` field
is accepted — then delegates to `translate_csv`.

| Parameter | Type | Default | Description |
| --- | --- | --- | --- |
| `input_path` | `str \| Path` | — | Path to the input CSV. 1.x alias: `file=`. |
| `source_language` | `str` | — | Source language code/name, or `"auto"`. 1.x alias: `source_lang=`. |
| `target_language` | `str` | — | Target language code/name. 1.x alias: `target_lang=`. |
| `sep` | `str \| None` | `None` | 1.x delimiter alias, forwarded to `delimiter=`. When omitted, the dialect detector runs. |
| `output_path` | `str \| Path \| None` | `None` | Output CSV path (same default as above). |
| `**options` | — | — | Any `TranslationConfig` field, e.g. `provider=`, `columns=`, `privacy=`, `overwrite=`. |

```python
from csv_trans import translate
from csv_trans.providers import EchoProvider

result = translate(
    "catalog.csv", "en", "fr",
    provider=EchoProvider(),
    columns=("title", "description"),
    privacy="public",
)
```

:::caution
`options` are `TranslationConfig` field names. `provider=` takes a provider
**object** (e.g. `EchoProvider()`), not a string. The v2 delimiter option is
`delimiter=` (one character); `sep=` is accepted as a 1.x alias and forwarded to
`delimiter=`. An unknown keyword raises `TypeError`.
:::

## TranslationConfig

The typed configuration passed to [`translate_csv`](#translate_csv). It is a
dataclass; `source_language` and `target_language` are required and everything
else has a default. Values are validated in `__post_init__`, so an invalid
configuration raises `ValueError` (or `TypeError`) at construction.

```python
from csv_trans import TranslationConfig
from csv_trans.providers import EchoProvider

config = TranslationConfig(
    source_language="en",
    target_language="fr",
    provider=EchoProvider(),
    columns=("title", "description"),
    privacy="restricted",
    allowed_providers=("echo",),
)
```

### Languages and provider

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `source_language` | `str` | required | Source language code/name. `"auto"`, `"detect"`, or `"automatic"` request auto-detection (sent as no source). Stripped; must be non-empty. |
| `target_language` | `str` | required | Target language code/name. Stripped; must be non-empty. |
| `provider` | provider object `\| None` | `None` | Primary provider. `None` uses the experimental `GoogleFreeProvider`. |
| `fallback_providers` | sequence of provider objects | `()` | Providers tried, in order, only after bounded recovery on the primary fails and privacy permits. A bare `str`/`bytes` is rejected. |

### Selection and structure

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `columns` | `Sequence[str \| int] \| None` | `None` | Explicit column names or zero-based indexes; `None` = automatic selection. Booleans and empty names are rejected. |
| `translate_headers` | `bool` | `False` | Translate the selected columns' header cells too. |
| `encoding` | `str \| None` | `None` | Input encoding. `None`/`"auto"`/`"detect"`/empty = detect BOM or strict UTF-8. Unknown codecs rejected. |
| `output_encoding` | `str` | `"utf-8"` | Output codec (normalized via `codecs.lookup`). Unknown codecs rejected. |
| `delimiter` | `str \| None` | `None` | One-character field delimiter; `None` auto-detects. Must be a single non-newline, non-NUL character. |
| `overwrite` | `bool` | `False` | Allow replacing an existing output/report. |

### Privacy

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `privacy` | `PrivacyMode \| str` | `"public"` | Network boundary: `"public"`, `"restricted"`, or `"local-only"`. A string is coerced to `PrivacyMode`. |
| `allowed_providers` | `Sequence[str]` | `()` | Provider names permitted under `restricted`. Non-empty strings. Under `privacy="restricted"` an empty allowlist fails the run-time preflight with `PrivacyViolation`.  |
| `approved_local_hosts` | `Sequence[str]` | `()` | Exact non-loopback hosts approved under `local-only`. Non-empty strings. |

See [Privacy and security](/csv_trans/privacy-and-security/) for behavior.

### Sampling, batching, and limits

All fields in this section must be **positive integers** (≥ 1).

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `sample_rows` | `int` | `100` | Rows sampled for automatic column selection. |
| `batch_size` | `int` | `20` | Max items per provider request; also bounds row groups by selected-cell count. |
| `max_chars` | `int` | `3500` | Max characters per translatable segment before lossless chunking. |
| `min_adaptive_chars` | `int` | `32` | Floor for adaptive splitting of a context-limited singleton. |
| `max_field_chars` | `int` | `67108864` (64 MiB) | Reject any single CSV field larger than this. |
| `max_row_chars` | `int` | `134217728` (128 MiB) | Reject any row whose fields sum beyond this. |
| `max_columns` | `int` | `10000` | Reject any row with more columns than this. |
| `max_sample_chars` | `int` | `16777216` (16 MiB) | Cap on characters buffered during selection sampling. |
| `max_pending_chars` | `int` | `67108864` (64 MiB) | Character budget that flushes a pending row group. |

### Recovery and caching

| Field | Type | Default | Rule | Description |
| --- | --- | --- | --- | --- |
| `max_failure_details` | `int` | `10000` | ≥ 0 | Max stored failure records; the rest count in `omitted_failure_count`. |
| `max_retries` | `int` | `2` | ≥ 0 | Transient-error retries per provider. |
| `malformed_retries` | `int` | `1` | ≥ 0 | Separate corrective-retry budget for invalid model output. |
| `backoff_base` | `float` | `0.5` | ≥ 0, finite | Base seconds for exponential backoff. |
| `max_backoff` | `float` | `8.0` | ≥ 0, finite | Cap on backoff delay. |
| `jitter` | `float` | `0.1` | ≥ 0, finite | Random jitter added to each backoff delay. |
| `cache_size` | `int` | `2048` | ≥ 0 | LRU capacity for `(source, target, segment)` translations. `0` disables caching. |

### Behavior and hooks

| Field | Type | Default | Description |
| --- | --- | --- | --- |
| `preserve_placeholders` | `bool` | `True` | Protect URLs, tokens, formats, tags, and boundary whitespace as local segments. |
| `allow_empty_translations` | `bool` | `False` | Accept an empty provider result for non-empty source text instead of rejecting it. |
| `report_path` | `str \| Path \| None` | `None` | Write the structured JSON result here. Must differ from input and output paths, must not be a symlink, and must not exist unless `overwrite=True`. |
| `snapshot_directory` | `str \| Path \| None` | `None` | Directory for the transient plaintext source snapshot. `None` = beside the input. |
| `dry_run` | `bool` | `False` | Inspect selection and counts without contacting a provider or writing a CSV. |
| `progress_callback` | `Callable[[ProgressEvent], None] \| None` | `None` | Called with content-free `ProgressEvent`s during translation. A raising callback is caught and recorded as a warning. |
| `cancellation_check` | `Callable[[], bool] \| None` | `None` | Polled at safe points; returning `True` cancels the run without publishing output. |

### `ProgressEvent`

The object passed to `progress_callback` (frozen dataclass):

| Field | Type | Description |
| --- | --- | --- |
| `phase` | `str` | `"translating"` or `"complete"`. |
| `rows_processed` | `int` | Data rows processed so far. |
| `cells_translated` | `int` | Cells fully translated so far. |
| `cells_failed` | `int` | Cells preserved after failure so far. |

```python
from csv_trans import TranslationConfig, ProgressEvent

def on_progress(event: ProgressEvent) -> None:
    print(event.phase, event.rows_processed, event.cells_translated)

config = TranslationConfig("en", "fr", progress_callback=on_progress)
```

## TranslationResult

Every run returns a `TranslationResult` — a durable, content-free record.

```python
result = translate_csv("catalog.csv", config)

if result.succeeded:
    print("done:", result.output_path)
else:
    print(result.status.value, "failures:", result.failed_cells)
    result.write_json("catalog.translation.json")
```

### Identity and status fields

| Field | Type | Description |
| --- | --- | --- |
| `input_path` | `Path` | Resolved source path. |
| `output_path` | `Path \| None` | Output CSV path; `None` for a dry run or a cancelled run. |
| `source_language` | `str` | As configured. |
| `target_language` | `str` | As configured. |
| `privacy` | `PrivacyMode` | Effective privacy mode. |
| `status` | `RunStatus` | Final state (see [`RunStatus`](#runstatus)). |
| `input_encoding` | `str` | Detected/selected input encoding. |
| `output_encoding` | `str` | Output codec used. |
| `dialect` | `dict` | Detected CSV dialect (delimiter, quotechar, quoting, line terminator, …). |

### Count fields

| Field | Type | Description |
| --- | --- | --- |
| `row_count` | `int` | Data rows processed (excludes the header). |
| `total_cells` | `int` | Fields processed; header fields count only when `translate_headers=True`. |
| `selected_cells` | `int` | Fields in selected columns, including blank ones. |
| `translated_cells` | `int` | Fields whose translation fully succeeded. |
| `cached_cells` | `int` | Subset of translated cells completed entirely via dedup/cache. |
| `skipped_cells` | `int` | Unselected or safely bypassed fields (blank, machine-like, identical languages, no translatable segment). |
| `failed_cells` | `int` | Fields preserved with their original value after failing. |
| `omitted_failure_count` | `int` | Failures beyond `max_failure_details` that were counted but not stored. |
| `retries` | `int` | Total provider retries across the run. |
| `fallbacks` | `int` | Number of times work moved to a fallback provider. |

### Detail fields

| Field | Type | Description |
| --- | --- | --- |
| `selected_columns` | `list[ColumnSelection]` | One entry per column with its selection decision and reason. |
| `failures` | `list[TranslationFailure]` | One entry per preserved cell failure (capped by `max_failure_details`). |
| `provider_attempts` | `list[ProviderAttempt]` | Per-provider telemetry (batches, items, retries, failures, sanitized endpoints). |
| `warnings` | `list[str]` | Non-fatal advisories (e.g. identical languages, no columns selected, durability notes). |
| `report_path` | `Path \| None` | Where a report was published, if any. |

### Properties and methods

```python
@property
def succeeded(self) -> bool
```

`True` when `status` is `success` or `dry-run` — i.e. the run completed without a
final cell failure.

```python
def to_dict(self, *, include_column_names: bool = False) -> dict
```

Returns a JSON-ready dict. **Content-free by default**: header names and
per-failure `column_name` are set to `null` unless `include_column_names=True`.
Paths, status, and privacy are stringified; provider endpoints are lists.

```python
def write_json(
    self,
    path: str | Path,
    *,
    overwrite: bool = False,
    include_column_names: bool = False,
) -> Path
```

Writes the result atomically as UTF-8 JSON and returns the destination path. It
refuses to overwrite an existing file (or a symlink) unless `overwrite=True`, and
updates `self.report_path` on success. See
[How it works](/csv_trans/how-it-works/).

### `RunStatus`

A string enum. `succeeded` is `True` for `SUCCESS` and `DRY_RUN`.

| Value | Meaning |
| --- | --- |
| `success` | Every selected cell translated. |
| `partial` | One or more cells preserved after failure; output still written. |
| `failed` | Reserved for forward compatibility; **not produced by v2** (fatal errors raise instead). |
| `cancelled` | `cancellation_check` stopped the run; no output published. |
| `dry-run` | Selection/counts only; no provider contacted, no CSV written. |

### `PrivacyMode`

String enum: `public`, `restricted`, `local-only`. See
[Privacy and security](/csv_trans/privacy-and-security/).

### `ColumnSelection`

| Field | Type | Description |
| --- | --- | --- |
| `index` | `int` | Zero-based column index. |
| `name` | `str` | Header name (nulled in serialized reports by default). |
| `selected` | `bool` | Whether the column was translated. |
| `reason` | `str` | Why (e.g. `text-like values`, `numeric-like values`, `explicitly selected`). |

### `TranslationFailure`

| Field | Type | Description |
| --- | --- | --- |
| `row` | `int` | Data-row number of the failed cell. |
| `column_index` | `int` | Zero-based column index. |
| `column_name` | `str` | Header name (nulled in serialized reports by default). |
| `item_id` | `str` | Internal stable cell ID (e.g. `r3c1`). |
| `category` | `str` | Error category (e.g. `timeout`, `invalid_response`, `output_encoding`). |
| `provider` | `str` | Provider that produced the final failure. |
| `endpoint` | `str \| None` | Sanitized recipient endpoint. |
| `attempts` | `int` | Total attempts across recovery. |
| `message` | `str` | Engine-derived safe message (never provider raw text). |
| `original_preserved` | `bool` | Always `True` — the source value is kept. |

### `ProviderAttempt`

| Field | Type | Description |
| --- | --- | --- |
| `provider` | `str` | Provider name. |
| `chain_index` | `int` | Position in the provider chain (0 = primary). |
| `endpoint` | `str \| None` | First sanitized endpoint. |
| `endpoints` | `tuple[str, ...]` | All sanitized endpoints observed. |
| `batches` | `int` | Provider requests made. |
| `items` | `int` | Items submitted across those requests. |
| `retries` | `int` | Retries within this provider. |
| `failures` | `int` | Failed requests within this provider. |

## Exceptions

`csv-trans` raises fatal input, configuration, privacy, and write errors to the
caller; returned results are only `success`, `partial`, `cancelled`, or
`dry-run`. Provider adapters normalize transport-, HTTP-, and response-level
failures into a small provider-independent hierarchy so recovery can make
retry/split/fallback decisions without depending on a provider SDK.

### `PrivacyViolation`

```python
from csv_trans import PrivacyViolation   # subclass of ValueError
```

Raised during preflight (and re-validation before each provider call) when a
configured provider would cross the selected network boundary — for example a
remote endpoint under `local-only`, a `restricted` run without an allowlist, or a
provider not on the allowlist. See
[Privacy and security](/csv_trans/privacy-and-security/).

### Input, output, and configuration errors

These come from the CSV and config layers and inherit from standard base classes,
so existing `except ValueError` / `except FileExistsError` handlers keep working:

| Exception | Base | Raised when |
| --- | --- | --- |
| `csv_trans.csvio.CsvInputError` | `ValueError` | Input cannot be decoded/interpreted as CSV, or it changed during the run. |
| `csv_trans.csvio.OutputExistsError` | `FileExistsError` | Output/report collision rejected by policy (no `overwrite`). |
| `ValueError` / `TypeError` | — | Invalid `TranslationConfig` fields, or a non-`TranslationConfig` passed to `translate_csv`. |

### The `ProviderError` hierarchy

All provider exceptions live in `csv_trans.exceptions` (and are re-exported from
`csv_trans.providers`). The base carries safe, log-friendly metadata — never a
response body, which could echo source text or credentials.

```python
class ProviderError(RuntimeError):
    provider: str            # provider id/name
    category: ErrorCategory  # stable category
    retryable: bool          # engine retry hint
    status_code: int | None  # HTTP status when applicable
```

| Exception | Category | Retryable | Default status | Meaning |
| --- | --- | --- | --- | --- |
| `ProviderConfigurationError` | `configuration` | no | — | Invalid/missing provider configuration. |
| `ProviderAuthenticationError` | `authentication` | no | — | Auth/authorization failed (HTTP 401/403). |
| `ProviderRateLimitError` | `rate_limit` | yes | `429` | Quota exceeded. |
| `ProviderContextLimitError` | `context_limit` | no | — | Request exceeded a context/payload limit → drives adaptive split. |
| `ProviderTimeoutError` | `timeout` | yes | — | Request timed out. |
| `ProviderConnectionError` | `connection` | yes | — | Could not connect to the endpoint. |
| `ProviderRequestError` | `invalid_request` | no | — | Semantically invalid request rejected. |
| `ProviderResponseError` | `invalid_response` | no | — | Malformed/contract-breaking output → corrective retry then split. |
| `ProviderServerError` | `server` | yes | — | Provider internal server failure (HTTP 5xx). |
| `ProviderUnavailableError` | `unavailable` | yes | — | Endpoint temporarily unavailable (HTTP 502/503/504). |

### `ErrorCategory`

A `StrEnum` of stable categories used across providers and reports:
`configuration`, `authentication`, `rate_limit`, `context_limit`, `timeout`,
`connection`, `invalid_request`, `invalid_response`, `server`, `unavailable`,
`unknown`.

### Raising these from a custom provider

Raise the subclass that matches the failure so recovery classifies it correctly
(see [Providers](/csv_trans/providers/)):

```python
from csv_trans.exceptions import ProviderRateLimitError, ProviderResponseError

# 429 from the upstream service:
raise ProviderRateLimitError("rate limited", provider="my-provider")

# Model returned something that isn't the required JSON contract:
raise ProviderResponseError("not translation JSON", provider="my-provider")
```

Reports record only the engine's category-derived wording, not your message. Do
not put source text or credentials in messages anyway — logs and error reporters
may capture them.

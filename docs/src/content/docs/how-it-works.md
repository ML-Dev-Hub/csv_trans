---
title: How it works
description: The csv-trans pipeline — column selection, placeholder-safe chunking, bounded failure recovery, and atomic two-file publication.
---

`csv-trans` is a streaming engine: it never loads the whole CSV into memory and
never lets a provider touch the file structure. [Providers](/csv_trans/providers/)
translate text items only; the engine owns encoding, dialect, row order, field
count, and output.

## The pipeline

<div class="pipeline not-content">
  <div class="pipeline__phase">
    <div class="pipeline__node">1</div>
    <div class="pipeline__body">
      <div class="pipeline__title">Prepare</div>
      <ul class="pipeline__steps">
        <li>Snapshot &amp; validate config <small>immutable copy, privacy preflight</small></li>
        <li>Detect encoding &amp; dialect</li>
        <li>Select text columns <small>skip numeric, id, secret, URL</small></li>
      </ul>
    </div>
  </div>
  <div class="pipeline__phase">
    <div class="pipeline__node">2</div>
    <div class="pipeline__body">
      <div class="pipeline__title">Protect</div>
      <ul class="pipeline__steps">
        <li>Hold back placeholders &amp; URLs</li>
        <li>Lossless chunking</li>
        <li>Deduplicate &amp; cache</li>
      </ul>
    </div>
  </div>
  <div class="pipeline__phase">
    <div class="pipeline__node">3</div>
    <div class="pipeline__body">
      <div class="pipeline__title">Translate</div>
      <ul class="pipeline__steps">
        <li>Send batches to the provider</li>
        <li>Validate response IDs, count &amp; order</li>
      </ul>
      <div class="pipeline__recover">
        <span class="pipeline__recover-label">On failure, escalate</span>
        <div class="ladder">
          <span>retry</span><span>corrective retry</span><span>split</span><span>adaptive singleton</span><span>provider fallback</span><span class="ladder__end">keep original</span>
        </div>
      </div>
    </div>
  </div>
  <div class="pipeline__phase">
    <div class="pipeline__node">4</div>
    <div class="pipeline__body">
      <div class="pipeline__title">Publish</div>
      <ul class="pipeline__steps">
        <li>Reassemble the cell <small>original preserved on failure</small></li>
        <li>Atomic write + content-free report</li>
      </ul>
    </div>
  </div>
</div>

1. **Configuration and privacy preflight.** The
   [`TranslationConfig`](/csv_trans/reference/python-api/) is validated, then every provider
   in the chain is checked against the selected
   [privacy mode](/csv_trans/privacy-and-security/) before any text is submitted.
   The output collision policy is checked up front so a provider cannot incur
   cost only to fail on a pre-existing output.
2. **Immutable snapshot.** The complete input is copied to a byte-for-byte
   plaintext snapshot (beside the source, or in `snapshot_directory`) and hashed.
   Sampling and translation both read the snapshot, and the source is re-checked
   for change before the output is published, so a file changing mid-run cannot
   mix two versions into one output.
3. **Encoding and dialect inspection.** UTF-8, UTF-8 BOM, UTF-16 BOM, and UTF-32
   BOM are recognized with bounded reads and no third-party detector. A BOM-less
   non-UTF-8 file must declare its encoding explicitly rather than be silently
   mis-decoded. Delimiter, quote character, quoting policy, and line-ending style
   are inferred and preserved.
4. **Column selection.** Explicit `columns` win; otherwise a bounded sample
   infers text-like columns and records a reason for each. See
   [Column selection](#column-selection).
5. **Streaming row groups.** The snapshot is reopened and processed in groups
   bounded by `batch_size` (rows and selected cells) and
   `max_pending_chars`. `max_columns`, `max_row_chars`, and `max_field_chars`
   reject pathological records.
6. **Protection, chunking, deduplication.** Each selected cell is segmented so
   placeholders and URLs stay local and long text splits losslessly (see
   [Placeholder protection](#placeholder-protection--chunking)). Identical
   segments in a group are deduplicated before disclosure, and an in-memory LRU
   cache (`cache_size`) reuses earlier translations. The cache key is
   `(casefolded source language, casefolded target language, exact segment text)`.
7. **Provider protocol with bounded recovery.** Items are sent in batches; a
   response is accepted only when its IDs, item count, types, and order match the
   request exactly. Failures run the [recovery chain](#failure-recovery).
8. **Reassembly and original-on-failure.** A cell is rewritten only after all its
   translatable segments succeed and the result encodes cleanly in the output
   codec. Any final failure leaves the complete original field in place.
9. **Atomic publication.** Output is staged, fsynced, and published only after
   the last row is written; a required report is published first and rolled back
   if the CSV commit fails. See [Atomic output & reports](#atomic-output--reports).

**Guarantee.** For every completed or partial CSV, one input row produces exactly
one output row in the same position with its original field count, including
ragged rows. CSV quoting may be normalized by Python's writer, but decoded field
values, row order, field order, delimiter, quote policy, and line-ending style
are preserved. Inputs are never passed through type inference.

## Column selection

`csv-trans` translates only columns that look like natural-language text. Every
column's decision is recorded in
[`result.selected_columns`](/csv_trans/reference/python-api/) with a reason string.

### Automatic selection

With `columns=None` (the default), the engine samples up to `sample_rows` rows
(capped by `max_sample_chars`) and classifies each column by its header name and
sampled values. A column is **skipped** when any of these hold:

| Signal | Reason string | Examples |
| --- | --- | --- |
| Credential-like header | `credential-like header` | `password`, `secret`, `api_key`, `token`, `client_secret`, `private_key`, `signing_key` |
| Identifier-like header | `identifier-like header` | `id`, `uuid`, `sku`, `code`, `zip`, `postal_code`, plus affixes like `user_id`, `order_uuid` |
| No sampled values | `empty in selection sample` | column blank across the sample |
| ≥80% numeric values | `numeric-like values` | prices, counts, percentages |
| ≥80% machine-like values | `identifier or machine-like values` | URLs, emails, UUIDs, timestamps, codes, opaque tokens |
| No alphabetic content | `no text-like values` | punctuation- or symbol-only columns |

Otherwise the column is **selected** with reason `text-like values`. Short words
count as text — city names and brief labels are not treated as identifiers merely
for being short.

At the value level, the classifier preserves rather than translates:

- **Numeric literals**, including thousands separators in three-digit groups and
  a trailing `%`. `NaN`, `Infinity`, and underscore-grouped literals such as
  `1_000` do not count as *numeric*, but as standalone tokens they are still
  preserved as machine values; only when such a word appears inside
  natural-language text is the cell translated.
- **URLs and emails**, **UUIDs**, and **dates/timestamps** (ISO-like and common
  slash/dash forms, with optional time and timezone).
- **Code-like values** — mixed letters-and-digits tokens such as `A1`, `SKU-42`.
- **Opaque secret-shaped blobs** — a single whitespace-free token ≥20 chars
  containing `+` or `=` and matching the base64/token alphabet.

### Explicit columns

Pass `columns` to override the heuristics entirely. Selectors are **header names**
or **zero-based integer indexes**; each column reports `explicitly selected` or
`not requested`.

```python
from csv_trans import TranslationConfig

TranslationConfig("en", "fr", columns=("title", "description"))  # by name
TranslationConfig("en", "fr", columns=(1, 3))                     # by index
TranslationConfig("en", "fr", columns=("title", 3))              # mixed
```

On the CLI, indexes are written as `#N`:

```bash
csv-trans -f catalog.csv -sl en -tl fr --columns title description
csv-trans -f catalog.csv -sl en -tl fr --columns '#1' '#3'
```

Resolution rules:

- An out-of-range index or unknown name raises `ValueError`.
- A **duplicated** header name is an error — select it by zero-based index.
- Booleans are rejected: `columns=[True]` is not read as "column 1".
- Duplicate selectors are de-duplicated, preserving first-seen order.

### Per-cell safeguards

- **Automatic mode** applies the value-level machine/numeric checks per cell, so a
  stray URL or number inside a text column is preserved.
- **Explicit mode** relaxes this to "translate any non-blank cell" — you asked for
  the column — but blank cells and cells with no translatable segment are still
  skipped.

In both modes a cell is skipped (counted in `skipped_cells`) when source and
target languages are identical, when it is blank, or when placeholder protection
leaves nothing translatable.

Header names are outside the value sample and are **never translated** unless
`translate_headers=True`, and even then only the *selected* columns' headers.

## Placeholder protection & chunking

Before any cell is sent, `csv-trans` segments it so machine-readable constructs
never leave the process and long text splits without dropping or inventing a
character. Only translatable segments are sent; the cell is reassembled from those
translations.

With `preserve_placeholders=True` (the default), these constructs are held back as
non-translatable segments and reinserted **byte-for-byte**:

| Construct | Matches |
| --- | --- |
| URLs | `https://…`, `http://…`, `www.…` |
| Emails | `name@example.com` |
| Double-brace tokens | `{{user}}`, `{{count}}` |
| Shell/JS-style vars | `${HOME}`, `${var}` |
| Single-brace tokens | `{name}`, `{0}` |
| `printf`/percent formats | `%s`, `%d`, `%(name)s`, `%.2f` |
| Tags | `<b>`, `</span>`, `<br/>` |

Percent-mapping keys are length-bounded (`%(...)` up to 64 chars) so adversarial
input cannot trigger quadratic scanning; ordinary keys, including ones with
spaces, are still protected. Leading and trailing whitespace around each chunk is
also protected locally, so a provider cannot silently strip indentation or padding.

Set `preserve_placeholders=False` to translate the raw cell as a single unit; only
do so when no placeholders are present.

### The byte-exact guarantee

```text
Hello {{name}}, see https://example.com/docs for %(count)d updates.
```

Only `Hello `, `, see `, and ` for … updates.` are sent; the `{{name}}`, the URL,
and `%(count)d` are copied verbatim. If every translatable segment were replaced
by an identity provider, the reconstructed string would equal the original
**exactly** — the property the offline echo provider verifies end-to-end. A cell
is only rewritten after *all* its translatable segments succeed and encode cleanly
in the output codec, so a partial failure never yields a half-translated field.

### Lossless chunking

Long cells split so each request stays within `max_chars` (default 3500). The
splitter prefers a whitespace boundary in the final third of each chunk, never
emits an empty chunk, and assigns boundary whitespace to the preceding chunk so
joining reconstructs the source exactly. An all-whitespace chunk is treated as a
single protected segment to avoid duplicating it during reassembly. Chunking runs
*inside* each segment, so placeholders are never split across a boundary.

When a lone item still hits a context-limit error and its text is longer than
`min_adaptive_chars` (default 32), the engine re-segments it with a smaller
limit — half its length, floored at `min_adaptive_chars` — sends the pieces as
separate requests, and reassembles them losslessly (see
[Failure recovery](#failure-recovery)).

## Failure recovery

When a batch fails, `csv-trans` recovers through a fixed, finite sequence — no
unbounded retry loop, no invented fallback. For each unresolved set of items,
against each provider in the chain:

1. **Transient retry.** A classified transient error (timeout, connection, rate
   limit, server, unavailable) retries up to `max_retries` times with capped
   exponential backoff plus jitter (`backoff_base`, `max_backoff`, `jitter`).
2. **Corrective retry.** Invalid structured output (`invalid_response`) gets a
   **separate** budget of `malformed_retries`, using a corrective prompt that
   restates the exact JSON contract.
3. **Recursive split.** A recoverable batch failure (`context_limit`,
   `invalid_response`, or `output_encoding`) with more than one item is split in
   half and each half recovered independently.
4. **Adaptive singleton split.** A lone item that still hits a `context_limit` and
   is longer than `min_adaptive_chars` is re-segmented with a smaller limit and
   its pieces are submitted as separate requests, then reassembled losslessly.
5. **Provider fallback.** Only items still unresolved move to the next provider —
   and only if the privacy policy permits that destination. Each fallback is
   counted in `result.fallbacks`.
6. **Preserve and report.** Any item that still fails keeps its complete original
   field and appears in `result.failures`.

Errors that will not improve are terminal for that provider immediately:
`authentication`, `configuration`, `invalid_request`, and `privacy`/`policy`.
`rate_limit`/quota errors are retried within the transient budget but never
split. This prevents a hard credential or policy failure from being multiplied
across dozens of split sub-requests.

The engine keys decisions on an internal, provider-independent taxonomy:
`authentication`, `configuration`, `rate_limit`, `context_limit`, `timeout`,
`connection`, `transient`, `invalid_request`, `invalid_response`, `server`,
`unavailable`, `privacy`, `policy`, `unsupported_language`, `output_encoding`, and
`unknown`. Adapters raise the subset published as the
[`ErrorCategory`](/csv_trans/reference/python-api/) enum; `transient`, `privacy`, `policy`,
`unsupported_language`, and `output_encoding` arise from the engine's own
classification and internal validation and are **not** part of that public enum.

### Partial results

If any cell is preserved after all recovery, the run's status is
`RunStatus.PARTIAL`, never a silent success. The output CSV is still produced —
mixed-language, with failed cells holding their originals.

```python
result = translate_csv("catalog.csv", config)

if result.status is RunStatus.PARTIAL:
    for failure in result.failures:
        print(
            failure.row,
            failure.column_index,
            failure.column_name,     # in-memory; omitted from JSON by default
            failure.category,
            failure.provider,
            failure.attempts,
            failure.original_preserved,  # True
        )
```

Stored failure records are capped by `max_failure_details`; any beyond that are
counted in `result.omitted_failure_count`.

### Cancellation, status, and exit codes

A `cancellation_check` callable is polled at safe points. If it returns `True`,
the run stops, no output CSV is published, and the status becomes
`RunStatus.CANCELLED`.

`RunStatus.FAILED` is reserved for forward compatibility and is **not** produced
by v2 — fatal input, configuration, privacy-preflight, and write errors are
**raised** to Python callers. Returned results are `success`, `partial`,
`cancelled`, or `dry-run`. The CLI maps these to exit codes (`0` success/dry-run,
`2` partial, `1` fatal/cancelled) so automation cannot treat mixed-language output
as complete; see the [CLI reference](/csv_trans/reference/cli/#exit-codes).

## Atomic output & reports

The output is written to a private staging file beside the destination, flushed
and `fsync`ed, and only then published with a single atomic filesystem operation —
a hard link on POSIX (which refuses to clobber unless `overwrite=True`) or an
atomic rename on Windows. The destination directory entry is flushed for
durability. If anything fails while writing, the staging file is removed and
nothing is published.

Collision policy is checked **before** a provider does any work:

- An existing output is rejected unless `overwrite=True`.
- The output path must not be a symbolic link.
- Replacing the input in place requires `overwrite=True`.

With no `output_path`, the default is `translated_<target>_<name>` beside the
input, where `<name>` is the input filename and `<target>` is a filesystem-safe
form of the target language.

### The report-first transaction

When a report is required, `csv-trans` publishes it **first**, then commits the
CSV, and **rolls the report back** if the CSV commit raises — including restoring a
report that an `overwrite=True` run replaced. A mixed-language CSV is never made
visible without its report.

A report is written when:

- `report_path` (`--report`) is set — always, for any status; or
- a run ends **partial**, which automatically writes a collision-safe
  `<output>.report.json` sidecar (numbered if needed, never replacing either CSV,
  never following a pre-existing sidecar symlink).

`report_path` must differ from both the input and output CSV paths, must not be a
symlink, and must not already exist unless `overwrite=True`.

:::note
No portable filesystem primitive can atomically commit two separate paths. A
process or host crash in the narrow interval between the two commits can still
leave one file visible. Downstream automation should **correlate the report with
its expected output path and status**, not treat report presence alone as proof of
a completed CSV.
:::

### Writing a report from Python

```python
result = translate_csv("catalog.csv", config)

# Content-free by default; atomic UTF-8 JSON write.
path = result.write_json("catalog.translation.json")

# Opt in to header/column names only when your reporting boundary permits it.
result.write_json("catalog.debug.json", include_column_names=True, overwrite=True)

# Or get the dict without writing.
payload = result.to_dict()
```

`write_json(path, *, overwrite=False, include_column_names=False)` writes
atomically and refuses to overwrite an existing file unless `overwrite=True`.
`to_dict(*, include_column_names=False)` returns the same structure in memory.

### What a report contains

A serialized report is **content-free** by design. It includes:

- File paths (input, output, report), status, privacy mode, and encodings.
- The detected CSV dialect.
- Counts: `row_count`, `total_cells`, `selected_cells`, `translated_cells`,
  `cached_cells`, `skipped_cells`, `failed_cells`, `omitted_failure_count`,
  `retries`, `fallbacks`.
- Per-column selection decisions and per-cell failure records — with column and
  header names set to `null` unless `include_column_names=True`.
- Provider telemetry: provider IDs, **sanitized** recipient hosts (scheme/host/
  port only), and batch/item/retry/failure counts.
- Warnings, if any.

It deliberately **omits** source cell text, translated text, credentials, and (by
default) header/column names. Failure messages are the engine's own
category-derived wording, never a provider's raw message — even a `ProviderError`
from third-party code could otherwise carry a source cell or an API key.

:::caution
Redaction covers *content*, not *paths*. File paths remain in the report, so if a
path name is itself sensitive, protect the report accordingly. You also remain
responsible for your process environment and any custom logging.
:::

The input snapshot and atomic staging/rollback files are plaintext and normally
removed, but a crash can leave residue (`.csv-trans-*.snapshot`, `*.tmp`,
`*.rollback`). See
[Plaintext temporary files](/csv_trans/privacy-and-security/#plaintext-temporary-files).

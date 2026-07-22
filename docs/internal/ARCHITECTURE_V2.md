# csv-trans 2.0 architecture

This document describes the implemented v2 runtime. The historical design and
the evidence that motivated the rewrite remain in
[`REPOSITORY_AUDIT.md`](REPOSITORY_AUDIT.md); accepted product decisions remain
in [`PRODUCT_DIRECTION.md`](PRODUCT_DIRECTION.md).

## Runtime boundaries

```text
Python API / CLI
        |
        v
TranslationConfig + privacy preflight
        |
        v
Unicode and CSV inspection ----> automatic/explicit column selection
        |                                      |
        +------------------+-------------------+
                           v
                 bounded streaming row groups
                           |
            placeholder protection + lossless chunking
                           |
                    deduplication + LRU cache
                           |
             retry -> split -> singleton -> fallback
                           |
                           v
                     provider protocol
          +----------------+------------------+
          |                |                  |
     Google free    OpenAI-compatible     Anthropic
                           |
                           v
             exact ID/schema/order validation
                           |
                           v
              reassembly + original-on-failure
                           |
                           v
                atomic CSV + JSON result
```

Providers translate text items only. They never parse a CSV, choose columns,
name an output, retry a cell, or decide whether a privacy boundary may be
crossed.

## Modules

| Module | Responsibility |
| --- | --- |
| `models.py` | Public config, progress, result, attempt, column, and failure data |
| `csvio.py` | Encoding validation, dialect inspection, strict streaming reads, output collision policy, atomic writes |
| `selection.py` | Explicit name/index resolution and conservative text-column inference |
| `chunking.py` | Protected-token segmentation and character-lossless size bounds |
| `core.py` | Row orchestration, stable coordinates, cache/deduplication, recovery, privacy, reporting |
| `exceptions.py` | Provider-independent error taxonomy |
| `providers/base.py` | `TranslationItem`, provider protocol, injectable bounded HTTP transport |
| `providers/*.py` | One network protocol per adapter plus the offline Echo adapter |
| `translate.py` | Historical `translate(file, source, target, sep)` compatibility wrapper |
| `cli.py` | Argument/env mapping, presentation, and exit codes only |

The entire production tree uses the Python standard library. Provider SDKs,
dataframes, process pools, and web frameworks are not runtime requirements.

## Data-integrity invariants

The engine enforces these invariants for every completed or partial CSV:

1. One input row produces exactly one output row in the same position.
2. Every row keeps its original field count, including ragged rows.
3. An unselected field is copied exactly as decoded.
4. A selected field is replaced only after every translatable segment succeeds.
5. Any final segment failure preserves the complete original field.
6. Provider output is associated by an internal row/column/segment ID and is
   never assigned by response position alone.
7. A provider batch is accepted only when IDs, item count, types, and response
   order match exactly.
8. The destination is not published until the complete CSV is encoded and
   flushed successfully.

CSV quoting may be normalized by Python's writer, but decoded field values,
row order, field order, delimiter, quote policy, and line-ending style are
preserved. Inputs are not passed through type inference, so values such as
`001`, `NA`, and date-looking strings remain strings.

## Streaming and memory

Encoding and dialect inspection use bounded reads. Automatic selection buffers
at most `sample_rows` and stops at `max_sample_chars` (plus at most one bounded
row). Translation then reopens the immutable snapshot and processes row groups bounded by
row count, selected-cell count, and `max_pending_chars`. `max_columns`,
`max_row_chars`, and `max_field_chars` reject pathological records. Provider
batches are limited by `batch_size`; individual text segments are limited by
`max_chars`. The in-memory LRU contains at most `cache_size` translations and
is never persisted.

Before inspection, the engine copies the complete input to a byte-for-byte
snapshot beside the source by default, keeping it on the same storage boundary.
`snapshot_directory` can deliberately select another protected directory. This
prevents sampling one file version and translating another. The snapshot and
atomic output/report staging or rollback files are plaintext; normal control
flow deletes them, but abrupt process or host failure can leave residue that
operators must include in their storage and retention policy.

Output and report publication is a best-effort two-file transaction: each file
is individually atomic, the report is published first, and it is removed or a
prior report restored if the CSV commit raises. A process/host crash between
the two independent filesystem commits cannot be rolled back portably, so
consumers must correlate the report with its expected output path and status.

UTF-8, UTF-8 BOM, UTF-16 BOM, and UTF-32 BOM are recognized without a third
party detector. A legacy encoding must be explicit because silently treating
arbitrary bytes as Latin-1 can produce valid but incorrect text.

## Selection and protection

When `columns` is absent, a bounded sample excludes empty, numeric, and
identifier/machine-like columns and records a reason for every decision.
Explicit names or zero-based indexes override those heuristics. A duplicated
header can be selected safely by index; selecting it by ambiguous name is an
error.

Empty cells remain local. In automatic mode, numeric values, URLs, email
addresses, UUIDs, timestamps, and code-like values are not submitted. With
placeholder preservation enabled, URLs, tags, and common template/format
tokens are kept as protected local segments and reinserted byte-for-byte.

Headers are outside the data-selection sample and are never submitted unless
`translate_headers=True`; even then, only selected headers are translated.

## Recovery

Provider work is synchronous and bounded. For each unresolved item set:

1. Retry a classified transient error with capped exponential backoff and
   jitter.
2. Give invalid structured model output its separate corrective retry budget.
3. Split recoverable failed batches recursively.
4. Try remaining items singly; on a context error, adaptively split a singleton
   into smaller separately submitted segments down to `min_adaptive_chars`.
5. Move only unresolved items to an explicitly configured fallback.
6. Preserve and report any item that still fails.

Authentication, configuration, privacy, invalid-request, and rate-limit/quota
errors are not multiplied through recursive splitting. There is no invented
fallback and no unbounded retry loop.

The cache is keyed by source language, target language, and exact segment text.
Repeated values in the same group are deduplicated before disclosure; later
groups can use the bounded in-memory cache.

## Privacy enforcement

Privacy is checked against the complete provider chain before translation text
is submitted, and every declared destination is revalidated immediately before
each provider invocation, including retries, split requests, and fallbacks:

- `public` accepts configured remote providers.
- `restricted` requires an explicit provider allowlist.
- `local-only` validates every endpoint as loopback or an exact approved host,
  without DNS resolution. A provider's self-reported `is_remote` flag cannot
  override a nonlocal URL.

Providers declare every possible recipient endpoint; Google’s optional HTML
fallback is therefore preflighted even when its primary endpoint later works.
HTTP redirects are disabled so a validated endpoint cannot silently move a
request to another host. Ambient environment/system proxies are disabled for
the built-in transport, and non-loopback endpoints require HTTPS unless a
trusted local-network HTTP endpoint is explicitly opted in. An injected
`HttpClient` is contractually required not to follow redirects. HTTP response
bodies are capped at 4 MiB. Provider errors retain classifications and status
codes, but not response bodies. Reports contain paths, coordinates, sanitized
recipient hosts, provider IDs, counters, and safe error messages;
source/translated cell contents, header names by default, and credentials are
intentionally absent.

`local-only` verifies network destination. It cannot make an independently
operated local model trustworthy; deployment, access control, logs, model
retention, and host security remain the operator's responsibility.

Custom providers and injected transports are trusted extension code, not an
operating-system egress sandbox. They can violate their declared recipients or
the no-redirect contract. Endpointless custom providers are rejected in
`local-only` even when they report `is_remote=False`; the sole endpointless
exception is the exact built-in `EchoProvider` without an injected transform.

## Provider extension contract

A custom provider needs four public attributes and one method:

```python
class MyProvider:
    provider_id = "my-provider"
    name = provider_id
    base_url = "https://translation.example/v1"
    is_remote = True

    def translate(self, items, *, source_language, target_language):
        # Return one TranslationItem per input, with exact IDs and order.
        ...
```

Raise a `ProviderError` subclass from `csv_trans.exceptions` so recovery can
distinguish authentication, rate limits, context limits, timeouts, connection
failures, invalid responses, and server outages. Provider constructors should
receive credentials explicitly, avoid reading global process configuration,
and accept an injectable HTTP client so their contract can be tested offline.

## Status and counts

`row_count` counts data rows, not the header. `total_cells` counts fields that
were processed; header fields are included only when header translation is
enabled. `selected_cells` includes blank selected fields, while
`translated_cells` counts fields whose translation fully succeeded.
`cached_cells` is the subset completed entirely through deduplication/cache.
`failed_cells` counts original-preserved fields, and `skipped_cells` includes
unselected or safely bypassed fields.

An output containing one or more preserved failures is `partial`, never silent
success. A fatal input/configuration/write error raises to the Python caller and
maps to CLI exit code 1. Cancellation does not publish the temporary CSV.
`RunStatus.FAILED` is reserved for forward compatibility and is not produced by
the v2 core.

## Deliberate v2 limits

- The built-in Google web adapter is undocumented and cannot offer an uptime or
  stability guarantee.
- Translation is synchronous; bounded asynchronous/concurrent transport can be
  added later behind the same provider/core boundary.
- There is no inbound REST service or model-runtime manager.
- CSV lexical quoting may be normalized even though field values and dialect
  semantics are preserved.
- Spreadsheet formula neutralization is intentionally outside the CSV engine:
  quoting a value beginning with `=`, `+`, `-`, or `@` does not prevent a
  spreadsheet application from evaluating it.
- Automatic selection is heuristic. Known production schemas should select
  columns explicitly.

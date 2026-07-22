# Product direction after discovery

Status: accepted  
Recorded: 2026-07-17

This document converts the maintainer's answers after the repository audit into
an implementation contract. It supersedes the broader API assumptions in the
initial audit where they differ.

## Confirmed decisions

### "API" means translation providers

The next API work is provider support inside the Python package, not a hosted
CSV upload service. The package should translate through:

- OpenAI models.
- Anthropic Claude models.
- Qwen and DeepSeek models.
- Other services that implement a compatible HTTP protocol.
- Locally hosted models for confidential data.

An HTTP/REST service around `csv_trans` can still be added later, but it is not
the meaning of the immediate API requirement.

### Remove deep-translator

`deep-translator` will not be the foundation of the new provider system. Its
behavioral, multiprocessing, provenance, and dependency problems should be
removed rather than wrapped permanently.

### Keep the base package dependency-free

CSV parsing, CSV writing, chunking, batching, retries, validation, reporting,
configuration, and HTTP transport should use the Python standard library.

The production base should not depend on pandas, PyArrow, NumPy, requests,
chardet, tqdm, translation SDKs, or web frameworks. Development-only test and
quality tools may remain optional.

### Include a no-key default provider

The normal installation should include a built-in free provider that requires
no API key. The first implementation candidate is a Google web translation
adapter using an undocumented public web request or carefully isolated scraping
logic.

Because any no-key web technique can change without notice, it must be one
replaceable provider rather than logic embedded in the CSV core. Its network and
privacy behavior must be explicit in CLI output and documentation.

### Manage CSV translation internally

External providers should receive only text batches and return translations.
They must not receive responsibility for parsing CSV files, selecting fields,
mapping rows, naming outputs, retries, or recovery.

The package owns:

- Lossless CSV row and column mapping.
- Encoding and dialect handling.
- Field selection and header policy.
- Stable cell IDs and response-order validation.
- Text chunking and reassembly.
- Batching, deduplication, and caching policy.
- Retry, fallback, and partial-failure handling.
- Progress events and cancellation.
- Atomic output and structured reports.

### Recover aggressively, then report partial failure

A provider failure should not immediately abandon all remaining cells. The
package should apply a bounded recovery ladder, continue wherever safe, preserve
the original value for an ultimately failed cell, and produce a complete failure
report.

"Try every possible solution" is implemented as a deterministic, finite policy;
it must not create an infinite retry loop, unexpected charges, or an
unauthorized privacy boundary crossing.

### Support confidential inputs and local models

Confidential operation is a first-class mode. The package must support local
model endpoints and must be able to guarantee that a local-only run never falls
back to an internet provider.

## Provider architecture

The initial protocol set should be small:

```text
Translator protocol
    |
    +-- GoogleFreeProvider
    |     no key, network, replaceable implementation
    |
    +-- OpenAICompatibleProvider
    |     OpenAI, compatible hosted services, and local servers
    |
    +-- AnthropicProvider
    |     Claude Messages protocol
    |
    +-- FakeProvider
          deterministic offline tests
```

The OpenAI-compatible adapter should allow a configurable base URL, model,
headers, API key, timeout, and model options. This creates one path for OpenAI,
compatible DeepSeek/Qwen offerings, and local servers such as Ollama, llama.cpp,
vLLM, LM Studio, or LocalAI when they expose that protocol.

The Anthropic adapter is separate because its request and response schema is
different. Additional native protocols can be added without changing CSV logic.

Provider clients should use standard-library HTTPS/JSON transport. Vendor SDKs
may be offered later as optional integrations only if they add a capability that
cannot be supported safely through HTTP.

## Privacy profiles

Every translation run should have an explicit network policy:

### `public`

- The no-key provider may be used.
- Configured remote LLM fallbacks may be used.
- Output reports identify every provider that received data.

### `restricted`

- Only an explicit allowlist of configured providers may receive data.
- There is no automatic fallback to another vendor.
- Persistent plaintext caching is disabled unless explicitly enabled.

### `local-only`

- Only loopback or explicitly approved local endpoints are permitted.
- DNS/public internet providers are rejected before reading translation cells.
- No remote fallback is allowed, even when local translation fails.
- Logs and reports contain coordinates and error types, not cell contents.

The no-key default is therefore an ease-of-use default, not a safe default for
confidential data. Confidential callers must be able to select `local-only`
before any cell content leaves the process.

## LLM translation integrity

LLM output cannot be trusted solely because the HTTP request succeeded. Each
batch should carry stable internal item IDs and request a strict JSON mapping.
The package must validate:

- Response JSON syntax and schema.
- Exact ID set with no missing or duplicate items.
- Expected item count and maximum length.
- No Markdown fences or commentary.
- No translation of cells that were not selected.
- Preservation rules for placeholders, markup, URLs, and variables when enabled.

Invalid batch output enters the recovery ladder rather than being written to the
CSV.

## Bounded recovery ladder

For each failed batch or invalid LLM response:

1. Classify the error as transient, permanent, malformed output, context limit,
   authentication, quota, or policy violation.
2. Retry transient failures with capped exponential backoff and jitter.
3. Retry malformed structured output once with a corrective prompt.
4. Split the batch into smaller batches.
5. Split a long cell losslessly at a safer semantic boundary.
6. Retry remaining items one at a time.
7. Use the next configured provider only when the active privacy profile permits
   it and the user explicitly configured that fallback.
8. Preserve the original cell, continue, and record the final failure.

Authentication errors, invalid API keys, privacy-policy violations, and hard
budget limits should not be retried blindly.

## Result and failure report

The Python API should return a structured result and the CLI should be able to
write the same information as JSON. At minimum it should include:

- Input and output paths.
- Total, selected, translated, cached, skipped, and failed cell counts.
- Source/target languages and selected columns.
- Encoding and CSV dialect.
- Provider attempts without secrets or cell content.
- Retries and fallback counts.
- Per-failure row, column, error category, provider, attempts, and whether the
  original value was preserved.
- A final status such as `success`, `partial`, or `failed`.

The translated CSV may be produced for a partial result because the chosen
policy is to preserve failed source cells. The report makes the mixture visible
and machine-detectable.

## Explanation of the compatibility question

The earlier question about a "2.0 compatibility break" asked whether fixes may
deliberately change behavior that existing users could rely on.

For example, version 1.1.4:

- Returns `None` instead of a result.
- Renames only the second header.
- Translates strings in every column.
- Always overwrites a fixed output filename.
- Saves non-comma input as comma-separated output.

Preserving those behaviors would preserve bugs and ambiguity. The recommended
answer is:

- Release the redesign as 2.0.
- Keep `translate(file, source_lang, target_lang, sep=',')` as a compatibility
  wrapper so simple callers still run.
- Correct unsafe semantics rather than retaining them silently.
- Provide a migration guide and, only where safe, explicit legacy options.

## Final defaults

The maintainer confirmed these user-visible defaults:

1. **Column selection:** when `columns` is omitted, automatically detect
   text-like columns, skip empty/numeric/identifier-like fields, record the
   selection in the result, and allow explicit names or indexes to override it.
2. **Headers:** preserve headers by default. Translate them only when the Python
   API or CLI explicitly enables header translation.
3. **Versioning:** release the redesign as 2.0 while keeping the historical
   four-argument `translate(...)` form as a compatibility wrapper.
4. **Local models:** require the caller to supply an OpenAI-compatible HTTP base
   URL and model name for a running local model server. `csv_trans` will not
   install, download, launch, or manage model runtimes.

Hosted and local OpenAI-compatible models therefore use the same adapter and
configuration model. A local-only privacy profile additionally verifies that
the configured endpoint is loopback or explicitly approved before any source
text is processed.

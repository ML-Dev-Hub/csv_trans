# csv-trans

[![CI](https://github.com/ML-Dev-Hub/csv_trans/actions/workflows/ci.yml/badge.svg)](https://github.com/ML-Dev-Hub/csv_trans/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/csv-trans.svg)](https://pypi.org/project/csv-trans/)
[![Python](https://img.shields.io/pypi/pyversions/csv-trans.svg)](https://pypi.org/project/csv-trans/)
[![PyPI Downloads](https://static.pepy.tech/personalized-badge/csv-trans?period=total&units=INTERNATIONAL_SYSTEM&left_color=BLACK&right_color=GREEN&left_text=downloads)](https://pepy.tech/projects/csv-trans)

`csv-trans` translates selected text fields in CSV files through a built-in
no-key provider, OpenAI-compatible hosted or local models, or Anthropic. Version
2 uses the Python standard library for CSV handling, HTTP, retries, reporting,
and configuration: the installed package has **zero mandatory runtime
dependencies**.

> [!IMPORTANT]
> Translation providers receive selected cell text. The default `google-free`
> provider is an experimental, undocumented internet service and is not suitable
> for confidential data. Use `local-only` with a model endpoint you control when
> text must not leave your approved network boundary. The CLI defaults to
> `privacy=public` and, when `--provider` is omitted, warns before using
> `google-free`; `--quiet` suppresses that warning but does not prevent the
> transfer. Use `--dry-run` to inspect column selection without contacting a
> provider.

## Requirements and installation

`csv-trans` supports CPython 3.11, 3.12, 3.13, and 3.14.

```bash
python -m pip install csv-trans
```

Or with [uv](https://docs.astral.sh/uv/):

```bash
uv pip install csv-trans
```

Both `csv-trans` and the historical `csv_trans` executable name are installed.

## Quick start

The primary Python API returns a structured result:

```python
from csv_trans import TranslationConfig, translate_csv

config = TranslationConfig(
    source_language="en",
    target_language="fr",
    privacy="public",
)
result = translate_csv("catalog.csv", config)

print(result.status.value)
print(result.output_path)
print(result.translated_cells, result.failed_cells)
```

With no provider object, the built-in `google-free` provider is used. Headers
are preserved and text-like columns are selected automatically; numeric,
empty, and identifier-like columns are skipped. Pass `columns=("title",
"description")` or column indexes to override selection, and set
`translate_headers=True` only when translated headers are desired.

A string-language convenience wrapper builds the configuration for you and
accepts any configuration field as a keyword argument:

```python
from csv_trans import translate

result = translate("catalog.csv", "en", "fr", columns=("title",))
```

`translate` returns the same `TranslationResult` as `translate_csv`, so callers
can detect partial completion and find the output file. The delimiter is
auto-detected; pass `delimiter=";"` to set it explicitly.

The equivalent default CLI command is:

```bash
csv-trans -f catalog.csv -sl en -tl fr
```

Run `csv-trans --help` for column, encoding, output, report, recovery, and
privacy options.

## Providers

| Provider ID | Intended use | Credentials and network behavior |
| --- | --- | --- |
| `google-free` | Easy no-key default | Remote, undocumented Google web endpoint; experimental and replaceable |
| `openai` | Official OpenAI Chat Completions API | Model and API key; official base URL by default |
| `openai-compatible` | Any explicitly configured compatible hosted or local API | Explicit base URL and model; key depends on the endpoint |
| `qwen`, `deepseek` | Named compatible hosted/local aliases | Explicit base URL and model; provider-specific environment variables |
| `local`, `ollama`, `llama.cpp`, `vllm`, `lm-studio`, `localai` | Named local-compatible aliases | Explicit base URL and model; never default to a public host |
| `anthropic` | Anthropic Claude Messages API | API key; official Anthropic host by default, with an explicit base-URL override |
| `echo` | Offline tests and orchestration checks | No network and no credential; does not translate text |

Providers accept stable item IDs and must return the same IDs in the same order.
Malformed JSON, missing or duplicate IDs, unexpected commentary, HTTP failures,
and oversized responses are rejected before anything is written to the CSV.

Python callers construct provider objects explicitly. Provider classes do not
read the process environment on their own:

```python
import os

from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    model=os.environ["CSV_TRANS_OPENAI_COMPATIBLE_MODEL"],
    base_url=os.environ["CSV_TRANS_OPENAI_COMPATIBLE_BASE_URL"],
    api_key=os.environ.get("CSV_TRANS_OPENAI_COMPATIBLE_API_KEY"),
)
config = TranslationConfig(
    source_language="en",
    target_language="fr",
    provider=provider,
    privacy="restricted",
    allowed_providers=(provider.provider_id,),
)
result = translate_csv("catalog.csv", config)
```

Environment-variable mapping is a CLI convenience. Explicit Python
configuration makes credential and destination flow visible to applications.

### Official OpenAI endpoint

Credentials are supplied through the environment, never as a literal CLI
argument:

```bash
export CSV_TRANS_OPENAI_API_KEY="..."
export CSV_TRANS_OPENAI_MODEL="your-openai-model"

csv-trans -f catalog.csv -sl en -tl fr \
  --provider openai \
  --privacy restricted
```

The same adapter powers Qwen and DeepSeek aliases, but those aliases require an
explicit destination and use `CSV_TRANS_QWEN_*` and
`CSV_TRANS_DEEPSEEK_*` variables respectively. Always verify the service's
protocol, retention policy, cost, and base URL before sending data.

### Local OpenAI-compatible model

Start and manage the model server separately, then point `csv-trans` at its
OpenAI-compatible endpoint:

```bash
export CSV_TRANS_OPENAI_COMPATIBLE_BASE_URL="http://127.0.0.1:11434/v1"
export CSV_TRANS_OPENAI_COMPATIBLE_MODEL="qwen3"

csv-trans -f confidential.csv -sl en -tl ko \
  --provider openai-compatible \
  --privacy local-only
```

`local-only` validates the destination before selected cell text is submitted
and never falls back to an internet provider. `csv-trans` does not download,
install, launch, or supervise Ollama or any other model runtime.

The boundary is enforceable for the built-in providers and transport, not an
operating-system sandbox around arbitrary Python extensions. A custom provider
or injected `HttpClient` is trusted code and can ignore its declared endpoint,
open other connections, or follow redirects in violation of the extension
contract. `local-only` therefore rejects endpointless custom providers even
when they self-report `is_remote=False`; the only endpointless exception is the
exact built-in `EchoProvider` without an injected transform.

Endpoint validation is not a trust assessment. A local model server can still
log prompts, retain data, expose an insecure administration interface, or be
accessible to other users. Operators remain responsible for the server,
network, model, access controls, and retention policy.

Loopback HTTP is accepted for local servers. Non-loopback endpoints require
HTTPS by default. A Python caller using an explicitly approved, trusted LAN
server over HTTP must also set `allow_insecure_http=True` on the provider; the
CLI applies that opt-in only in `local-only` mode and still requires the host in
`--approved-local-host`.

### Anthropic

```bash
export CSV_TRANS_ANTHROPIC_API_KEY="..."
export CSV_TRANS_ANTHROPIC_MODEL="your-anthropic-model"

csv-trans -f catalog.csv -sl en -tl de \
  --provider anthropic \
  --privacy restricted
```

### Provider chains

`--provider` accepts a comma-separated chain and may also be repeated. A later
provider is tried only after bounded recovery fails and the selected privacy
mode permits that destination:

```bash
csv-trans -f catalog.csv -sl en -tl es \
  --provider openai-compatible,google-free \
  --privacy public
```

Authentication failures, policy violations, and hard budget or quota failures
are not retried blindly. No fallback is implicit: only providers explicitly in
the chain can follow the primary provider.

## Environment variables

| Variable | Meaning |
| --- | --- |
| `CSV_TRANS_PROVIDER` | Default provider ID or comma-separated provider chain |
| `CSV_TRANS_OPENAI_API_KEY` | Credential for the official OpenAI host |
| `CSV_TRANS_OPENAI_BASE_URL` | Optional base-URL override for the `openai` provider ID |
| `CSV_TRANS_OPENAI_MODEL` | Model for the `openai` provider ID |
| `CSV_TRANS_OPENAI_COMPATIBLE_API_KEY` | Optional credential for a generic compatible endpoint |
| `CSV_TRANS_OPENAI_COMPATIBLE_BASE_URL` | Required base URL for `openai-compatible` |
| `CSV_TRANS_OPENAI_COMPATIBLE_MODEL` | Model for `openai-compatible` |
| `CSV_TRANS_OPENAI_CUSTOM_API_KEY` | Credential used when `openai` is pointed at a non-OpenAI host |
| `CSV_TRANS_QWEN_API_KEY`, `CSV_TRANS_QWEN_BASE_URL`, `CSV_TRANS_QWEN_MODEL` | Named Qwen-compatible endpoint |
| `CSV_TRANS_DEEPSEEK_API_KEY`, `CSV_TRANS_DEEPSEEK_BASE_URL`, `CSV_TRANS_DEEPSEEK_MODEL` | Named DeepSeek-compatible endpoint |
| `CSV_TRANS_LOCAL_API_KEY`, `CSV_TRANS_LOCAL_BASE_URL`, `CSV_TRANS_LOCAL_MODEL` | `local` alias (API key optional) |
| `CSV_TRANS_OLLAMA_API_KEY`, `CSV_TRANS_OLLAMA_BASE_URL`, `CSV_TRANS_OLLAMA_MODEL` | `ollama` alias (API key optional) |
| `CSV_TRANS_LLAMA_CPP_API_KEY`, `CSV_TRANS_LLAMA_CPP_BASE_URL`, `CSV_TRANS_LLAMA_CPP_MODEL` | `llama.cpp` alias (API key optional) |
| `CSV_TRANS_VLLM_API_KEY`, `CSV_TRANS_VLLM_BASE_URL`, `CSV_TRANS_VLLM_MODEL` | `vllm` alias (API key optional) |
| `CSV_TRANS_LM_STUDIO_API_KEY`, `CSV_TRANS_LM_STUDIO_BASE_URL`, `CSV_TRANS_LM_STUDIO_MODEL` | `lm-studio` alias (API key optional) |
| `CSV_TRANS_LOCALAI_API_KEY`, `CSV_TRANS_LOCALAI_BASE_URL`, `CSV_TRANS_LOCALAI_MODEL` | `localai` alias (API key optional) |
| `CSV_TRANS_ANTHROPIC_API_KEY` | Credential for the official Anthropic host |
| `CSV_TRANS_ANTHROPIC_CUSTOM_API_KEY` | Credential used with a non-Anthropic Messages endpoint |
| `CSV_TRANS_ANTHROPIC_BASE_URL` | Optional Anthropic-compatible base URL override |
| `CSV_TRANS_ANTHROPIC_MODEL` | Anthropic model name |

`OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are lower-precedence credential
fallbacks only when the resolved destination is the exact official vendor
host. They are never forwarded automatically to a generic or custom endpoint.
The matching `CSV_TRANS_*` name wins when both are defined.
`--api-key-env NAME` tells the CLI to read a differently named environment
variable; there is deliberately no `--api-key` flag. Sensitive literal
`--header` names are also rejected. `--base-url`, `--model`, and non-sensitive
custom headers apply only to the primary provider; fallbacks use their own
provider-specific environment variables.

The built-in HTTP transport deliberately ignores ambient `HTTP_PROXY` and
`HTTPS_PROXY` variables so a local-only request cannot be silently rerouted.
Applications that require a trusted corporate proxy should inject an explicit
`HttpClient` and treat that proxy as a data recipient.

## Privacy modes

| Mode | Guarantee |
| --- | --- |
| `public` | Permits the no-key provider and explicitly configured remote fallbacks; records sanitized recipient hosts in attempt telemetry |
| `restricted` | Uses only the explicit provider allowlist and never changes vendors automatically; caching is memory-only |
| `local-only` | Allows loopback or explicitly approved local endpoints only; rejects public destinations before translation and never falls back remotely |

Logs and structured reports contain coordinates, provider IDs, sanitized
recipient hosts, attempt counts, and error categories—not source cell text,
translated text, credentials, or header names by default.

### CSV and temporary-file boundaries

`csv-trans` preserves CSV field values; it does not neutralize spreadsheet
formulas. A source value or provider translation beginning with characters such
as `=`, `+`, `-`, or `@` can be interpreted as a formula when the output is
opened in spreadsheet software. CSV quoting does not prevent that behavior.
Applications that export to a spreadsheet must apply a consumer-appropriate
formula-injection policy after translation and keep translation concerns
separate from export sanitization.

To process one stable input version, the engine creates a full byte-for-byte
plaintext snapshot beside the input CSV by default, keeping it on the same
storage boundary. Set `snapshot_directory=` in Python or
`--snapshot-directory` on the CLI to choose another protected location. Atomic
CSV and JSON publication also uses plaintext staging/rollback files beside each
destination. Normal completion and handled failures remove them, but a process
crash, forced termination, or power loss can leave residue. Confidential
deployments should secure and encrypt every selected directory and include
orphaned `.csv-trans-*.snapshot`, `*.tmp`, and `*.rollback` files in their
retention and cleanup policy.

Each destination file is published atomically. When a report is required, v2
publishes it first and rolls it back if the CSV commit fails, including restoring
an overwritten prior report. No portable filesystem primitive can atomically
commit two separate paths, so a process or host crash in that narrow interval
can still leave one side visible; consumers should treat the report and CSV as
an auditable pair.

## Partial failures and recovery

Recovery is aggressive but finite: transient requests use capped backoff,
malformed LLM output receives a distinct corrective prompt, large batches are
split, long cells are split losslessly, and a singleton that still hits a
context limit is adaptively split into smaller separate requests down to
`min_adaptive_chars`. A configured fallback is considered only after those
steps and only within the privacy policy.

If a cell still fails, its original value is preserved and processing continues.
The output may therefore be produced with `result.status == RunStatus.PARTIAL`.
Inspect `result.failures` or write the content-free report as JSON:

```python
result.write_json("catalog.translation.json")

for failure in result.failures:
    print(failure.row, failure.column_name, failure.category, failure.provider)
```

Partial CLI runs automatically create a collision-safe
`<output>.report.json` sidecar. Serialized reports omit header names by default;
the in-memory result retains them, and trusted callers can opt in with
`include_column_names=True`. Existing report files are not replaced unless
`overwrite=True` is explicit.

`RunStatus.FAILED` is reserved for forward compatibility. Version 2 raises
fatal input, configuration, privacy-preflight, and write errors to Python
callers instead of returning a failed result. Returned results use `success`,
`partial`, `cancelled`, or `dry-run`; the CLI maps raised fatal errors to exit
code 1.

CLI runs return a nonzero status for partial or failed results so automation
cannot silently treat mixed-language output as complete.

| Exit code | Meaning |
| --- | --- |
| `0` | Success or dry run |
| `1` | Failed, cancelled, or configuration/runtime error |
| `2` | Partial output; `argparse` also uses 2 for invalid CLI syntax |

## What v2 intentionally does not provide

- It is not an inbound HTTP/REST server. A server may be a separate future
  layer, but none is installed or started in v2.0.
- It is not a model runtime or model downloader.
- The no-key provider has no uptime or compatibility guarantee.
- Automatic column selection is conservative; use explicit columns when the
  schema is known.

## Project documentation

- [Migration from 1.x](https://github.com/ML-Dev-Hub/csv_trans/blob/main/docs/internal/MIGRATION_V2.md)
- [Local and CI test bed](https://github.com/ML-Dev-Hub/csv_trans/blob/main/TESTING.md)
- [Security and private reporting](https://github.com/ML-Dev-Hub/csv_trans/blob/main/SECURITY.md)
- [Version 2 architecture](https://github.com/ML-Dev-Hub/csv_trans/blob/main/docs/internal/ARCHITECTURE_V2.md)
- [Changelog](https://github.com/ML-Dev-Hub/csv_trans/blob/main/CHANGELOG.md)
- [Contributing](https://github.com/ML-Dev-Hub/csv_trans/blob/main/CONTRIBUTING.md)

## Acknowledgements

`csv-trans` was created by [Saeed Ahmad](https://github.com/saeedahmadicp),
with contributions from [Izhar Ali](https://github.com/ali-izhar) and
[Shaharyar Sajid](https://github.com/shaharyar-sajid).

## License

`csv-trans` is distributed under the
[MIT License](https://github.com/ML-Dev-Hub/csv_trans/blob/main/LICENSE).

---
title: CLI
description: Every flag, provider alias, environment variable, and exit code for the csv-trans command-line interface.
---

Two identical console scripts are installed: **`csv-trans`** and **`csv_trans`**.

```bash
csv-trans -f catalog.csv -sl en -tl fr --provider echo --output catalog.fr.csv
```

Only `-f`, `-sl`, and `-tl` are required. Credentials are **never** passed as literal arguments — there is no `--api-key` flag; keys come from the environment.

## Flags

### Required

| Flag | Description |
| --- | --- |
| `-f`, `--file`, `--file-path` | Input CSV path. |
| `-sl`, `--source-language` | Source language code/name, or `auto`. |
| `-tl`, `--target-language` | Target language code/name. |

### Output and structure

| Flag | Type / default | Description |
| --- | --- | --- |
| `-o`, `--output` | path | Output CSV path (default `translated_<target>_<name>.csv`). |
| `-fs`, `--delimiter`, `--file-separator` | char | One-character delimiter; auto-detected when omitted. |
| `--columns` | names / `#N` … | Column names or zero-based indexes written as `#N`. Space-separated. |
| `--translate-headers` | flag | Also translate the selected columns' headers. |
| `--encoding` | str | Input encoding; default is BOM detection / strict UTF-8. |
| `--output-encoding` | str (`utf-8`) | Output encoding. |
| `--overwrite` | flag | Replace an existing output. |

### Providers

| Flag | Type / default | Description |
| --- | --- | --- |
| `--provider` | id (repeatable) | Primary provider ID; repeat or comma-separate to append fallbacks. Default `google-free`. |
| `--fallback-provider` | id (repeatable) | Explicit fallback provider ID. |
| `--model` | str | Model for the **primary** LLM provider. |
| `--base-url` | url | Base URL for the **primary** LLM provider. |
| `--api-key-env` | name | Read the primary provider's API key from this env var. |
| `--header` | `NAME=VALUE` (repeatable) | Extra HTTP header for the **primary** provider. Sensitive header names are rejected. |
| `--timeout` | float (`60.0`) | HTTP timeout in seconds (must be finite and > 0). |

`--base-url`, `--model`, `--api-key-env`, and `--header` apply **only** to the primary provider; fallbacks use their own provider-specific environment variables.

### Privacy

| Flag | Type / default | Description |
| --- | --- | --- |
| `--privacy` | `public` \| `restricted` \| `local-only` (`public`) | Network boundary. |
| `--allow-provider` | name (repeatable) | Provider allowed under `restricted`. |
| `--approved-local-host` | host (repeatable) | Exact non-loopback host approved under `local-only`. |

Under `restricted`, if you pass `--provider` explicitly and no `--allow-provider`, the chain's providers are allowed automatically.

### Batching and limits

| Flag | Type / default |
| --- | --- |
| `--batch-size` | int (`20`) |
| `--max-chars` | int (`3500`) |
| `--min-adaptive-chars` | int (`32`) |
| `--max-field-chars` | int (`67108864`, 64 MiB) |
| `--max-row-chars` | int (`134217728`, 128 MiB) |
| `--max-columns` | int (`10000`) |
| `--max-sample-chars` | int (`16777216`, 16 MiB) |
| `--max-pending-chars` | int (`67108864`, 64 MiB) |
| `--max-failure-details` | int (`10000`) |

### Recovery

| Flag | Type / default | Description |
| --- | --- | --- |
| `--max-retries` | int (`2`) | Transient-error retries per provider. |
| `--malformed-retries` | int (`1`) | Corrective retries for invalid model output. |
| `--backoff-base` | float (`0.5`) | Base seconds for exponential backoff. |
| `--max-backoff` | float (`8.0`) | Cap on backoff delay. |
| `--allow-empty-translations` | flag | Accept an empty result for non-empty source text. |

### Reporting and output modes

| Flag | Type / default | Description |
| --- | --- | --- |
| `--report` | path | Write the structured JSON result here. |
| `--snapshot-directory` | path | Directory for the transient plaintext source snapshot (default: beside the input). |
| `--dry-run` | flag | Inspect selection without translating or writing a CSV. |
| `--json` | flag | Print the content-free result as JSON to stdout. |
| `--quiet` | flag | Suppress the human summary (and the default-provider warning). |
| `--version` | flag | Print the version and exit. |

:::note
The CLI exposes a subset of [`TranslationConfig`](/csv_trans/reference/python-api/). Fields such as `sample_rows`, `cache_size`, `jitter`, `preserve_placeholders`, `progress_callback`, and `cancellation_check` are available only through the Python API and use their defaults on the CLI.
:::

## Provider aliases

`--provider` (and `CSV_TRANS_PROVIDER`) accept these aliases, each mapping to a canonical provider ID:

| Alias(es) | Canonical ID | Adapter |
| --- | --- | --- |
| `google-free`, `google`, `free`, `default` | `google-free` | Google no-key (experimental) |
| `echo`, `identity` | `echo` | Offline echo |
| `anthropic`, `claude` | `anthropic` | Anthropic Messages |
| `openai` | `openai` | OpenAI-compatible (official host default) |
| `openai-compatible` | `openai-compatible` | OpenAI-compatible (explicit base URL) |
| `local` | `local` | OpenAI-compatible local |
| `qwen` | `qwen` | OpenAI-compatible |
| `deepseek` | `deepseek` | OpenAI-compatible |
| `ollama` | `ollama` | OpenAI-compatible local |
| `llama.cpp` | `llama.cpp` | OpenAI-compatible local |
| `vllm` | `vllm` | OpenAI-compatible local |
| `lm-studio` | `lm-studio` | OpenAI-compatible local |
| `localai` | `localai` | OpenAI-compatible local |

An unknown provider ID is a fatal error (exit code 1).

## Environment variables

Credentials and per-provider settings are read from the environment; the primary provider's `--model`, `--base-url`, and `--api-key-env` override them.

| Variable | Meaning |
| --- | --- |
| `CSV_TRANS_PROVIDER` | Default provider ID or comma-separated chain when `--provider` is omitted. |
| `CSV_TRANS_OPENAI_API_KEY` | Credential for the official OpenAI host. |
| `CSV_TRANS_OPENAI_BASE_URL` | Optional base-URL override for the `openai` ID. |
| `CSV_TRANS_OPENAI_MODEL` | Model for the `openai` ID. |
| `CSV_TRANS_OPENAI_CUSTOM_API_KEY` | Credential when `openai` points at a non-OpenAI host (optional). |
| `CSV_TRANS_OPENAI_COMPATIBLE_API_KEY` / `_BASE_URL` / `_MODEL` | Generic compatible endpoint (base URL required, key optional). |
| `CSV_TRANS_QWEN_API_KEY` / `_BASE_URL` / `_MODEL` | `qwen` alias. |
| `CSV_TRANS_DEEPSEEK_API_KEY` / `_BASE_URL` / `_MODEL` | `deepseek` alias. |
| `CSV_TRANS_LOCAL_API_KEY` / `_BASE_URL` / `_MODEL` | `local` alias (key optional). |
| `CSV_TRANS_OLLAMA_API_KEY` / `_BASE_URL` / `_MODEL` | `ollama` alias (key optional). |
| `CSV_TRANS_LLAMA_CPP_API_KEY` / `_BASE_URL` / `_MODEL` | `llama.cpp` alias (key optional). |
| `CSV_TRANS_VLLM_API_KEY` / `_BASE_URL` / `_MODEL` | `vllm` alias (key optional). |
| `CSV_TRANS_LM_STUDIO_API_KEY` / `_BASE_URL` / `_MODEL` | `lm-studio` alias (key optional). |
| `CSV_TRANS_LOCALAI_API_KEY` / `_BASE_URL` / `_MODEL` | `localai` alias (key optional). |
| `CSV_TRANS_ANTHROPIC_API_KEY` | Credential for the official Anthropic host. |
| `CSV_TRANS_ANTHROPIC_CUSTOM_API_KEY` | Credential for a non-Anthropic Messages endpoint. |
| `CSV_TRANS_ANTHROPIC_BASE_URL` | Optional Anthropic-compatible base-URL override. |
| `CSV_TRANS_ANTHROPIC_MODEL` | Anthropic model name. |

The generic `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are **lower-precedence** fallbacks considered **only** when the resolved destination is the exact official vendor host; the matching `CSV_TRANS_*` name wins when both are set. They are never forwarded to a generic or custom endpoint.

For any OpenAI-family alias other than `openai`, a base URL is required (via `--base-url` on the primary, or the alias's `_BASE_URL` variable), and a model is required (via `--model` or the alias's `_MODEL` variable).

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | Success or dry run. |
| `2` | Partial output (some cells preserved). `argparse` also uses `2` for invalid CLI syntax. |
| `1` | Fatal error (input/config/privacy/write error), an unknown provider, or a cancelled run. |

## Examples

Offline, no key, private mode:

```bash
csv-trans -f catalog.csv -sl en -tl fr \
  --provider echo --output catalog.fr.csv --privacy local-only --quiet
```

Official OpenAI, restricted privacy, from the environment:

```bash
export CSV_TRANS_OPENAI_API_KEY="sk-..."
export CSV_TRANS_OPENAI_MODEL="gpt-4o-mini"
csv-trans -f catalog.csv -sl en -tl fr --provider openai --privacy restricted
```

Local Ollama model, local-only:

```bash
export CSV_TRANS_OLLAMA_BASE_URL="http://localhost:11434/v1"
export CSV_TRANS_OLLAMA_MODEL="qwen3"
csv-trans -f confidential.csv -sl en -tl ko --provider ollama --privacy local-only
```

Provider chain (fallback only after bounded recovery and within privacy policy):

```bash
csv-trans -f catalog.csv -sl en -tl es \
  --provider openai-compatible,google-free --privacy public
```

Explicit columns, translated headers, JSON output, and a report:

```bash
csv-trans -f catalog.csv -sl en -tl de \
  --provider echo --columns title description --translate-headers \
  --report catalog.report.json --json
```

:::caution
When `--provider` is omitted, the CLI prints a one-time stderr warning before sending cell text to the default [`google-free`](/csv_trans/providers/) adapter. `--quiet` hides the warning but does not prevent the transfer; `--dry-run` inspects selection without contacting any provider.
:::

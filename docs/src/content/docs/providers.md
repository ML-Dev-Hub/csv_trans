---
title: Providers
description: The built-in translation adapters, the shared response contract, and how to write a custom provider.
---

A provider translates text items and nothing else. `csv-trans` ships four
built-in adapters and accepts custom ones. The engine owns everything around
them — CSV parsing, column selection, chunking, retries, privacy, and
reporting; a provider never parses a CSV, chooses columns, retries a cell, or
makes a privacy decision.

## Comparison

| Provider | Class | Network | Credentials | Notes |
| --- | --- | --- | --- | --- |
| OpenAI-compatible | `OpenAICompatibleProvider` | Remote or local | API key optional | Any `/chat/completions` API — hosted or a local server |
| Anthropic | `AnthropicProvider` | Remote | API key required | Anthropic Messages API (`/v1/messages`) |
| Google (no-key) | `GoogleFreeProvider` | Remote | None | **Experimental**, undocumented web endpoints; the default when no provider is set |
| Echo | `EchoProvider` | None | None | Offline; returns text unchanged, or an injected transform |

Pick a local model behind [OpenAI-compatible](#local-models) for confidential
data under `local-only`; [OpenAI-compatible](#openai-compatible) or
[Anthropic](#anthropic) for hosted APIs; [Google no-key](#google-no-key) for
quick, non-sensitive experiments; [Echo](#echo-offline) for tests, CI, and dry
runs.

### Constructing providers in Python

`provider=` and any `fallback_providers=` entries take provider objects, not
strings — provider classes never read the process environment. When
`provider=None`, the engine uses the experimental `GoogleFreeProvider`. The
[CLI](/csv_trans/reference/cli/) maps string aliases and environment variables to these
objects.

```python
from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import OpenAICompatibleProvider, GoogleFreeProvider

primary = OpenAICompatibleProvider(model="gpt-4o-mini", base_url="https://api.openai.com/v1", api_key="sk-...")
config = TranslationConfig(
    source_language="en",
    target_language="es",
    provider=primary,
    fallback_providers=(GoogleFreeProvider(),),
    privacy="public",
)
result = translate_csv("catalog.csv", config)
```

## OpenAI-compatible

`OpenAICompatibleProvider` targets any OpenAI-style `/chat/completions`
endpoint. The same adapter serves the official OpenAI API, compatible hosted
vendors (Qwen, DeepSeek, and others), and local model servers.

```python
OpenAICompatibleProvider(
    model,                      # str, required
    *,
    base_url,                   # str, required
    api_key=None,               # str | None
    http_client=None,           # inject an HttpClient for testing / proxying
    timeout=60.0,               # seconds, > 0
    temperature=None,           # float >= 0, or None
    instruction_role=None,      # "system" | "developer" | None (auto)
    response_format=None,       # mapping, e.g. {"type": "json_object"}
    max_tokens=None,            # positive int, or None
    extra_headers=None,         # mapping[str, str]
    allow_insecure_http=False,  # allow non-loopback HTTP (trusted LAN only)
)
```

- `base_url` is validated: `http`/`https` only, no credentials, query, or
  fragment, and (unless loopback or `allow_insecure_http=True`) HTTPS. The
  request goes to `<base_url>/chat/completions`, or to `base_url` itself if it
  already ends with that path.
- `api_key`, when set, is sent as `Authorization: Bearer <key>`. Local servers
  usually need none.
- `instruction_role` defaults to `developer` for the `api.openai.com` host and
  `system` elsewhere.
- `extra_headers` cannot override the adapter's own `Accept`, `Content-Type`, or
  `Authorization` headers.

### Official OpenAI

```python
import os
from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    model="gpt-4o-mini",
    base_url="https://api.openai.com/v1",
    api_key=os.environ["CSV_TRANS_OPENAI_API_KEY"],
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

From the CLI, credentials and model come from the environment:

```bash
export CSV_TRANS_OPENAI_API_KEY="sk-..."
export CSV_TRANS_OPENAI_MODEL="gpt-4o-mini"

csv-trans -f catalog.csv -sl en -tl fr --provider openai --privacy restricted
```

### Compatible hosted vendors

The CLI exposes named aliases (`qwen`, `deepseek`, `openai-compatible`) that use
the same adapter but require an explicit base URL and their own
[environment variables](/csv_trans/reference/cli/#environment-variables) — each alias
reads `CSV_TRANS_<ALIAS>_BASE_URL`, `_MODEL`, and `_API_KEY`.

```bash
export CSV_TRANS_QWEN_BASE_URL="https://dashscope.example/compatible-mode/v1"
export CSV_TRANS_QWEN_MODEL="qwen-plus"
export CSV_TRANS_QWEN_API_KEY="..."

csv-trans -f catalog.csv -sl en -tl fr --provider qwen --privacy restricted
```

### Local models

Local servers that speak the OpenAI protocol — **Ollama**, **vLLM**,
**LM Studio**, **llama.cpp**, **LocalAI** — work by pointing `base_url` at their
loopback endpoint and running under `local-only` privacy. Loopback HTTP is
accepted without any insecure opt-in.

```python
from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import OpenAICompatibleProvider

# Ollama exposes an OpenAI-compatible API at /v1
provider = OpenAICompatibleProvider(model="qwen3", base_url="http://localhost:11434/v1")

config = TranslationConfig(
    source_language="en",
    target_language="ko",
    provider=provider,
    privacy="local-only",
)
result = translate_csv("confidential.csv", config)
```

Typical local base URLs:

| Server | Base URL | CLI alias |
| --- | --- | --- |
| Ollama | `http://localhost:11434/v1` | `ollama` |
| vLLM (OpenAI server) | `http://localhost:8000/v1` | `vllm` |
| LM Studio | `http://localhost:1234/v1` | `lm-studio` |
| llama.cpp server | `http://localhost:8080/v1` | `llama.cpp` |
| LocalAI | `http://localhost:8080/v1` | `localai` |

Each CLI alias carries its own `CSV_TRANS_<ALIAS>_BASE_URL`/`_MODEL` env vars and
never defaults to a public host:

```bash
export CSV_TRANS_OLLAMA_BASE_URL="http://localhost:11434/v1"
export CSV_TRANS_OLLAMA_MODEL="qwen3"

csv-trans -f confidential.csv -sl en -tl ko --provider ollama --privacy local-only
```

:::note
`csv-trans` never downloads, installs, launches, or supervises a model runtime —
start and manage the server yourself, then point the adapter at it.
:::

:::caution[Trusted LAN over HTTP]
A non-loopback local server reached over plain HTTP requires an explicit opt-in
(`allow_insecure_http=True`); see
[the loopback / HTTP rule](/csv_trans/privacy-and-security/#local-only).
:::

## Anthropic

`AnthropicProvider` translates through Anthropic's Messages API
(`/v1/messages`). It requires an API key and a model.

```python
AnthropicProvider(
    model,                      # str, required
    api_key,                    # str, required
    *,
    base_url="https://api.anthropic.com",
    api_version="2023-06-01",
    max_tokens=4096,            # positive int
    temperature=None,           # float >= 0, or None
    http_client=None,           # inject an HttpClient for testing / proxying
    timeout=60.0,               # seconds, > 0
    extra_headers=None,         # mapping[str, str]
    allow_insecure_http=False,
)
```

The request URL resolves to `<base_url>/v1/messages` — or `base_url` itself if it
already ends with `/v1/messages`, or `<base_url>/messages` if it ends with
`/v1`. The adapter sets `x-api-key`, `anthropic-version`, `Accept`, and
`Content-Type` itself; `extra_headers` cannot override those.

```python
import os
from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import AnthropicProvider

provider = AnthropicProvider(
    model="claude-sonnet-4-5",
    api_key=os.environ["CSV_TRANS_ANTHROPIC_API_KEY"],
)
config = TranslationConfig(
    source_language="en",
    target_language="de",
    provider=provider,
    privacy="restricted",
    allowed_providers=(provider.provider_id,),
)
result = translate_csv("catalog.csv", config)
```

```bash
export CSV_TRANS_ANTHROPIC_API_KEY="..."
export CSV_TRANS_ANTHROPIC_MODEL="claude-sonnet-4-5"

csv-trans -f catalog.csv -sl en -tl de --provider anthropic --privacy restricted
```

CLI aliases `anthropic` and `claude` both select this adapter.

**Credentials.** The official `api.anthropic.com` host reads
`CSV_TRANS_ANTHROPIC_API_KEY`, then the ambient `ANTHROPIC_API_KEY` as a
lower-precedence fallback. A non-Anthropic endpoint (set via
`CSV_TRANS_ANTHROPIC_BASE_URL`) reads `CSV_TRANS_ANTHROPIC_CUSTOM_API_KEY`. See
the [CLI reference](/csv_trans/reference/cli/) for the full precedence rule.

A body reporting a token/context overflow (for example `prompt is too long`) is
classed `context_limit` so the engine can split adaptively.

## Google (no-key)

`GoogleFreeProvider` is a no-key adapter for Google's **undocumented public web**
translation endpoints. It is the default provider when none is configured.

:::caution[Experimental and not private]
This adapter uses undocumented web endpoints, **not** Google Cloud Translation.
It can change, throttle, or stop working without notice, offers no availability,
privacy, or contractual guarantee, and **must not be used for confidential
data**. For anything sensitive, use a provider you control under `restricted` or
`local-only` privacy.
:::

```python
GoogleFreeProvider(
    *,
    http_client=None,           # inject an HttpClient for testing
    timeout=10.0,               # seconds, > 0
    allow_html_fallback=True,   # allow the mobile-HTML endpoint after primary failure
)
```

There is no model and no API key; it translates each item individually.

- The **primary** endpoint is `translate.googleapis.com/translate_a/single`,
  returning JSON.
- When the primary call fails — a `403` rejecting the web surface, or a
  transient/response error — and `allow_html_fallback=True`, it retries through
  the **mobile HTML** endpoint `translate.google.com/m`, parsed with a bounded
  standard-library HTML parser (no Beautiful Soup). A non-`403` authentication
  error is not retried.
- It declares **both** endpoints as `recipient_endpoints`, so the privacy
  preflight validates the HTML fallback even when the primary later succeeds. Set
  `allow_html_fallback=False` to declare only the primary.

```python
from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import GoogleFreeProvider

config = TranslationConfig(
    source_language="en",   # or "auto" to let the endpoint detect
    target_language="fr",
    provider=GoogleFreeProvider(),
    privacy="public",
)
result = translate_csv("catalog.csv", config)
```

Because it is the default, both of these are equivalent to the above:

```python
# provider=None uses GoogleFreeProvider()
TranslationConfig(source_language="en", target_language="fr")
```

```bash
# CLI default provider is google-free
csv-trans -f catalog.csv -sl en -tl fr
```

CLI aliases `google-free`, `google`, `free`, and `default` all select this
adapter. Omitting `--provider` prints a one-time stderr warning before sending
cell text here.

## Echo (offline)

`EchoProvider` returns input text unchanged, or passes it through an injected
transform. It makes no network calls and needs no credentials — used for tests,
CI, and end-to-end checks of the CSV orchestration.

```python
EchoProvider(transform=None)
```

`transform` is an optional callable `(text, source_language, target_language) ->
str`; `source_language` may be `None`. With `transform=None`, the provider is a
pure identity — its output reconstructs the source exactly, which is what
verifies the [placeholder/chunking](/csv_trans/how-it-works/) round trip.

It declares `base_url=None` and `is_remote=False`, and is the **only**
endpointless provider accepted under `local-only` privacy (without a transform);
see [endpointless providers](/csv_trans/privacy-and-security/#the-local-only-threat-model-and-its-limits).

```python
from csv_trans import translate
from csv_trans.providers import EchoProvider

result = translate("catalog.csv", "en", "fr", provider=EchoProvider())
print(result.status.value)      # "success"
print(result.translated_cells)  # selected text cells, unchanged
```

A transform produces visibly different output while staying offline and
deterministic:

```python
from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import EchoProvider

def tag(text, source_language, target_language):
    return f"[{target_language}] {text}"

config = TranslationConfig(
    source_language="en",
    target_language="fr",
    provider=EchoProvider(transform=tag),
    privacy="public",
)
result = translate_csv("catalog.csv", config)
```

CLI aliases `echo` and `identity` select this provider; `--dry-run` uses it
internally to inspect selection without translating.

:::caution[Transform disables the local-only exemption]
The `local-only` endpointless exemption applies **only** to the exact built-in
`EchoProvider` *without* a transform. Injecting a transform makes it a
**rejected** endpointless provider under `local-only`
(`PrivacyViolation: local-only mode cannot verify endpoint for echo`). Use
`privacy="public"` for a transform, or the plain `EchoProvider()` for a
`local-only` offline run.
:::

## The response contract

Every provider receives `TranslationItem(id, text)` values with caller-owned,
stable IDs and must return one item per input, with the **same IDs in the same
order**. The engine re-validates each response and rejects it before writing
anything to the CSV when:

- an ID is missing, duplicated, or unexpected;
- the item count or order does not match the request;
- an ID or text field is not a string;
- a translation exceeds the per-item safety cap (`max(4096, len(source) * 8 +
  1024)` characters);
- a non-empty source produced empty text (unless `allow_empty_translations`);
- a translation is not representable in the output encoding.

Malformed structured output is classed `invalid_response` and gets the
[corrective retry then recursive split](/csv_trans/how-it-works/) path; an
encoding failure is classed `output_encoding` and split without a corrective
retry.

## Writing a custom provider

A provider needs four public attributes and one `translate` method.

```python
from csv_trans.providers import TranslationItem


class MyProvider:
    provider_id = "my-provider"      # stable ID used in telemetry and allowlists
    name = provider_id               # human-facing name
    base_url = "https://translation.example/v1"  # declared recipient endpoint
    is_remote = True                 # informational; not an enforceable boundary

    def translate(self, items, *, source_language, target_language):
        # source_language is None when the caller requested auto-detection.
        # Return ONE TranslationItem per input, with the SAME ids in the SAME order.
        results = []
        for item in items:
            translated_text = my_service(item.text, source_language, target_language)
            results.append(TranslationItem(item.id, translated_text))
        return results
```

### Required attributes

| Attribute | Type | Purpose |
| --- | --- | --- |
| `provider_id` | `str` | Stable identifier; appears in reports and is matched against `restricted` allowlists |
| `name` | `str` | Human-facing name (often equal to `provider_id`) |
| `base_url` | `str \| None` | The endpoint that receives text; used by privacy validation |
| `is_remote` | `bool` | Informational only — the engine validates the URL, not this flag |

### The `translate` method

- Signature: `translate(self, items, *, source_language, target_language)`.
- `items` is a sequence of `TranslationItem(id, text)`. `source_language` is
  `None` for auto-detect; `target_language` is always a non-empty string.
- Return a `list[TranslationItem]` (or a dict / iterable of `(id, text)` pairs)
  with **exactly the input IDs, in the input order**. The engine re-validates the
  [response contract](#the-response-contract) and rejects any mismatch before
  writing the CSV.
- An **optional** `translate_corrective(...)` method with the same signature is
  called on the corrective retry after invalid structured output; if absent, the
  engine retries `translate`.

### Raising errors the engine understands

Raise a `ProviderError` subclass from
[`csv_trans.exceptions`](/csv_trans/reference/python-api/) so recovery can classify the
failure. The category drives whether the engine retries, splits, or falls back:

```python
from csv_trans.exceptions import (
    ProviderTimeoutError,        # retryable transient
    ProviderRateLimitError,      # retryable transient (429)
    ProviderContextLimitError,   # triggers recursive / adaptive split
    ProviderResponseError,       # invalid_response -> corrective retry then split
    ProviderAuthenticationError, # terminal for this provider
    ProviderConfigurationError,  # terminal for this provider
)
```

Do not embed source text, response bodies, or credentials in exception messages
or attributes — reports serialize the engine's own safe wording, but logs and
error reporters that capture frame locals could otherwise leak them.

### Declaring multiple recipient endpoints

If a provider may contact more than one host (for example a primary and a
fallback), expose a `recipient_endpoints` property returning every possible
destination. Privacy preflight validates **all** of them, so an approved run
cannot later reach an unvalidated host:

```python
class MyProvider:
    provider_id = "my-provider"
    name = provider_id
    base_url = "https://primary.example/v1"
    is_remote = True

    @property
    def recipient_endpoints(self):
        return (self.base_url, "https://fallback.example/v1")

    def translate(self, items, *, source_language, target_language):
        ...
```

### Injecting an HTTP client

For an HTTP-based provider, accept an injectable client so it can be tested
offline. The built-in `UrllibHttpClient` implements the `HttpClient` protocol; a
fake client can return canned `HttpResponse` objects. An injected client **must
not follow redirects** and must return every HTTP status unchanged — following a
redirect can move a request to an unvalidated host and break the privacy
guarantee.

### Using it

A custom provider is just another object passed to `provider=` or
`fallback_providers=`:

```python
from csv_trans import TranslationConfig, translate_csv

config = TranslationConfig(
    source_language="en",
    target_language="fr",
    provider=MyProvider(),
    privacy="restricted",
    allowed_providers=("my-provider",),
)
result = translate_csv("catalog.csv", config)
```

:::caution
Custom providers and injected transports are **trusted extension code**, not an
OS egress sandbox — review them as part of your confidential-data boundary. See
the [threat model](/csv_trans/privacy-and-security/) for what `is_remote` and
`local-only` do and do not enforce.
:::

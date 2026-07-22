---
title: Privacy & security
description: The three network privacy modes, what enforces them at the transport layer, and the local-only threat model with its explicit limits.
---

`csv-trans` is a client library, not an offline translation model. Selected CSV
cell text reaches a provider unless you point it at a local endpoint. This page
states the privacy boundary, the transport controls that enforce it, and the
limits of those guarantees.

## Privacy modes

A privacy mode is the network boundary applied to selected cell text before it
reaches any provider. It is checked against the whole provider chain during
preflight and re-validated before every provider invocation — including retries,
split requests, and fallbacks. A rejected chain raises `PrivacyViolation`.

Set it with `privacy=` (a `PrivacyMode` or its string value) in
[`TranslationConfig`](/csv_trans/reference/python-api/), or `--privacy` on the CLI.

| Mode | Guarantee |
| --- | --- |
| `public` | Default. Accepts the no-key provider and any configured remote provider; validates each declared endpoint and records sanitized recipient hosts in telemetry. |
| `restricted` | Uses only the explicit `allowed_providers` allowlist and never substitutes a vendor automatically. Errors without a non-empty allowlist. |
| `local-only` | Allows loopback or explicitly approved local endpoints only. Rejects public destinations before translation and never falls back remotely. |

Under every mode each declared endpoint is validated: it must use `http`/`https`,
include a host, and carry no embedded credentials, query, or fragment.

### `public`

The default. Configured remote providers are accepted with no restriction on
which vendor receives your text. This is the mode the experimental Google
adapter runs under.

The CLI defaults to `public` and uses `google-free` when no provider is given.
It warns on stderr before an implicit, non-quiet, non-dry run; `--quiet` hides
the warning but does not prevent disclosure, and `--dry-run` performs selection
without contacting a provider.

:::caution
The no-key Google web provider is an **undocumented remote service** with no
availability, privacy, or contractual guarantee. Do not use it for confidential
data. Prefer `restricted`, or `local-only` with a model server you control.
:::

### `restricted`

Only providers whose name appears in `allowed_providers` may be used, and the
engine never substitutes a different vendor automatically. Selecting
`restricted` without a non-empty allowlist is an error.

```python
from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import OpenAICompatibleProvider

provider = OpenAICompatibleProvider(
    model="gpt-4o-mini",
    base_url="https://api.openai.com/v1",
    api_key="sk-...",
)
config = TranslationConfig(
    source_language="en",
    target_language="fr",
    provider=provider,
    privacy="restricted",
    allowed_providers=(provider.provider_id,),
)
```

On the CLI, `--allow-provider` names an allowed provider. When you pass
`--provider` explicitly under `restricted` and give no `--allow-provider`, the
chain's providers are allowed by default.

### `local-only`

Every declared endpoint must be a **loopback** address (`localhost`,
`127.0.0.0/8`, `::1`) or a host you list explicitly in `approved_local_hosts`
(CLI: `--approved-local-host`). Host matching is exact after case folding and
trailing-dot removal, and **no DNS resolution** is performed — a name is never
resolved to decide whether it is local. `local-only` never falls back to a
public provider.

```python
from csv_trans import TranslationConfig, translate_csv
from csv_trans.providers import OpenAICompatibleProvider

provider = OpenAICompatibleProvider(model="qwen3", base_url="http://localhost:11434/v1")
config = TranslationConfig(
    source_language="en",
    target_language="ko",
    provider=provider,
    privacy="local-only",
)
```

**The loopback / HTTP rule.** Loopback HTTP is accepted automatically. A
non-loopback approved host over plain HTTP requires an explicit insecure opt-in
(`allow_insecure_http=True` on the provider); the CLI applies that opt-in only
in `local-only` mode, and the host must still be in `--approved-local-host`.
Non-loopback endpoints otherwise require HTTPS.

**Endpointless providers.** `local-only` needs a declared destination to
validate. A custom provider that declares no endpoint is **rejected** even if it
self-reports `is_remote=False` — a self-reported flag is not an enforceable
boundary. The only exception is the exact built-in `EchoProvider` without an
injected transform (and without a shadowed `translate`/`translate_corrective`),
which the core can prove is offline. Local model providers must declare the
endpoint that receives text.

## What never leaves the machine

### Redaction guarantees

By default, structured results and logs redact configured credentials, source
text, translated values, and header names. A serialized report or `--json`
output is **content-free**: it carries file paths, status, counts, selection
decisions, sanitized recipient hosts (scheme/host/port only), and
engine-derived failure categories — never source text, translated text,
credentials, or (by default) header names. Provider failure messages are the
engine's own category wording, not a provider's raw message, which could
otherwise carry a source cell or an API key.

:::note
Redaction covers **content, not paths**. File paths remain in reports, so
protect reports when a path name is itself sensitive. You also remain
responsible for your process environment and any custom logging you add.
:::

### Transport enforcement

Transport- and configuration-level controls back the privacy modes:

- **No redirects.** The built-in transport (and any injected `HttpClient`, by
  contract) must not follow redirects, so a validated endpoint cannot silently
  move a request to another host. A `3xx` response is surfaced as an error.
- **No ambient proxies.** `HTTP_PROXY` / `HTTPS_PROXY` are ignored by the
  built-in transport so a request cannot be rerouted. Inject a proxy-aware
  `HttpClient` if you need a trusted proxy — and treat that proxy as a data
  recipient in its own right.
- **Bounded responses.** HTTP response bodies are capped at 4 MiB, and provider
  errors retain classifications and status codes but never response bodies.
- **Scoped credentials.** Ambient `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` are
  used only for the exact official vendor hosts; generic and custom destinations
  use separate `CSV_TRANS_*` variables so an official key is never forwarded
  onward. No flag accepts a literal API key (`--api-key-env` names an
  environment variable instead), and sensitive literal `--header` names are
  rejected.

## The `local-only` threat model and its limits

`local-only` verifies the configured network **destination** — every declared
endpoint must be loopback or an exact approved host, checked **without DNS
resolution**, and a provider's self-reported `is_remote=False` cannot override a
non-local URL. That is the whole of what it guarantees.

It does **not** guarantee, and cannot:

- **Trustworthiness of the local service.** A local model server may log
  prompts, retain requests, expose an insecure admin interface, or be reachable
  by other users. Its deployment, network, authentication, logs, model
  provenance, and retention remain the operator's responsibility.
- **An OS egress sandbox.** Privacy policy is not a Python or operating-system
  sandbox. A custom provider or an injected `HttpClient` is trusted extension
  code that can open an undeclared connection or otherwise violate the transport
  contract. This is why `local-only` rejects endpointless custom providers.
  Review extension code as part of the confidential-data boundary.

## Plaintext temporary files

To translate one stable input version, the engine writes a complete
byte-for-byte plaintext **snapshot** beside the source (or in
`snapshot_directory`), keeping it on the same storage boundary. Atomic CSV and
report publication also create plaintext **staging** and **rollback** files
beside their destinations. These are removed on normal completion and handled
failures, but an interpreter crash, forced termination, or power loss can leave
residue (`.csv-trans-*.snapshot`, `*.tmp`, `*.rollback`). Confidential
deployments should protect and encrypt every selected directory, restrict
access, and include orphaned files in retention and cleanup procedures.

No portable filesystem primitive can atomically commit two separate paths, so a
crash between the report and CSV commits can leave one file visible. Downstream
automation must **validate the report/CSV pair** rather than treat report
presence alone as proof of a completed CSV. See
[the report-first transaction](/csv_trans/how-it-works/).

## Spreadsheet formula injection

CSV is a data format, but spreadsheet programs may execute fields beginning with
`=`, `+`, `-`, or `@` as formulas. `csv-trans` preserves source values and
translations verbatim and does **not** add a protective prefix — normal CSV
quoting does not stop spreadsheet evaluation. Applications that open or
distribute output through spreadsheet software must apply a consumer-specific
formula-injection policy after translation.

## Reporting a vulnerability

Report suspected vulnerabilities privately through the repository's
[GitHub security advisory form](https://github.com/ML-Dev-Hub/csv_trans/security/advisories/new).
Do not open a public issue, and do not include API keys, CSV contents,
authorization headers, or customer data in a report.

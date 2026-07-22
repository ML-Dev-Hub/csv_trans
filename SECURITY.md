# Security policy

## Supported versions

| Version | Security updates |
| --- | --- |
| 2.0.x | Yes |
| 1.x and older | No |

Version 1.x uses an unsupported dependency stack and should not be used for
new deployments. Upgrade guidance is in [docs/MIGRATION_V2.md](docs/MIGRATION_V2.md).

## Reporting a vulnerability

Please report suspected vulnerabilities privately through the repository's
[GitHub security advisory form](https://github.com/ML-Dev-Hub/csv_trans/security/advisories/new).
Do not open a public issue for an undisclosed vulnerability or include API
keys, CSV contents, authorization headers, or customer data in a report.

Include, when available:

- The affected `csv-trans` and Python versions.
- The provider and privacy mode, without credentials or source text.
- A minimal synthetic reproduction.
- Expected impact and any known mitigations.

Maintainers will acknowledge a report, investigate it, and coordinate disclosure
and a release when appropriate. No response-time guarantee is currently offered.

## Translation data leaves the process

`csv-trans` is a client library, not an offline translation model. A provider
receives selected CSV cell text unless a caller uses a local endpoint:

- `public` permits the default no-key internet provider and explicitly
  configured remote fallbacks.
- `restricted` permits only providers explicitly selected by the caller and
  never changes vendors automatically.
- `local-only` accepts loopback or explicitly approved local endpoints and
  forbids public fallback.

The no-key Google web provider is an undocumented remote service. It offers no
availability, privacy, or contractual guarantee and must not be used for
confidential data. Use `local-only` with a model server you control when data
must remain on the local machine or network.

The CLI defaults to `public` privacy and uses `google-free` when no provider is
specified. It warns before an implicit non-quiet run; `--quiet` hides that
warning but does not prevent disclosure. `--dry-run` performs selection without
contacting a provider.

`local-only` verifies the configured network destination, not the
trustworthiness of the model service. A local server may log prompts, retain
requests, expose administration interfaces, or be accessible by other users.
Its deployment, network, authentication, logs, model provenance, and retention
remain the operator's responsibility.

Privacy policy is not a Python or operating-system sandbox. A custom provider
and an injected `HttpClient` are trusted extension code: either can open an
undeclared connection or otherwise violate the transport contract. For that
reason, `local-only` rejects endpointless custom providers even when they set
`is_remote=False`; only the exact built-in `EchoProvider` without an injected
transform is accepted without a declared endpoint. Review extension code as
part of the confidential-data boundary.

Version 2.0 is a Python library and CLI. It does not expose an inbound HTTP/REST
server, install model runtimes, or launch local model processes.

## Credential handling

- Prefer environment variables or in-memory configuration over source files
  and command history.
- Scope keys to the minimum permissions and budget required.
- Never commit `.env` files, keys, tokens, or provider responses.
- Rotate any credential that might have appeared in logs or an issue.
- Treat a custom base URL as a data recipient; HTTPS is required for non-local
  endpoints.
- The built-in transport ignores environment/system proxies. If an application
  injects a proxy-aware HTTP client, that proxy becomes a data recipient and
  must be included in its privacy review.
- Injected HTTP clients must return redirects without following them; otherwise
  they violate the provider transport contract and can invalidate endpoint
  guarantees.

Ambient `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` values are considered only for
the exact official vendor hosts. Generic OpenAI-compatible and custom vendor
destinations use separate custom or compatible `CSV_TRANS_*_API_KEY` variables
(or an explicit `--api-key-env`) so an ambient official credential is not
forwarded to another recipient.

The package redacts configured credentials, cell text, translated values, and
header names by default from structured results. File paths remain present, so
callers must protect reports when path names themselves are sensitive. Callers
also remain responsible for their process environment and custom logging.

## Spreadsheet formula injection

CSV is a data format, but spreadsheet programs may execute fields beginning
with characters such as `=`, `+`, `-`, or `@` as formulas. `csv-trans` preserves
source values and provider translations and does not add a protective prefix;
normal CSV quoting does not stop spreadsheet evaluation. Applications that
open or distribute output through spreadsheet software must apply a
consumer-specific formula-injection policy after translation.

## Plaintext temporary files

The engine creates a complete byte-for-byte plaintext source snapshot beside
the source by default, so it stays on the same storage boundary while
preventing a changing input from mixing two versions in one translation. Use
`snapshot_directory` / `--snapshot-directory` only to select another protected
location deliberately. Atomic CSV and report publication creates additional
plaintext staging and rollback files beside their destinations. These files
are removed on normal completion and handled exceptions, but an interpreter
crash, forced termination, or power failure can leave residue. Confidential
deployments should protect and encrypt every selected directory, restrict
access, and include orphaned csv-trans files in retention and cleanup
procedures.

CSV and JSON paths are each committed atomically. The engine rolls a report
back if the subsequent CSV commit raises, but operating systems do not provide
a portable atomic transaction across both paths. A crash in the inter-file
commit interval can leave one file visible, so downstream automation must
validate the pair rather than treating report presence alone as proof of a
completed CSV publication.

## Dependency and release security

The v2 runtime has no mandatory third-party dependencies. Build tooling is
isolated from the installed runtime. Releases are intended to be built in
GitHub Actions and published to PyPI through Trusted Publishing, without a
long-lived PyPI token. The build frontend and backend are version-pinned, and
workflow actions are pinned to full commit SHAs so a movable action tag cannot
change release code without review.

# Owner's local testing guide

This is the maintainer-only guide for testing `csv-trans` 2.0 on Windows and
Linux. The normal validation is one cross-platform Python command; you do
**not** need to translate PowerShell commands into Bash or Bash commands into
PowerShell.

`OWNER_LOCAL_TESTING.md` is an instruction file, not a program. Do not run
`python OWNER_LOCAL_TESTING.md`. Run the Python validation program shown below.

## What you normally need to do

Choose the instructions for the operating system you are currently using.
Paste commands into an operating-system terminal, **not** into a Python
`>>>` prompt:

- Windows commands go into PowerShell.
- Linux commands go into Bash.
- Copy only the commands inside a shaded code block. Do not copy the opening
  language label or the closing fence line.
- Keep that terminal open. The `$Python` (Windows) or `$PYTHON` (Linux)
  selection is remembered only in that terminal. If you open a new terminal,
  repeat the operating system's setup block.

Running both operating systems locally is useful, but it is not mandatory when
the complete Windows and Linux GitHub Actions jobs pass before release.

The validation program:

- uses a unique operating-system temporary directory;
- never modifies or installs into your current development environment;
- does not configure a live provider; the current suite is audited to use only
  fakes, local loopback HTTP servers, and the offline Echo provider;
- stops immediately when a required command fails;
- removes its temporary directory after success;
- retains that directory after failure, once created, so it can be inspected;
- checks that repository status is exactly the same before and after the run.

### Windows: exact commands

Prerequisites:

- Git available as `git`;
- CPython 3.11, 3.12, 3.13, or 3.14 available as `python`;
- PowerShell or the PowerShell terminal in VS Code.

Open a new PowerShell window. If this checkout is at `I:\csv_trans`, paste
this entire block and press Enter:

```powershell
Set-Location -LiteralPath "I:\csv_trans" -ErrorAction Stop
$Python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
& $Python --version
git status --short
& $Python .\tools\owner_validate.py
```

The first line selects this repository. The second line stores the exact Python
program in `$Python`; `& $Python` runs that program. Wait for validation to
finish. The Windows `py` launcher is **not** required.

If the version shown is not CPython 3.11, 3.12, 3.13, or 3.14, paste this
fallback block after replacing the Python path:

```powershell
Set-Location -LiteralPath "I:\csv_trans" -ErrorAction Stop
$Python = "C:\full\path\to\python.exe"
& $Python --version
git status --short
& $Python .\tools\owner_validate.py
```

Replace `C:\full\path\to\python.exe` with a real path; do not type the
placeholder literally. To list Python programs visible to PowerShell:

```powershell
Get-Command python -All
```

### Linux: exact commands

Prerequisites:

- Git, Bash, CPython 3.11 through 3.14, and that interpreter's `venv`
  component;
- normal Linux utilities and certificate configuration needed by `pip`.

For Debian or Ubuntu, the basic packages are commonly installed with:

```bash
sudo apt-get update
sudo apt-get install git python3 python3-venv
```

For Fedora, the basic packages are commonly installed with:

```bash
sudo dnf install git python3
```

Distribution package names and default Python versions vary. Verify that
`python3 --version` reports 3.11, 3.12, 3.13, or 3.14. Use `sudo` only for
installing operating-system packages; run validation as your normal user.

Open a Bash terminal. Replace `$HOME/src/csv_trans` below if your checkout is
somewhere else, then paste this entire block:

```bash
cd "$HOME/src/csv_trans" || exit 1
PYTHON="$(type -P python3)" || exit 1
[[ -n "$PYTHON" && -x "$PYTHON" ]] || exit 1
"$PYTHON" --version
git status --short
"$PYTHON" tools/owner_validate.py
```

The first line selects this repository and stops if the path is wrong. The next
two lines select and verify a real Python executable; `"$PYTHON"` runs that
exact program. If using WSL,
clone and test under its Linux filesystem, such as `~/src/csv_trans`, rather
than `/mnt/c/...` or `/mnt/i/...`; the latter can hide Linux filesystem and
symbolic-link behavior.

If the version shown is unsupported, paste this fallback block after changing
the interpreter name if needed:

```bash
cd "$HOME/src/csv_trans" || exit 1
PYTHON="$(type -P python3.12)" || exit 1
[[ -n "$PYTHON" && -x "$PYTHON" ]] || exit 1
"$PYTHON" --version
git status --short
"$PYTHON" tools/owner_validate.py
```

Change `python3.12` to the real installed command if needed. If `type -P`
prints nothing, that Python version is not installed.

If Linux reports that `ensurepip` is unavailable while creating a virtual
environment, install the `venv` package matching that exact interpreter.

## Successful output

The current source suite runs exactly 171 tests. After successful cleanup, the
final output from a complete run must end with:

```text
FULL LOCAL VALIDATION PASSED
```

That banner plus exit code `0` means the run passed. To display the most
recent program's numeric exit code immediately after it finishes, use
`$LASTEXITCODE` in PowerShell or `echo $?` in Bash. Do this before running
another command, because the stored exit code can then change.

On Windows without Developer Mode or symbolic-link privilege, these two
specific skips are accepted:

- output symbolic-link rejection;
- report symbolic-link rejection.

The summary will say `171 tests, 2 platform skips`. Windows with symbolic-link
privilege can report zero skips. A normal Linux run must report zero skips; the
runner fails a Linux validation containing any skip.

The validation process exits with:

| Exit | Meaning |
| ---: | --- |
| `0` | Every selected validation check passed. |
| `1` | A test, build, installation, metadata, or repository check failed. |
| `2` | The command-line options were invalid; read the usage message. |
| `130` | Validation was interrupted with Ctrl+C. |

For exit 1, read the first `VALIDATION FAILED` message. Exit 2 prints an
option-usage message, and Ctrl+C prints `VALIDATION INTERRUPTED`. If a
temporary workspace was already created, it is retained for diagnosis. Start
the next attempt from the beginning rather than reusing that workspace.

## What the full command checks

The one-command workflow performs all mandatory local release checks:

1. Confirms the checkout, Git root, version `2.0.0`, supported CPython, and
   non-optimized interpreter mode.
2. Hashes and copies the complete current nonignored Git working tree into an
   isolated snapshot, rejecting unsafe paths and symbolic links.
3. Creates a clean virtual environment and runs the entire offline suite.
4. Verifies source import, module CLI, byte compilation, and Git whitespace.
5. Installs pinned build tools only inside the temporary environment.
6. Builds exactly one wheel and one source distribution.
7. Verifies every expected packaged file and hash against the snapshot; checks
   archive safety, `py.typed`, zero runtime requirements, and absence of
   owner-only or test-machine residue.
8. Installs and tests the wheel outside the source checkout.
9. Installs and tests the sdist outside the source checkout.
10. Verifies `csv-trans`, the compatibility command `csv_trans`,
    `python -m csv_trans`, metadata, and a deterministic Echo translation.
11. Confirms that validation did not alter repository status or any source
    file hash.

The test suite and Echo checks are offline. Installing `setuptools==83.0.0`
and `build==1.5.0` can access the configured Python package index unless a
wheelhouse is supplied.

## Useful runner options

Show every available option:

Windows PowerShell:

```powershell
& $Python .\tools\owner_validate.py --help
```

Linux Bash:

```bash
"$PYTHON" tools/owner_validate.py --help
```

### Quick source-only re-test

This skips package builds and clean artifact installations. It is useful while
developing, but it does not replace the full command before release.
Its successful final line is `SOURCE VALIDATION PASSED`.

Windows:

```powershell
& $Python .\tools\owner_validate.py --tests-only
```

Linux:

```bash
"$PYTHON" tools/owner_validate.py --tests-only
```

### Keep artifacts and environments

The runner normally deletes its unique temporary workspace after success. To
keep the wheel, sdist, smoke outputs, and environments, add:

```text
--keep-workdir
```

The runner prints the exact retained location. Delete only that printed
`csv-trans-owner-validation-*` directory after inspection.

### Linux `noexec` temporary directory

If Linux reports `Permission denied` while starting a program inside
`/tmp/csv-trans-owner-validation-...`, the system temporary directory is
probably mounted with `noexec`. Create a private executable work root
**outside this repository**, then run:

```bash
mkdir -p "$HOME/.cache/csv-trans-validation-work"
"$PYTHON" tools/owner_validate.py --work-root "$HOME/.cache/csv-trans-validation-work"
```

The runner still creates and safely removes a unique child directory. The
`--work-root` directory itself is retained.

Every child command has a 300-second timeout by default. On an unusually slow
machine, increase it explicitly, for example:

Windows PowerShell:

```powershell
& $Python .\tools\owner_validate.py --command-timeout 600
```

Linux Bash:

```bash
"$PYTHON" tools/owner_validate.py --command-timeout 600
```

### Run package validation from a wheelhouse

The source suite needs no internet. Package validation additionally needs
build tools. The blocks below assume the validation machine can temporarily
reach its Python package index; they download the pinned tools, validate, and
then clean up. The downloader uses no global pip cache.

Windows PowerShell:

```powershell
$WheelRoot = Join-Path ([IO.Path]::GetTempPath()) ("csv-trans-wheelhouse-" + [guid]::NewGuid())
$Wheelhouse = Join-Path $WheelRoot "wheels"
$DownloadVenv = Join-Path $WheelRoot "download-venv"
New-Item -ItemType Directory -Path $Wheelhouse | Out-Null
& $Python -m venv $DownloadVenv
if ($LASTEXITCODE -ne 0) { throw "Downloader environment creation failed; retained: $WheelRoot" }
& "$DownloadVenv\Scripts\python.exe" -m pip download --no-cache-dir --dest $Wheelhouse setuptools==83.0.0 build==1.5.0
if ($LASTEXITCODE -ne 0) { throw "Wheel download failed; retained: $WheelRoot" }
& $Python .\tools\owner_validate.py --wheelhouse $Wheelhouse
if ($LASTEXITCODE -ne 0) { throw "Validation failed; retained: $WheelRoot" }
$ResolvedWheelRoot = (Resolve-Path -LiteralPath $WheelRoot).Path
$ExpectedParent = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd("\")
if ([IO.Path]::GetDirectoryName($ResolvedWheelRoot) -ne $ExpectedParent -or [IO.Path]::GetFileName($ResolvedWheelRoot) -notlike "csv-trans-wheelhouse-*") { throw "Refusing unexpected cleanup path: $ResolvedWheelRoot" }
Remove-Item -LiteralPath $ResolvedWheelRoot -Recurse -Force -ErrorAction Stop
```

Linux Bash:

```bash
(
set -e
VALIDATION_WORK_ROOT="$HOME/.cache/csv-trans-validation-work"
mkdir -p "$VALIDATION_WORK_ROOT"
WHEEL_ROOT="$(mktemp -d "$VALIDATION_WORK_ROOT/csv-trans-wheelhouse.XXXXXX")"
WHEELHOUSE="$WHEEL_ROOT/wheels"
"$PYTHON" -m venv "$WHEEL_ROOT/download-venv"
mkdir -p "$WHEELHOUSE"
"$WHEEL_ROOT/download-venv/bin/python" -m pip download --no-cache-dir --dest "$WHEELHOUSE" setuptools==83.0.0 build==1.5.0
"$PYTHON" tools/owner_validate.py --work-root "$VALIDATION_WORK_ROOT" --wheelhouse "$WHEELHOUSE"
case "$WHEEL_ROOT" in
  "$VALIDATION_WORK_ROOT"/csv-trans-wheelhouse.*) rm -rf -- "$WHEEL_ROOT" ;;
  *) echo "Refusing unexpected cleanup path: $WHEEL_ROOT" >&2; exit 1 ;;
esac
)
```

The runner uses `--no-index` when a wheelhouse is supplied. Do not commit the
wheelhouse.

For a separate air-gapped machine, run only through the `pip download` line
on an online machine with the same operating system and Python version. Copy
the `wheels` directory—not the downloader environment—to the offline machine.
On the offline machine, replace the example copied path and run:

Windows PowerShell:

```powershell
$Wheelhouse = "D:\full\path\to\copied\wheels"
& $Python .\tools\owner_validate.py --wheelhouse $Wheelhouse
```

Linux Bash:

```bash
WHEELHOUSE="$HOME/full/path/to/copied/wheels"
"$PYTHON" tools/owner_validate.py --wheelhouse "$WHEELHOUSE"
```

On Linux with `noexec /tmp`, add
`--work-root "$HOME/.cache/csv-trans-validation-work"` to that final command.

## Run one test group manually

Normally use the runner. These commands are useful only when diagnosing a
failure and can be run directly from the repository root.

Windows:

```powershell
& $Python -B -m unittest tests.test_github_issue_regressions -v
& $Python -B -m unittest tests.test_http_transport_integration -v
& $Python -B -m unittest tests.test_privacy_and_atomicity -v
& $Python -B -m unittest tests.test_recovery_and_reporting -v
& $Python -B -m unittest tests.test_v2_regressions -v
```

Linux:

```bash
"$PYTHON" -B -m unittest tests.test_github_issue_regressions -v
"$PYTHON" -B -m unittest tests.test_http_transport_integration -v
"$PYTHON" -B -m unittest tests.test_privacy_and_atomicity -v
"$PYTHON" -B -m unittest tests.test_recovery_and_reporting -v
"$PYTHON" -B -m unittest tests.test_v2_regressions -v
```

The GitHub regression group explicitly covers issues #14 and #15.

## Optional live-provider testing

Live checks are separate from the mandatory validator. They can contact an
external service, consume quota, or incur cost. Every check uses only this
fixed synthetic sentence:

```text
Hello from the csv-trans owner live test.
```

Never use confidential, customer, personal, production, or secret data. The
live runner creates a unique temporary directory, selects exactly one cell,
uses batch size one, limits the timeout to 30 seconds, disables core retries,
validates the output and a cell-content- and credential-free report, and
cleans up after success. It never invents a fallback provider.

Run live checks only after `owner_validate.py` has passed.

### First test the live runner without a network

Echo sends nothing outside the process.

Windows:

```powershell
& $Python .\tools\owner_live_check.py echo
```

Linux:

```bash
"$PYTHON" tools/owner_live_check.py echo
```

The final line must be `LIVE PROVIDER CHECK PASSED`.

### Google no-key check

This experimental check can try the adapter's two declared Google endpoints.
It is for public synthetic text only.

Windows PowerShell:

```powershell
& $Python .\tools\owner_live_check.py google-free
```

Linux Bash:

```bash
"$PYTHON" tools/owner_live_check.py google-free
```

A failure can mean rate limiting, network policy, or an undocumented endpoint
change. It does not invalidate the offline suite, but investigate it before
advertising the adapter as currently operational.

### Hosted model checks

The runner securely prompts for the API key, so the key is not placed in
command history. Use an exact model ID enabled for the account. Every
all-capital value below is a placeholder:

- replace `OPENAI_MODEL_ID` or `ANTHROPIC_MODEL_ID` with the exact model ID;
- replace `QWEN_MODEL_ID` or `DEEPSEEK_MODEL_ID` with the exact model ID;
- replace `VERIFIED_QWEN_BASE_URL` or `VERIFIED_DEEPSEEK_BASE_URL` with the
  provider-owned API base URL.

Do not run a hosted example with those placeholder words unchanged. After you
press Enter, type the API key only at the hidden `API key:` prompt.

OpenAI, Windows PowerShell:

```powershell
& $Python .\tools\owner_live_check.py openai --model "OPENAI_MODEL_ID"
```

OpenAI, Linux Bash:

```bash
"$PYTHON" tools/owner_live_check.py openai --model 'OPENAI_MODEL_ID'
```

Anthropic, Windows PowerShell:

```powershell
& $Python .\tools\owner_live_check.py anthropic --model "ANTHROPIC_MODEL_ID"
```

Anthropic, Linux Bash:

```bash
"$PYTHON" tools/owner_live_check.py anthropic --model 'ANTHROPIC_MODEL_ID'
```

Qwen, Windows PowerShell:

```powershell
& $Python .\tools\owner_live_check.py qwen --model "QWEN_MODEL_ID" --base-url "VERIFIED_QWEN_BASE_URL"
```

Qwen, Linux Bash:

```bash
"$PYTHON" tools/owner_live_check.py qwen --model 'QWEN_MODEL_ID' --base-url 'VERIFIED_QWEN_BASE_URL'
```

DeepSeek, Windows PowerShell:

```powershell
& $Python .\tools\owner_live_check.py deepseek --model "DEEPSEEK_MODEL_ID" --base-url "VERIFIED_DEEPSEEK_BASE_URL"
```

DeepSeek, Linux Bash:

```bash
"$PYTHON" tools/owner_live_check.py deepseek --model 'DEEPSEEK_MODEL_ID' --base-url 'VERIFIED_DEEPSEEK_BASE_URL'
```

Qwen and DeepSeek base URLs must be current, verified provider-owned
OpenAI-compatible endpoints, never arbitrary third-party proxies. The runner
pins official OpenAI and Anthropic checks to their official hosts.

For noninteractive use, put the key in an environment variable and add
`--key-env VARIABLE_NAME`. Do not put the key itself on the command line.

### Local OpenAI-compatible model

Start the server separately and verify `/chat/completions` support. No key is
used by default. Replace `LOCAL_MODEL_ID` with the exact model name loaded by
your server. Change the example base URL if the server listens elsewhere.

Windows PowerShell:

```powershell
& $Python .\tools\owner_live_check.py openai-compatible --model "LOCAL_MODEL_ID" --base-url "http://127.0.0.1:11434/v1" --target-language ko
```

Linux Bash:

```bash
"$PYTHON" tools/owner_live_check.py openai-compatible --model 'LOCAL_MODEL_ID' --base-url 'http://127.0.0.1:11434/v1' --target-language ko
```

Add `--prompt-for-key` when the local server requires a bearer key. For a
trusted non-loopback LAN server, also add
`--approved-local-host exact.host.name`. Use the exact hostname, not a URL or
wildcard. `local-only` constrains network placement, but the server can still
log prompts.

### Interpret a live result

| Exit | Meaning |
| ---: | --- |
| `0` | Provider, output, recipient hosts, counters, and report all passed. |
| `1` | Configuration, provider, publication, or report validation failed. |
| `2` | Safe partial output was published, or command-line usage was invalid. |

On exit 1 or 2, the runner retains its temporary workspace for inspection if
one was created. A partial result proves safe failure reporting only; fix the
provider/model response and rerun until exit 0.

Do not assert one exact generated phrase. The runner instead requires one
translated cell, zero failed cells, the expected provider and recipient hosts,
a nonempty output, and a report containing no source text, translated text,
authorization field, or key.

Use `--keep-workdir` to retain a successful check. Show all options with:

Windows PowerShell:

```powershell
& $Python .\tools\owner_live_check.py --help
```

Linux Bash:

```bash
"$PYTHON" tools/owner_live_check.py --help
```

## Release handoff

After the full runner succeeds on the chosen local platform:

1. Review the final source diff and `CHANGELOG.md`.
2. Commit the release candidate.
3. Wait for CPython 3.11 through 3.14 GitHub Actions jobs on Windows, Linux,
   and macOS.
4. Follow `docs/RELEASING.md` for the annotated `v2.0.0` tag.

Do not upload the runner's local artifacts manually. The protected release
workflow rebuilds, validates, and publishes the tagged source through PyPI
Trusted Publishing.

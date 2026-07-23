# Local test bed

The normal test suite is deterministic, offline, and uses Python's standard
`unittest` runner. Fake transports and providers replace all network calls, so
running the suite never uploads CSV content or consumes provider quota.

## Supported interpreters

Version 2 supports CPython 3.11, 3.12, 3.13, and 3.14. GitHub Actions tests all
four versions on Linux, macOS, and Windows. For local work, use any one of those
versions and rely on CI for the full matrix.

## Create an isolated environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e .
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

POSIX shells:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
.venv/bin/python -m unittest discover -s tests -v
```

The editable installation has no runtime requirements beyond the standard
library.

## Build and installed-distribution smoke test

Install the build frontend only in the development environment:

```bash
python -m pip install build==1.5.0
python -m build
python -c "import glob, subprocess, sys; wheel = glob.glob('dist/*.whl'); assert len(wheel) == 1, wheel; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--force-reinstall', '--no-deps', wheel[0]])"
python -m pip check
python -c "import importlib.metadata as m; assert m.version('csv-trans') == '2.0.1'; assert not m.requires('csv-trans')"
csv-trans --help
csv_trans --help
python -c "import glob, subprocess, sys; sdist = glob.glob('dist/*.tar.gz'); assert len(sdist) == 1, sdist; subprocess.check_call([sys.executable, '-m', 'pip', 'install', '--force-reinstall', '--no-deps', sdist[0]])"
python -m pip check
python -c "import importlib.metadata as m; assert m.version('csv-trans') == '2.0.1'; assert not m.requires('csv-trans')"
csv-trans --help
```

Run the import and console checks from outside the repository when verifying a
release artifact. That prevents the working tree from shadowing the installed
wheel.

## Test layers

- Core tests cover CSV dialects, encodings, stable coordinates, column
  selection, header policy, chunk reassembly, atomic output, cancellation, and
  structured results.
- Provider contract tests use fake HTTP transports and require exact output IDs
  and order. They cover redaction, authentication, rate limits, malformed JSON,
  response-size limits, and endpoint policy.
- Privacy tests prove that `restricted` never changes vendors automatically and
  `local-only` rejects public hosts before submitting text.
- CLI tests verify both executable names, exit codes, JSON reports, environment
  configuration, and that error output contains no cell text or credentials.
- Packaging tests build both distributions, install the wheel and source
  distribution without runtime dependencies, and verify metadata and the
  `py.typed` marker.

## Live provider checks

Live checks are intentionally excluded from pull requests. If maintainers add a
manual live suite, it must:

- Require an explicit opt-in marker or script.
- Use synthetic, non-confidential text only.
- Enforce a small request and cost budget.
- Never print credentials, authorization headers, or provider response bodies.
- Never run automatically for pull requests from forks.

The built-in `echo` provider is the preferred end-to-end test provider because
it exercises CSV orchestration without a network or secret.

An unmocked local CLI smoke test can be run after installation:

```bash
python -c "from pathlib import Path; Path('cli-smoke.csv').write_text('id,text\n1,hello\n', encoding='utf-8')"
csv-trans -f cli-smoke.csv -sl en -tl fr --provider echo --columns text --output cli-smoke.out.csv --report cli-smoke.report.json --privacy local-only --quiet
python -c "import json; report=json.load(open('cli-smoke.report.json', encoding='utf-8')); assert report['status'] == 'success'"
```

The CI matrix runs this installed-console-script path on every supported Python
and operating system.

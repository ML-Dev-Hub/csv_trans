# Contributing to csv-trans

Thank you for helping improve `csv-trans`. Version 2 keeps its production
runtime dependency-free, so proposals that add a mandatory package should first
explain why the capability cannot be implemented safely with the standard
library or as an optional integration.

## Development setup

Use any supported CPython version from 3.11 through 3.14:

```bash
python -m venv .venv
python -m pip install --upgrade pip
python -m pip install -e .
python -m unittest discover -s tests -v
```

See [TESTING.md](TESTING.md) for Windows commands, packaging checks, and the
full local test bed.

## Pull requests

1. Fork the repository and create a focused branch.
2. Add or update deterministic tests for every behavior change.
3. Run the offline unit suite. Normal tests must not contact a provider.
4. Update the README, migration guide, and changelog when public behavior
   changes.
5. Open a pull request describing the problem, approach, privacy implications,
   and verification performed.

Provider changes must preserve stable item IDs, output ordering, bounded retry
behavior, privacy-mode enforcement, and redaction of credentials and cell text.
Use synthetic strings in tests and examples.

## Reporting problems

Use the issue templates for ordinary bugs and feature requests. Report security
issues privately as described in [SECURITY.md](SECURITY.md).

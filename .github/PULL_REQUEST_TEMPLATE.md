## Summary

Describe the problem and the focused change that solves it.

## Verification

- [ ] `python -m unittest discover -s tests -v`
- [ ] Public behavior and migration documentation are updated when needed.
- [ ] Tests use synthetic data and make no unapproved live provider calls.
- [ ] The runtime remains dependency-free, or an optional dependency decision is explained.

## Privacy and provider impact

State which providers may receive text, how all privacy modes behave, and whether
the change affects credentials, retries, fallbacks, quotas, logs, or reports.
Write `None` if the change has no provider or privacy impact.

## Compatibility

Describe CLI, Python API, result-schema, CSV-round-trip, or packaging changes.

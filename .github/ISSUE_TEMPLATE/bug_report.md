---
name: Bug report
about: Report a reproducible csv-trans defect
title: "[Bug]: "
labels: bug
assignees: ""

---

# Before submitting

- Search existing issues first.
- Use synthetic CSV text. Do not attach confidential data, API keys,
  authorization headers, or unredacted provider responses.
- Report security vulnerabilities privately as described in `SECURITY.md`.

## Environment

- csv-trans version:
- Python version:
- Operating system:
- Installation method:
- Provider ID:
- Privacy mode:

## Reproduction

Provide the smallest synthetic CSV and Python snippet or CLI command that
reproduces the problem. Replace secrets with `<redacted>`.

```text
# synthetic input
```

```text
# command or Python snippet
```

## Expected behavior

What should have happened?

## Actual behavior

Include the exit code, result status, sanitized traceback, and failure category
when available. Never include source cell contents from a real dataset.

## Additional context

Mention encoding, delimiter, selected columns, local model server, or network
conditions when relevant.

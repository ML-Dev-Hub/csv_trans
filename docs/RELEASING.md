# Release process

Releases are built from a version tag and published by
`.github/workflows/release.yml`. Maintainers should not upload artifacts from a
workstation.

## One-time repository setup

1. Create a protected GitHub Actions environment named `pypi`.
2. Configure the `ML-Dev-Hub/csv_trans` project as a Trusted Publisher on PyPI,
   using workflow `release.yml` and environment `pypi`.
3. Require approval for the `pypi` environment when the repository's release
   policy calls for it.

No `PYPI_API_TOKEN` secret is required. The publish job receives a short-lived
OIDC identity through `id-token: write`.

## Prepare a release

1. Update `project.version` in `pyproject.toml`.
2. Change the matching changelog section from `Unreleased` to the release date.
3. Confirm that migration and security documentation reflect public changes.
4. Run the full offline suite and build smoke test from `TESTING.md`.
5. Merge the release preparation and wait for the complete CI matrix to pass.

## Publish

Create an annotated tag whose version exactly matches `pyproject.toml`. A
leading `v` is accepted:

```bash
git tag -a v2.0.0 -m "csv-trans 2.0.0"
git push origin v2.0.0
```

The release workflow verifies the tag, reruns tests, builds the wheel and source
distribution with pinned build tooling, installs and inspects both formats, and
publishes the same artifacts through PyPI Trusted Publishing. External actions
are pinned to full immutable commit SHAs. Dependabot is configured for GitHub
Actions updates; maintainers must review those proposals before changing a pin.

PyPI versions are immutable. If publishing succeeds but a later release step
fails, do not reuse or move the tag and do not attempt to replace the files.
Prepare a new patch version instead.

"""Regression tests for the credential-disclosure fix in csv_trans.cli.

Covers two reproduced leak paths:
  1. ``--api-key SECRET`` prefix-abbreviation-binding onto ``--api-key-env`` and
     echoing SECRET as an env-var name.
  2. ``-key/--token/--password SECRET`` triggering an ``unrecognized arguments``
     error that echoes SECRET.

Both must now exit nonzero with the value ABSENT from stderr, while v1 CLI
compatibility (underscore/hyphen long-names, echo provider) keeps working.
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path

try:
    import pytest
except ImportError as exc:  # stdlib-only CI runs skip this optional suite
    raise unittest.SkipTest(f"optional test dependency not installed: {exc.name}") from exc

from csv_trans import cli

_SECRET = "sk-LIVE-SUPERSECRET-9f3aQ"


@pytest.mark.parametrize(
    "flag",
    ["--api-key", "-key", "--token", "--password", "--secret", "--bearer", "-apikey", "-api-key"],
)
def test_credential_flag_rejected_without_echoing_value(flag, capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["-f", "x.csv", "-sl", "en", "-tl", "fr", flag, _SECRET])
    # argparse errors exit with code 2 (nonzero).
    assert exc.value.code != 0
    captured = capsys.readouterr()
    assert _SECRET not in captured.err
    assert _SECRET not in captured.out


def test_bare_api_key_flag_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc:
        cli.main(["-f", "x.csv", "-sl", "en", "-tl", "fr", "--api-key"])
    assert exc.value.code != 0
    err = capsys.readouterr().err
    assert "--api-key" in err
    assert "--api-key-env" in err  # points user at the safe path


def _write_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["text"])
        writer.writerow(["hello"])


def test_v1_style_invocation_still_succeeds(tmp_path):
    source = tmp_path / "x.csv"
    _write_csv(source)
    code = cli.main(
        [
            "-f",
            str(source),
            "-sl",
            "en",
            "-tl",
            "fr",
            "-fs",
            ",",
            "--provider",
            "echo",
            "-o",
            str(tmp_path / "out.csv"),
        ]
    )
    assert code == 0


def test_v1_underscore_long_names_still_parse():
    parser = cli.build_parser()
    ns = parser.parse_args(
        [
            "--file_path",
            "x.csv",
            "--source_language",
            "en",
            "--target_language",
            "fr",
            "--file_separator",
            ",",
        ]
    )
    assert ns.input_path == "x.csv"
    assert ns.source_language == "en"
    assert ns.target_language == "fr"
    assert ns.delimiter == ","


def test_v1_hyphen_long_names_still_parse():
    parser = cli.build_parser()
    ns = parser.parse_args(
        [
            "--file-path",
            "y.csv",
            "--source-language",
            "de",
            "--target-language",
            "es",
            "--file-separator",
            ";",
        ]
    )
    assert ns.input_path == "y.csv"
    assert ns.delimiter == ";"


def test_api_key_env_still_binds_exactly():
    parser = cli.build_parser()
    ns = parser.parse_args(["-f", "x.csv", "-sl", "en", "-tl", "fr", "--api-key-env", "MY_ENV"])
    assert ns.api_key_env == "MY_ENV"


def test_separatorless_secret_header_is_rejected_without_echoing_value():
    with pytest.raises(ValueError) as exc:
        cli._parse_headers(["sessiontoken=" + _SECRET])
    assert _SECRET not in str(exc.value)

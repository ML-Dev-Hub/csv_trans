"""Allow ``python -m csv_trans`` to behave like the console script."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())

"""Compatibility shim for tools that still invoke ``python setup.py``.

All project metadata and build configuration live in ``pyproject.toml``.
New installations should use ``python -m pip install .`` and releases should
use ``python -m build``.
"""

import setuptools
from setuptools import setup


if __name__ == "__main__":
    major = int(setuptools.__version__.split(".", 1)[0])
    if major < 77:
        raise SystemExit(
            "the setup.py compatibility shim requires setuptools>=77; "
            "use `python -m pip install .` for an isolated modern build"
        )
    setup()

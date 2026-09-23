"""Small helpers the generator's tests share."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path
from types import ModuleType

REPO = Path(__file__).resolve().parent.parent


def ruff_check(*paths: Path, ignore: tuple[str, ...] = ()) -> str:
    """Run ruff with this repository's configuration, wherever the files are; an empty string means clean."""
    command = [sys.executable, "-m", "ruff", "check", "--no-cache", "--config", str(REPO / "pyproject.toml")]
    if ignore:
        command += ["--ignore", ",".join(ignore)]
    result = subprocess.run([*command, *map(str, paths)], cwd=REPO, capture_output=True, text=True, check=False)
    return "" if result.returncode == 0 else result.stdout + result.stderr


def collected(directory: Path) -> int:
    """How many tests pytest collects from a generated suite, run as a separate process."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", str(directory), "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=REPO, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return int(result.stdout.strip().splitlines()[-1].split()[0])


def load_module(path: Path) -> ModuleType:
    """Import a generated module from its file, under its own file name, so model rebuilding sees its globals."""
    name = f"generated_{path.stem}_{abs(hash(str(path)))}"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

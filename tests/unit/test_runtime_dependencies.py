"""What the package declares is what `src/` imports (#111).

A consumer installs `[project].dependencies` and nothing else. Five of the eight
were there for the examples and the tests — FastAPI, uvicorn, uvloop,
strands-agents-tools — or for nothing at all (pydantic-settings), and every
consumer installed them anyway.

The other direction matters as much: the suite runs with the `dev` group, which
brings the examples' stack along, so a module the package imports but does not
declare would pass every test and fail on a clean install.
"""

import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "mongodb_session_manager"

# The hooks import botocore's exceptions and `Config`. boto3 pins botocore to
# its own release line, so it arrives with boto3 and is not declared apart.
PROVIDED_BY = {"botocore": "boto3"}


def _normalize(name: str) -> str:
    """PEP 503 name: `strands_agents` and `Strands-Agents` are the same project."""
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_dependencies() -> set[str]:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    names = (
        re.split(r"[\s<>=!~;\[]", spec, maxsplit=1)[0]
        for spec in pyproject["project"]["dependencies"]
    )
    return {_normalize(name) for name in names}


def imported_modules() -> set[str]:
    """Top-level modules the package imports, stdlib and itself excluded."""
    modules = set()
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(), filename=str(path))):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.add(node.module.split(".")[0])
    return modules - set(sys.stdlib_module_names) - {PACKAGE.name}


def imported_distributions() -> dict[str, str]:
    """Distribution that answers for each imported module."""
    owners = packages_distributions()
    result = {}
    for module in imported_modules():
        assert module in owners, f"no installed distribution provides {module!r}"
        distribution = _normalize(owners[module][0])
        result[module] = PROVIDED_BY.get(distribution, distribution)
    return result


class TestRuntimeDependencies:
    def test_every_declared_dependency_is_imported_by_the_package(self):
        unused = declared_dependencies() - set(imported_distributions().values())

        assert not unused, (
            f"declared but never imported by src/: {sorted(unused)}. "
            "What only the examples or the tests use belongs in a dependency group."
        )

    def test_every_import_of_the_package_is_declared(self):
        declared = declared_dependencies()
        undeclared = {
            module: distribution
            for module, distribution in imported_distributions().items()
            if distribution not in declared
        }

        assert not undeclared, (
            f"imported by src/ but not declared: {undeclared}. "
            "The tests would not notice: the dev group installs it."
        )

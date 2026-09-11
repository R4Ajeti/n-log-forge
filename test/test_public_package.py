"""Public import, repository packaging, documentation, and example contracts."""

from __future__ import annotations

import ast
import inspect
import json
import os
import subprocess
import sys
import tomllib
from dataclasses import fields
from pathlib import Path

import n_log_forge
from core.constant.configuration_constant import ENVIRONMENT_KEYS_MAPPING, PACKAGE_RULES_KEY_STR
from core.helper.event import Event

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PUBLIC_API = {
    "logger",
    "getLogger",
    "configure",
    "setPackageLevel",
    "resetPackageLevel",
    "flush",
    "shutdown",
}
_PUBLIC_LOGGER_METHODS = {
    "critical",
    "debug",
    "error",
    "exception",
    "info",
    "isEnabledFor",
    "log",
    "startTimer",
    "timed",
    "warn",
    "warning",
}


def _clean_environment() -> dict[str, str]:
    environment = os.environ.copy()
    for variable in (*ENVIRONMENT_KEYS_MAPPING.values(), PACKAGE_RULES_KEY_STR):
        environment.pop(variable, None)
    environment.pop("SENTRY_DSN", None)
    environment.pop("SENTRY_ENABLED", None)
    return environment


def _readme_python_source(markdown: str) -> str:
    """Return Python fences with blank placeholders preserving README line numbers."""
    source: list[str] = []
    in_python_block = False
    for line in markdown.splitlines():
        if line == "```python":
            in_python_block = True
            source.append("")
        elif in_python_block and line == "```":
            in_python_block = False
            source.append("")
        else:
            source.append(line if in_python_block else "")
    assert not in_python_block, "README has an unterminated Python code fence"
    return "\n".join(source)


def _assert_documented_call_binds(call: ast.Call, target: object, label: str) -> None:
    assert not any(isinstance(argument, ast.Starred) for argument in call.args), (
        f"README call to {label} uses an unchecked starred argument"
    )
    assert all(keyword.arg is not None for keyword in call.keywords), (
        f"README call to {label} uses unchecked keyword expansion"
    )
    arguments = [object()] * len(call.args)
    keywords = {keyword.arg: object() for keyword in call.keywords if keyword.arg is not None}
    try:
        inspect.signature(target).bind(*arguments, **keywords)
    except TypeError as error:
        message = f"README call to {label} does not match its public signature"
        raise AssertionError(message) from error


def test_required_public_api_is_explicit_and_type_marked() -> None:
    assert set(n_log_forge.__all__) == _PUBLIC_API
    assert {name for name in vars(n_log_forge) if not name.startswith("_")} == _PUBLIC_API
    for name in _PUBLIC_API:
        assert getattr(n_log_forge, name) is not None
    assert not hasattr(n_log_forge, "Logger")
    assert (_PROJECT_ROOT / "n_log_forge" / "py.typed").is_file()
    assert (_PROJECT_ROOT / "core" / "py.typed").is_file()


def test_import_and_lookup_are_passive_without_sentry() -> None:
    script = r'''
import builtins
import logging

root = logging.getLogger()
before = (root.level, tuple(root.handlers))
real_import = builtins.__import__

def blocked_import(name, *args, **kwargs):
    if name == "sentry_sdk" or name.startswith("sentry_sdk."):
        raise AssertionError("base use imported the optional Sentry SDK")
    return real_import(name, *args, **kwargs)

builtins.__import__ = blocked_import
import n_log_forge
assert (root.level, tuple(root.handlers)) == before
named = n_log_forge.getLogger("passive.lookup")
assert named.name == "passive.lookup"
assert (root.level, tuple(root.handlers)) == before
n_log_forge.configure(consoleEnabled=False)
named.info("base package works")
assert "sentry_sdk" not in __import__("sys").modules
assert n_log_forge.shutdown()
'''
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_PROJECT_ROOT,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert completed.stderr == ""


def test_pyproject_declares_distribution_layout_extra_and_minimum_python() -> None:
    configuration = tomllib.loads((_PROJECT_ROOT / "pyproject.toml").read_text())
    project = configuration["project"]
    wheel = configuration["tool"]["hatch"]["build"]["targets"]["wheel"]
    assert project["name"] == "n-log-forge"
    assert project["requires-python"] == ">=3.14"
    assert project["dependencies"] == []
    assert project["optional-dependencies"]["sentry"]
    assert set(wheel["packages"]) == {"core", "n_log_forge"}


def test_sync_async_example_runs_offline_through_the_public_api() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "example.sync_async"],
        cwd=_PROJECT_ROOT,
        env=_clean_environment(),
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == ""
    assert "Loaded configuration" in completed.stderr
    assert "Fetched user 42" in completed.stderr
    assert "Processing batch" in completed.stderr
    assert "dependency.client" in completed.stderr


def test_readme_and_raw_console_example_match_the_supported_commands() -> None:
    readme = (_PROJECT_ROOT / "README.md").read_text()
    for name in _PUBLIC_API:
        assert name in readme
    for command in (
        "python -m example.sync_async",
        "python -m pytest",
        "python -m ruff check .",
        "python -m mypy",
        "python -m build",
    ):
        assert command in readme

    raw = _PROJECT_ROOT / "raw" / "proxy" / "console"
    input_value = json.loads((raw / "json" / "input.json").read_text())
    output_value = json.loads((raw / "json" / "output.json").read_text())
    request = (raw / "request.txt").read_text()
    assert set(input_value) == {field.name for field in fields(Event)}
    assert input_value["source"] == "example.worker"
    assert input_value["metadata"] == {"itemCount": 12}
    assert output_value is None
    assert "standard-error" in request


def test_readme_python_examples_use_valid_public_api_calls() -> None:
    readme_path = _PROJECT_ROOT / "README.md"
    tree = ast.parse(_readme_python_source(readme_path.read_text()), filename=str(readme_path))
    aliases: dict[str, str] = {}
    facade_names: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == "n_log_forge":
            for imported in node.names:
                assert imported.name in _PUBLIC_API
                alias = imported.asname or imported.name
                aliases[alias] = imported.name
                if imported.name == "logger":
                    facade_names.add(alias)

    assert set(aliases.values()) == _PUBLIC_API
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        function = node.value.func
        if isinstance(function, ast.Name) and aliases.get(function.id) == "getLogger":
            facade_names.update(
                target.id for target in node.targets if isinstance(target, ast.Name)
            )

    checked_calls = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name) and function.id in aliases:
            public_name = aliases[function.id]
            _assert_documented_call_binds(
                node, getattr(n_log_forge, public_name), f"n_log_forge.{public_name}"
            )
            checked_calls += 1
        elif (
            isinstance(function, ast.Attribute)
            and isinstance(function.value, ast.Name)
            and function.value.id in facade_names
        ):
            assert function.attr in _PUBLIC_LOGGER_METHODS
            _assert_documented_call_binds(
                node, getattr(n_log_forge.logger, function.attr), f"logger.{function.attr}"
            )
            checked_calls += 1

    assert checked_calls >= 20

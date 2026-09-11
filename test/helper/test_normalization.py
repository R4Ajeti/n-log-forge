"""Executable contracts for the shared primitive configuration parsers."""

from __future__ import annotations

import pytest

from core.helper.normalization import (
    normalize_boolean,
    normalize_dsn,
    normalize_log_level,
    normalize_logger_name,
    normalize_package_rules,
    normalize_precision,
)


@pytest.mark.parametrize(
    ("aliases", "expected"),
    [
        (("critical", "crit", "c"), 50),
        (("error", "err", "e"), 40),
        (("warning", "warn", "w"), 30),
        (("info", "i"), 20),
        (("debug", "d"), 10),
        (("notset", "none", "n"), 0),
    ],
)
def test_every_level_alias(aliases: tuple[str, ...], expected: int) -> None:
    for alias in aliases:
        for candidate in (alias, alias.upper(), f" \t{alias.title()} \n"):
            assert normalize_log_level(candidate) == expected


@pytest.mark.parametrize("threshold", range(51))
def test_every_integer_threshold_and_decimal_string(threshold: int) -> None:
    assert normalize_log_level(threshold) == threshold
    assert normalize_log_level(f" \t{threshold} \n") == threshold
    assert normalize_log_level(f"000{threshold}") == threshold


@pytest.mark.parametrize(
    "value",
    [
        True,
        False,
        None,
        30.0,
        float("inf"),
        "+30",
        "-1",
        "3e1",
        "30.0",
        "٣٠",
        "３０",
        -1,
        51,
        "verbose",
        "",
        " \t",
        [],
        {},
        object(),
    ],
)
def test_invalid_levels(value: object) -> None:
    with pytest.raises(ValueError, match="threshold"):
        normalize_log_level(value)


def test_long_zero_prefixed_decimal_string_is_valid() -> None:
    assert normalize_log_level("0" * 5000 + "15") == 15
    with pytest.raises(ValueError):
        normalize_log_level("9" * 5000)


@pytest.mark.parametrize("value", [True, 1, "true", "1", "yes", "y", "on", " ON ", "TrUe"])
def test_true_values(value: object) -> None:
    assert normalize_boolean(value) is True


@pytest.mark.parametrize("value", [False, 0, "false", "0", "no", "n", "off", " OFF ", "FaLsE"])
def test_false_values(value: object) -> None:
    assert normalize_boolean(value) is False


@pytest.mark.parametrize("value", [None, 2, -1, 0.0, 1.0, "", " ", "maybe", "01", [], {}])
def test_invalid_booleans(value: object) -> None:
    with pytest.raises(ValueError, match="boolean"):
        normalize_boolean(value)


@pytest.mark.parametrize("precision", range(7))
def test_precision_range(precision: int) -> None:
    assert normalize_precision(precision) == precision
    assert normalize_precision(f" {precision} ") == precision


@pytest.mark.parametrize("value", [True, False, 1.0, -1, 7, None, "", "+1", "1.0", "١"])
def test_invalid_precision(value: object) -> None:
    with pytest.raises(ValueError, match="precision"):
        normalize_precision(value)


@pytest.mark.parametrize(
    "name", ["a", "A", "my-package", "my-package.api", "  Foo.Bar  ", "root.child"]
)
def test_valid_logger_names_preserve_case(name: str) -> None:
    assert normalize_logger_name(name) == name.strip()


@pytest.mark.parametrize(
    "name",
    [None, "", " ", "a..b", ".a", "a.", "a b", "a\tb", "a,b", "a=b", "root"],
)
def test_invalid_rule_names(name: object) -> None:
    with pytest.raises(ValueError):
        normalize_logger_name(name)


def test_root_can_be_acquired_but_cannot_be_configured_as_a_rule() -> None:
    assert normalize_logger_name("root", package_rule=False) == "root"
    assert normalize_logger_name("Root") == "Root"


def test_package_grammar_and_case_sensitivity() -> None:
    assert dict(normalize_package_rules(" pkg = DEBUG , Pkg=warn , pkg.api = 35 ")) == {
        "pkg": 10,
        "Pkg": 30,
        "pkg.api": 35,
    }


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "pkg",
        "pkg=",
        "=info",
        "pkg=info,",
        ",pkg=info",
        "pkg=info,,other=debug",
        "pkg=info=debug",
        "pkg=info,pkg=debug",
        "pkg=info, pkg = 10",
        "pkg..child=info",
        "pkg child=info",
        "root=info",
        "pkg=banana",
        "pkg=51",
    ],
)
def test_invalid_package_grammar(value: object) -> None:
    with pytest.raises(ValueError):
        normalize_package_rules(value)


@pytest.mark.parametrize(
    "dsn",
    [
        "https://public@example.ingest.sentry.io/123",
        "http://public@localhost:9000/1",
        "https://public:private@sentry.internal:8443/prefix/long/path/123",
        "http://key@[::1]:9000/team/42",
    ],
)
def test_local_dsn_validation_supports_self_hosted_shapes(dsn: str) -> None:
    normalized = normalize_dsn(f"  {dsn} ")
    assert normalized == dsn
    assert "public" not in repr(normalized)
    assert dsn not in repr(normalized)
    assert "redacted" in repr(normalized)


@pytest.mark.parametrize("value", ["", " \t\n"])
def test_dsn_blank_is_an_explicit_disable(value: str) -> None:
    assert normalize_dsn(value) == ""


@pytest.mark.parametrize(
    "value",
    [
        None,
        1,
        "banana",
        "ftp://private@example.com/123",
        "https://example.com/123",
        "https://private@/123",
        "https://private@example.com",
        "https://private@example.com/",
        "https://private@example.com/project",
        "https://private@example.com:wrong/1",
        "https://private@example.com:99999/1",
        "https://private@[secret-invalid-host/123",
        "https://private@exam ple.com/123",
        "https://private@example.com/123?secret=1",
        "https://private@example.com/123#secret",
    ],
)
def test_invalid_dsn_errors_and_exception_context_are_redacted(value: object) -> None:
    with pytest.raises(ValueError) as caught:
        normalize_dsn(value)
    assert "private" not in str(caught.value)
    assert "secret-invalid-host" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_dsn_string_subclass_cannot_run_credential_leaking_overrides() -> None:
    secret = "do-not-expose-this-dsn"

    class HostileDsn(str):
        def __str__(self) -> str:
            raise RuntimeError(secret)

        def strip(self, chars: str | None = None) -> str:
            raise RuntimeError(secret)

    valid = HostileDsn(" https://public@example.invalid/prefix/123 ")
    normalized = normalize_dsn(valid)
    assert normalized == "https://public@example.invalid/prefix/123"
    assert secret not in repr(normalized)

    with pytest.raises(ValueError) as caught:
        normalize_dsn(HostileDsn("not-a-dsn"))
    assert secret not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None

"""Pure normalization shared by configuration entry points.

Primitive parsers deliberately reject ``None`` and blank strings. Environment
absence and programmatic reset operations belong to the configuration service.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from urllib.parse import urlsplit

from core.constant import configuration_constant as constants


def _decimal_integer(value: object) -> int | None:
    """Accept integers and ASCII unsigned decimal strings, excluding bools."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        value = value.strip()
        if value and value.isascii() and value.isdecimal():
            # Compare after stripping leading zeros to avoid Python's configurable
            # integer-string conversion limit for otherwise valid "000...001".
            significant = value.lstrip("0") or "0"
            if len(significant) <= 2:
                return int(significant)
    return None


def normalize_log_level(value: object) -> int:
    """Return a threshold in 0..50 from an integer, digit string, or alias."""
    if isinstance(value, str):
        alias = constants.LEVEL_ALIASES_MAPPING.get(value.strip().lower())
        if alias is not None:
            return alias
    result = _decimal_integer(value)
    if result is None or not constants.LEVEL_MIN_INT <= result <= constants.LEVEL_MAX_INT:
        raise ValueError("expected a level alias or an integer threshold from 0 through 50")
    return result


def normalize_boolean(value: object) -> bool:
    """Accept bool, integer 0/1, or the documented case-insensitive tokens."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        token = value.strip().lower()
        if token in constants.BOOLEAN_TRUE_TOKENS_FROZENSET:
            return True
        if token in constants.BOOLEAN_FALSE_TOKENS_FROZENSET:
            return False
    raise ValueError("expected a boolean, integer 0/1, or a documented boolean token")


def normalize_precision(value: object) -> int:
    """Return duration decimal precision, restricted to integer values 0..6."""
    result = _decimal_integer(value)
    if result is None or not constants.PRECISION_MIN_INT <= result <= constants.PRECISION_MAX_INT:
        raise ValueError("expected an integer duration precision from 0 through 6")
    return result


def normalize_string(value: object) -> str:
    """Require a nonblank string and remove leading/trailing whitespace."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("expected a non-empty string")
    return value.strip()


def normalize_logger_name(value: object, *, package_rule: bool = True) -> str:
    """Validate a case-sensitive dotted logger path without identifier limits."""
    result = normalize_string(value)
    if (
        any(character.isspace() for character in result)
        or "," in result
        or "=" in result
        or any(not segment for segment in result.split("."))
    ):
        raise ValueError("expected a dotted logger name without empty segments, whitespace, ',' or '='")
    if package_rule and result == constants.ROOT_LOGGER_NAME_STR:
        raise ValueError("the logger name 'root' is reserved for global configuration")
    return result


def normalize_package_rules(value: object) -> Mapping[str, int]:
    """Parse the strict comma-separated environment rule grammar."""
    text = normalize_string(value)
    rules: dict[str, int] = {}
    for entry in text.split(","):
        if entry.count("=") != 1:
            raise ValueError("expected comma-separated name=level pairs with exactly one '=' each")
        raw_name, raw_level = entry.split("=")
        name = normalize_logger_name(raw_name)
        if name in rules:
            raise ValueError("duplicate exact logger name in package rules")
        rules[name] = normalize_log_level(raw_level)
    return MappingProxyType(rules)


class RedactedDsn(str):
    """A usable DSN string whose representation cannot reveal its contents."""

    def __repr__(self) -> str:
        return constants.REDACTED_DSN_STR


def normalize_dsn(value: object) -> str:
    """Validate an HTTP(S) Sentry DSN locally; blank strings disable Sentry.

    The structure follows ``sentry_sdk.utils.Dsn`` without importing the SDK:
    a public key, host, optional port/path prefix, and terminal project number.
    No parser exception is chained because URL errors can contain credentials.
    """
    if not isinstance(value, str):
        raise ValueError("expected a DSN string (value redacted)")
    candidate = value.strip()
    if not candidate:
        return constants.DISABLED_DSN_STR
    valid = False
    try:
        parts = urlsplit(candidate)
        project = parts.path.rsplit("/", 1)[-1]
        valid = (
            parts.scheme in constants.HTTP_SCHEMES_FROZENSET
            and bool(parts.hostname)
            and bool(parts.username)
            and (parts.port is None or 0 < parts.port <= 65535)
            and not any(character.isspace() or ord(character) < 32 for character in candidate)
            and bool(project)
            and project.isascii()
            and project.isdecimal()
            and not parts.query
            and not parts.fragment
        )
    except (ValueError, TypeError):
        # Raise outside this block: even __context__ must not retain a URL error.
        pass
    if not valid:
        raise ValueError("expected an HTTP(S) Sentry DSN with public key, host and project ID (value redacted)")
    return RedactedDsn(candidate)

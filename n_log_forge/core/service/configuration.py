"""Privately validate configuration and resolve immutable logging policies.

This module owns no active process state and never imports provider SDKs. The
runtime coordinates publication only after it has prepared all resources.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from types import MappingProxyType
from typing import cast

from ..constant import configuration_constant as constants
from ..helper.normalization import (
    normalize_boolean,
    normalize_dsn,
    normalize_log_level,
    normalize_logger_name,
    normalize_package_rules,
    normalize_precision,
    normalize_string,
)


class ConfigurationError(ValueError):
    """Invalid configuration, annotated with a key and source but no secrets."""

    def __init__(self, key: str, source: str, reason: str) -> None:
        self.key = key
        self.source = source
        super().__init__(f"Invalid {source} configuration for {key}: {reason}")


def validate_runtime_key(key: str) -> None:
    """Reject a key that cannot be stored as a programmatic override.

    Callers must perform this check before interpreting ``None`` as a reset so
    unknown reset keys cannot bypass validation. ``reloadEnvironment`` is a
    per-call control rather than stored configuration and is intentionally not
    accepted here; :func:`normalize_runtime` continues to normalize that control.
    """
    if key not in constants.CONFIGURATION_KEYS_TUPLE:
        raise ConfigurationError(
            key, constants.RUNTIME_SOURCE_STR, "unsupported configuration key"
        )


def _normalize(key: str, value: object, source: str) -> object:
    reason = "unsupported configuration key"
    try:
        if key in constants.LEVEL_KEYS_FROZENSET:
            return normalize_log_level(value)
        if key in constants.BOOLEAN_KEYS_FROZENSET or key == constants.RELOAD_ENVIRONMENT_KEY_STR:
            return normalize_boolean(value)
        if key == constants.DURATION_PRECISION_KEY_STR:
            return normalize_precision(value)
        if key in constants.STRING_KEYS_FROZENSET:
            return normalize_string(value)
        if key == constants.SENTRY_DSN_KEY_STR:
            return normalize_dsn(value)
        if key == constants.ROOT_HANDLER_POLICY_KEY_STR:
            policy = normalize_string(value)
            if policy not in constants.ROOT_POLICIES_FROZENSET:
                raise ValueError("expected 'preserve' or 'replace'")
            return policy
    except ValueError as error:
        reason = str(error)
    # Raising here deliberately avoids retaining sensitive parser exceptions.
    raise ConfigurationError(key, source, reason)


def normalize_runtime(key: str, value: object) -> object:
    """Validate a non-None programmatic override, including reload control."""
    if key != constants.RELOAD_ENVIRONMENT_KEY_STR:
        validate_runtime_key(key)
    return _normalize(key, value, constants.RUNTIME_SOURCE_STR)


def _normalize_package_name(name: object, source: str) -> str:
    error_reason: str | None = None
    try:
        normalized_name = normalize_logger_name(name)
    except (TypeError, ValueError) as error:
        error_reason = str(error)
    if error_reason is not None:
        raise ConfigurationError(constants.PACKAGE_RULES_KEY_STR, source, error_reason)
    return normalized_name


def _normalize_package_rule(name: object, level: object, source: str) -> tuple[str, int]:
    normalized_name = _normalize_package_name(name, source)
    error_reason: str | None = None
    try:
        normalized_level = normalize_log_level(level)
    except (TypeError, ValueError) as error:
        error_reason = str(error)
    if error_reason is not None:
        raise ConfigurationError(constants.PACKAGE_RULES_KEY_STR, source, error_reason)
    return normalized_name, normalized_level


def normalize_runtime_package_name(name: object) -> str:
    """Normalize a runtime package name, including for an exact-rule reset."""
    return _normalize_package_name(name, constants.RUNTIME_SOURCE_STR)


def normalize_runtime_package_rule(name: object, level: object) -> tuple[str, int]:
    """Normalize one runtime package rule with configuration error context."""
    return _normalize_package_rule(name, level, constants.RUNTIME_SOURCE_STR)


def _environment_text(key: str, variable: str, value: object) -> str:
    """Trim an environment string without invoking subclass overrides."""
    if not isinstance(value, str):
        raise ConfigurationError(
            key, f"environment {variable}", "expected a string environment value"
        )
    try:
        return str.__str__(value).strip()
    except Exception:
        # Raise later so an exception from an adversarial value is not chained.
        pass
    raise ConfigurationError(
        key, f"environment {variable}", "expected a string environment value"
    )


def read_environment(environ: Mapping[str, str] | None = None) -> Mapping[str, object]:
    """Copy and validate supported environment values once, ignoring blanks.

    Returned keys use their programmatic spelling except ``LOGGER_PACKAGES``.
    The snapshot and nested rule map are immutable; DSN reprs are redacted.
    """
    source = dict(os.environ if environ is None else environ)
    normalized: dict[str, object] = {}
    for key, variable in constants.ENVIRONMENT_KEYS_MAPPING.items():
        value = source.get(variable)
        if value is not None:
            text = _environment_text(key, variable, value)
            if text:
                normalized[key] = _normalize(key, text, f"environment {variable}")
    package_text = source.get(constants.PACKAGE_RULES_KEY_STR)
    if package_text is not None:
        package_text = _environment_text(
            constants.PACKAGE_RULES_KEY_STR,
            constants.PACKAGE_RULES_KEY_STR,
            package_text,
        )
    if package_text:
        error_reason: str | None = None
        try:
            normalized[constants.PACKAGE_RULES_KEY_STR] = normalize_package_rules(package_text)
        except ValueError as error:
            error_reason = str(error)
        if error_reason is not None:
            raise ConfigurationError(
                constants.PACKAGE_RULES_KEY_STR, constants.ENVIRONMENT_SOURCE_STR, error_reason
            )
    return MappingProxyType(normalized)


@lru_cache(maxsize=constants.HIERARCHY_CACHE_SIZE_INT)
def _resolve_threshold(name: str, rules: tuple[tuple[str, int], ...], global_level: int) -> int:
    selected = dict(rules)
    current = name
    while current:
        threshold = selected.get(current)
        if threshold:
            return threshold
        current, separator, _ = current.rpartition(".")
        if not separator:
            break
    return global_level


@dataclass(frozen=True)
class Config:
    """A coherent immutable provider and logger configuration snapshot."""

    level: int | None = None
    debugging: bool | None = None
    global_level: int = logging.INFO
    console_enabled: bool = constants.DEFAULT_CONSOLE_ENABLED_BOOL
    timestamp_format: str | None = None
    package_name: str | None = None
    duration_precision: int = constants.DEFAULT_PRECISION_INT
    sentry_data_source_name: str | None = field(default=None, repr=False)
    sentry_level: int = constants.DEFAULT_SENTRY_LEVEL_INT
    sentry_environment: str | None = None
    sentry_release: str | None = None
    manage_root_level: bool = constants.DEFAULT_MANAGE_ROOT_LEVEL_BOOL
    root_handler_policy: str = constants.ROOT_POLICY_PRESERVE_STR
    package_rules: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))
    _rule_items: tuple[tuple[str, int], ...] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        # Defensively copy caller-owned mappings, even when Config is used directly.
        frozen_rules = MappingProxyType(dict(self.package_rules))
        object.__setattr__(self, "package_rules", frozen_rules)
        object.__setattr__(self, "_rule_items", tuple(sorted(frozen_rules.items())))

    def threshold(self, name: str) -> int:
        """Resolve exact rules then ancestors; zero masks and inherits."""
        return _resolve_threshold(name, self._rule_items, self.global_level)


def _validated_rules(value: object, source: str) -> dict[str, int]:
    if not isinstance(value, Mapping):
        raise ConfigurationError(constants.PACKAGE_RULES_KEY_STR, source, "expected a rule mapping")
    rules: dict[str, int] = {}
    for raw_name, raw_level in value.items():
        name, level = _normalize_package_rule(raw_name, raw_level, source)
        if name in rules:
            raise ConfigurationError(
                constants.PACKAGE_RULES_KEY_STR,
                source,
                "duplicate exact logger name in package rules",
            )
        rules[name] = level
    return rules


def build_config(
    environment: Mapping[str, object],
    runtime: Mapping[str, object],
    runtime_packages: Mapping[str, object],
) -> Config:
    """Validate every source before merging per key and exact logger name.

    Inputs contain normalized non-None settings: the caller implements resets by
    removing entries before invoking this pure candidate builder. Validation is
    repeated so callers cannot accidentally hide an invalid shadowed setting.
    """
    merged: dict[str, object] = {}
    for source, values in (
        (constants.ENVIRONMENT_SOURCE_STR, environment),
        (constants.RUNTIME_SOURCE_STR, runtime),
    ):
        for key, value in values.items():
            if (
                key == constants.PACKAGE_RULES_KEY_STR
                and source == constants.ENVIRONMENT_SOURCE_STR
            ):
                continue
            merged[key] = _normalize(key, value, source)
    rules = _validated_rules(
        environment.get(constants.PACKAGE_RULES_KEY_STR, {}), constants.ENVIRONMENT_SOURCE_STR
    )
    rules.update(_validated_rules(runtime_packages, constants.RUNTIME_SOURCE_STR))

    level = cast("int | None", merged.get(constants.LEVEL_KEY_STR))
    debugging = cast("bool | None", merged.get(constants.DEBUGGING_KEY_STR))
    if debugging is True:
        global_level = logging.DEBUG
    elif level is not None:
        global_level = level
    elif debugging is False:
        global_level = logging.ERROR
    else:
        global_level = logging.INFO

    return Config(
        level=level,
        debugging=debugging,
        global_level=global_level,
        console_enabled=cast(
            bool,
            merged.get(
                constants.CONSOLE_ENABLED_KEY_STR,
                constants.DEFAULT_CONSOLE_ENABLED_BOOL,
            ),
        ),
        timestamp_format=cast("str | None", merged.get(constants.TIMESTAMP_FORMAT_KEY_STR)),
        package_name=cast("str | None", merged.get(constants.PACKAGE_NAME_KEY_STR)),
        duration_precision=cast(
            int, merged.get(constants.DURATION_PRECISION_KEY_STR, constants.DEFAULT_PRECISION_INT)
        ),
        sentry_data_source_name=cast("str | None", merged.get(constants.SENTRY_DSN_KEY_STR)),
        sentry_level=cast(
            int, merged.get(constants.SENTRY_LEVEL_KEY_STR, constants.DEFAULT_SENTRY_LEVEL_INT)
        ),
        sentry_environment=cast("str | None", merged.get(constants.SENTRY_ENVIRONMENT_KEY_STR)),
        sentry_release=cast("str | None", merged.get(constants.SENTRY_RELEASE_KEY_STR)),
        manage_root_level=cast(
            bool,
            merged.get(
                constants.MANAGE_ROOT_LEVEL_KEY_STR,
                constants.DEFAULT_MANAGE_ROOT_LEVEL_BOOL,
            ),
        ),
        root_handler_policy=cast(
            str,
            merged.get(
                constants.ROOT_HANDLER_POLICY_KEY_STR,
                constants.ROOT_POLICY_PRESERVE_STR,
            ),
        ),
        package_rules=rules,
    )

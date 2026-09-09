"""Validate candidate configuration and resolve immutable logging policies.

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

from core.constant import configuration_constant as constants
from core.helper.normalization import (
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
    return _normalize(key, value, constants.RUNTIME_SOURCE_STR)


def read_environment(environ: Mapping[str, str] | None = None) -> Mapping[str, object]:
    """Copy and validate supported environment values once, ignoring blanks.

    Returned keys use their programmatic spelling except ``LOGGER_PACKAGES``.
    The snapshot and nested rule map are immutable; DSN reprs are redacted.
    """
    source = dict(os.environ if environ is None else environ)
    normalized: dict[str, object] = {}
    for key, variable in constants.ENVIRONMENT_KEYS_MAPPING.items():
        value = source.get(variable)
        if value is not None and value.strip():
            normalized[key] = _normalize(key, value.strip(), f"environment {variable}")
    package_text = source.get(constants.PACKAGE_RULES_KEY_STR)
    if package_text is not None and package_text.strip():
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
    error_reason: str | None = None
    try:
        for raw_name, raw_level in value.items():
            name = normalize_logger_name(raw_name)
            if name in rules:
                raise ValueError("duplicate exact logger name in package rules")
            rules[name] = normalize_log_level(raw_level)
    except ValueError as error:
        error_reason = str(error)
    if error_reason is not None:
        raise ConfigurationError(constants.PACKAGE_RULES_KEY_STR, source, error_reason)
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
            if key == constants.PACKAGE_RULES_KEY_STR and source == constants.ENVIRONMENT_SOURCE_STR:
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
            bool, merged.get(constants.CONSOLE_ENABLED_KEY_STR, constants.DEFAULT_CONSOLE_ENABLED_BOOL)
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
            merged.get(constants.MANAGE_ROOT_LEVEL_KEY_STR, constants.DEFAULT_MANAGE_ROOT_LEVEL_BOOL),
        ),
        root_handler_policy=cast(
            str, merged.get(constants.ROOT_HANDLER_POLICY_KEY_STR, constants.ROOT_POLICY_PRESERVE_STR)
        ),
        package_rules=rules,
    )

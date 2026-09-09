"""Immutable names and defaults belonging to the configuration contract."""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Final

OMITTED: Final = object()

LEVEL_KEY_STR: Final = "level"
DEBUGGING_KEY_STR: Final = "debugging"
CONSOLE_ENABLED_KEY_STR: Final = "consoleEnabled"
TIMESTAMP_FORMAT_KEY_STR: Final = "timestampFormat"
PACKAGE_NAME_KEY_STR: Final = "packageName"
DURATION_PRECISION_KEY_STR: Final = "durationPrecision"
SENTRY_DSN_KEY_STR: Final = "sentryDataSourceName"
SENTRY_LEVEL_KEY_STR: Final = "sentryLevel"
SENTRY_ENVIRONMENT_KEY_STR: Final = "sentryEnvironment"
SENTRY_RELEASE_KEY_STR: Final = "sentryRelease"
MANAGE_ROOT_LEVEL_KEY_STR: Final = "manageRootLevel"
ROOT_HANDLER_POLICY_KEY_STR: Final = "rootHandlerPolicy"
RELOAD_ENVIRONMENT_KEY_STR: Final = "reloadEnvironment"
PACKAGE_RULES_KEY_STR: Final = "LOGGER_PACKAGES"

LEVEL_ENV_STR: Final = "LOGGER"
DEBUGGING_ENV_STR: Final = "DEBUGGING"
CONSOLE_ENABLED_ENV_STR: Final = "CONSOLE_ENABLED"
TIMESTAMP_FORMAT_ENV_STR: Final = "TIMESTAMP_FORMAT"
PACKAGE_NAME_ENV_STR: Final = "PACKAGE_NAME"
DURATION_PRECISION_ENV_STR: Final = "DURATION_PRECISION"
SENTRY_DSN_ENV_STR: Final = "SENTRY_DATA_SOURCE_NAME"
SENTRY_LEVEL_ENV_STR: Final = "SENTRY_LEVEL"
SENTRY_ENVIRONMENT_ENV_STR: Final = "SENTRY_ENVIRONMENT"
SENTRY_RELEASE_ENV_STR: Final = "SENTRY_RELEASE"

ENVIRONMENT_KEYS_MAPPING: Final = MappingProxyType(
    {
        LEVEL_KEY_STR: LEVEL_ENV_STR,
        DEBUGGING_KEY_STR: DEBUGGING_ENV_STR,
        CONSOLE_ENABLED_KEY_STR: CONSOLE_ENABLED_ENV_STR,
        TIMESTAMP_FORMAT_KEY_STR: TIMESTAMP_FORMAT_ENV_STR,
        PACKAGE_NAME_KEY_STR: PACKAGE_NAME_ENV_STR,
        DURATION_PRECISION_KEY_STR: DURATION_PRECISION_ENV_STR,
        SENTRY_DSN_KEY_STR: SENTRY_DSN_ENV_STR,
        SENTRY_LEVEL_KEY_STR: SENTRY_LEVEL_ENV_STR,
        SENTRY_ENVIRONMENT_KEY_STR: SENTRY_ENVIRONMENT_ENV_STR,
        SENTRY_RELEASE_KEY_STR: SENTRY_RELEASE_ENV_STR,
    }
)
CONFIGURATION_KEYS_TUPLE: Final = (
    LEVEL_KEY_STR,
    DEBUGGING_KEY_STR,
    CONSOLE_ENABLED_KEY_STR,
    TIMESTAMP_FORMAT_KEY_STR,
    PACKAGE_NAME_KEY_STR,
    DURATION_PRECISION_KEY_STR,
    SENTRY_DSN_KEY_STR,
    SENTRY_LEVEL_KEY_STR,
    SENTRY_ENVIRONMENT_KEY_STR,
    SENTRY_RELEASE_KEY_STR,
    MANAGE_ROOT_LEVEL_KEY_STR,
    ROOT_HANDLER_POLICY_KEY_STR,
)
BOOLEAN_KEYS_FROZENSET: Final = frozenset(
    (DEBUGGING_KEY_STR, CONSOLE_ENABLED_KEY_STR, MANAGE_ROOT_LEVEL_KEY_STR)
)
LEVEL_KEYS_FROZENSET: Final = frozenset((LEVEL_KEY_STR, SENTRY_LEVEL_KEY_STR))
STRING_KEYS_FROZENSET: Final = frozenset(
    (
        TIMESTAMP_FORMAT_KEY_STR,
        PACKAGE_NAME_KEY_STR,
        SENTRY_ENVIRONMENT_KEY_STR,
        SENTRY_RELEASE_KEY_STR,
    )
)

LEVEL_ALIASES_MAPPING: Final = MappingProxyType(
    {
        "critical": logging.CRITICAL,
        "crit": logging.CRITICAL,
        "c": logging.CRITICAL,
        "error": logging.ERROR,
        "err": logging.ERROR,
        "e": logging.ERROR,
        "warning": logging.WARNING,
        "warn": logging.WARNING,
        "w": logging.WARNING,
        "info": logging.INFO,
        "i": logging.INFO,
        "debug": logging.DEBUG,
        "d": logging.DEBUG,
        "notset": logging.NOTSET,
        "none": logging.NOTSET,
        "n": logging.NOTSET,
    }
)
BOOLEAN_TRUE_TOKENS_FROZENSET: Final = frozenset(("true", "1", "yes", "y", "on"))
BOOLEAN_FALSE_TOKENS_FROZENSET: Final = frozenset(("false", "0", "no", "n", "off"))
LEVEL_MIN_INT: Final = logging.NOTSET
LEVEL_MAX_INT: Final = logging.CRITICAL
PRECISION_MIN_INT: Final = 0
PRECISION_MAX_INT: Final = 6
DEFAULT_PRECISION_INT: Final = 1
DEFAULT_CONSOLE_ENABLED_BOOL: Final = True
DEFAULT_MANAGE_ROOT_LEVEL_BOOL: Final = True
DEFAULT_SENTRY_LEVEL_INT: Final = logging.ERROR
ROOT_POLICY_PRESERVE_STR: Final = "preserve"
ROOT_POLICY_REPLACE_STR: Final = "replace"
ROOT_POLICIES_FROZENSET: Final = frozenset(
    (ROOT_POLICY_PRESERVE_STR, ROOT_POLICY_REPLACE_STR)
)
ROOT_LOGGER_NAME_STR: Final = "root"
RUNTIME_SOURCE_STR: Final = "runtime"
ENVIRONMENT_SOURCE_STR: Final = "environment"
DISABLED_DSN_STR: Final = ""
REDACTED_DSN_STR: Final = "<redacted DSN>"
HTTP_SCHEMES_FROZENSET: Final = frozenset(("http", "https"))
HIERARCHY_CACHE_SIZE_INT: Final = 4096

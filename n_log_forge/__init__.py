"""Cooperative structured logging with optional isolated Sentry delivery.

The public logger objects are lightweight facades over :mod:`logging`; they are
not ``logging.Logger`` instances.  Importing this module and acquiring a named
logger are passive.  The owned logging pipeline is initialized by the first log
eligibility check/call or by an explicit :func:`configure` call.
"""

from __future__ import annotations

from core.constant import configuration_constant as _configuration
from core.constant import runtime_constant as _runtime_constant
from core.service import runtime as _runtime
from core.service.facade import getLogger, logger

__all__ = (
    "configure",
    "flush",
    "getLogger",
    "logger",
    "resetPackageLevel",
    "setPackageLevel",
    "shutdown",
)

type _LevelSetting = int | str | None | _configuration._Omitted
type _BooleanSetting = bool | int | str | None | _configuration._Omitted
type _StringSetting = str | None | _configuration._Omitted
type _PrecisionSetting = int | str | None | _configuration._Omitted
type _ReloadSetting = bool | int | str


def configure(
    *,
    level: _LevelSetting = _configuration.OMITTED,
    debugging: _BooleanSetting = _configuration.OMITTED,
    consoleEnabled: _BooleanSetting = _configuration.OMITTED,
    timestampFormat: _StringSetting = _configuration.OMITTED,
    packageName: _StringSetting = _configuration.OMITTED,
    durationPrecision: _PrecisionSetting = _configuration.OMITTED,
    sentryDataSourceName: _StringSetting = _configuration.OMITTED,
    sentryLevel: _LevelSetting = _configuration.OMITTED,
    sentryEnvironment: _StringSetting = _configuration.OMITTED,
    sentryRelease: _StringSetting = _configuration.OMITTED,
    manageRootLevel: _BooleanSetting = _configuration.OMITTED,
    rootHandlerPolicy: _StringSetting = _configuration.OMITTED,
    reloadEnvironment: _ReloadSetting = False,
) -> None:
    """Atomically validate and apply process-wide logging configuration.

    Omitted settings retain their runtime overrides.  Passing ``None`` removes
    the override for that one setting and reveals its environment/default value.
    ``reloadEnvironment`` is a per-call boolean control and cannot be reset with
    ``None``.  Calling ``configure()`` with no arguments initializes eagerly.
    """
    _runtime.RUNTIME.configure(
        {
            _configuration.LEVEL_KEY_STR: level,
            _configuration.DEBUGGING_KEY_STR: debugging,
            _configuration.CONSOLE_ENABLED_KEY_STR: consoleEnabled,
            _configuration.TIMESTAMP_FORMAT_KEY_STR: timestampFormat,
            _configuration.PACKAGE_NAME_KEY_STR: packageName,
            _configuration.DURATION_PRECISION_KEY_STR: durationPrecision,
            _configuration.SENTRY_DSN_KEY_STR: sentryDataSourceName,
            _configuration.SENTRY_LEVEL_KEY_STR: sentryLevel,
            _configuration.SENTRY_ENVIRONMENT_KEY_STR: sentryEnvironment,
            _configuration.SENTRY_RELEASE_KEY_STR: sentryRelease,
            _configuration.MANAGE_ROOT_LEVEL_KEY_STR: manageRootLevel,
            _configuration.ROOT_HANDLER_POLICY_KEY_STR: rootHandlerPolicy,
        },
        reloadEnvironment,
    )


def setPackageLevel(name: str, level: int | str) -> None:
    """Set the runtime threshold/inheritance rule for one exact logger name."""
    _runtime.RUNTIME.package_rule(name, level)


def resetPackageLevel(name: str) -> None:
    """Remove the runtime rule for one exact logger name, revealing environment rules."""
    _runtime.RUNTIME.package_rule(name)


def flush(timeout: float = _runtime_constant.DEFAULT_TIMEOUT_SECONDS_FLOAT) -> bool:
    """Wait within a total budget for currently queued owned provider work."""
    return _runtime.RUNTIME.flush(timeout)


def shutdown(timeout: float = _runtime_constant.DEFAULT_TIMEOUT_SECONDS_FLOAT) -> bool:
    """Stop owned intake, restore logging state, and drain/close within a budget."""
    return _runtime.RUNTIME.shutdown(timeout)


# Python 3.14 exposes the future-feature marker as a module global. Keep the
# documented public namespace limited to the seven names in ``__all__``.
del annotations

"""Process-local composition root and cooperative logging ownership.

Lock order: transition lock, then state lock, then logging's registry lock.
Emission takes only the state lock to lease a snapshot. Neither lock is held
during formatting, provider delivery, flush, close, or waiting for workers.
Daemon cleanup owns retired providers; it never edits active logging state.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from collections.abc import Mapping
from dataclasses import dataclass, field

from ..constant.configuration_constant import OMITTED
from ..constant.runtime_constant import (
    DEFAULT_TIMEOUT_SECONDS_FLOAT,
    LIFECYCLE_THREAD_NAME_STR,
    NAMED_CREATION_GATE_INT,
    OWNED_HANDLER_NAME_STR,
    REPLACE_POLICY_STR,
)
from ..helper.event import make_event
from ..helper.normalization import normalize_boolean, normalize_log_level, normalize_logger_name
from ..proxy.console import ConsoleProvider
from ..proxy.provider import Provider
from .configuration import Config, build_config, normalize_runtime, read_environment


def _timeout(value: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("timeout must be a finite nonnegative number")
    try:
        number = float(value)
    except OverflowError:
        raise ValueError("timeout must be a finite nonnegative number") from None
    if not math.isfinite(number) or number < 0:
        raise ValueError("timeout must be a finite nonnegative number")
    return number


@dataclass(eq=False)
class _Job:
    done: threading.Event = field(default_factory=threading.Event)
    result: bool = False


@dataclass(eq=False)
class _Resource:
    provider: Provider
    users: int = 0
    retired: bool = False
    closed: bool = False
    cleanup: _Job | None = None
    flushing: _Job | None = None


@dataclass(frozen=True)
class _Snapshot:
    config: Config
    console: _Resource | None
    sentry: _Resource | None

    @property
    def resources(self) -> tuple[_Resource, ...]:
        return tuple(resource for resource in (self.console, self.sentry) if resource is not None)


class DispatchHandler(logging.Handler):
    """The single root intake; provider locks never nest under Handler.lock."""

    def __init__(self, runtime: Runtime) -> None:
        super().__init__(logging.NOTSET)
        self.name = OWNED_HANDLER_NAME_STR
        self.runtime = runtime

    def handle(self, record: logging.LogRecord) -> bool:
        # Standard Handler.handle serializes emit under its RLock. Our immutable
        # snapshots and providers own synchronization, so avoid that extra lock.
        if not self.filter(record):
            return False
        self.emit(record)
        return True

    def emit(self, record: logging.LogRecord) -> None:
        self.runtime.emit(record)


class Runtime:
    def __init__(self) -> None:
        self._transition = threading.RLock()
        self._state = threading.RLock()
        self._idle_condition = threading.Condition(self._state)
        self._snapshot: _Snapshot | None = None
        self._environment: Mapping[str, object] | None = None
        self._overrides: dict[str, object] = {}
        self._rules: dict[str, int] = {}
        self._stopped = False
        self._handler: DispatchHandler | None = None
        self._gates: dict[logging.Logger, tuple[int, int]] = {}
        self._detached: list[logging.Handler] = []
        self._retired: list[_Resource] = []
        self._emitting = threading.local()

    def ensure(self) -> None:
        with self._state:
            if self._snapshot is not None or self._stopped:
                return
        with self._transition:
            with self._state:
                if self._snapshot is not None or self._stopped:
                    return
            self._update({})

    def enabled(self, name: str, level: int) -> bool:
        self.ensure()
        with self._state:
            snapshot = self._snapshot
            eligible = snapshot is not None and level >= snapshot.config.threshold(name)
        return eligible and logging.getLogger(name).isEnabledFor(level)

    def configure(self, changes: Mapping[str, object], reload: object = False) -> None:
        try:
            reload_value = normalize_boolean(reload)
        except (TypeError, ValueError):
            raise ValueError("reloadEnvironment (runtime): expected a valid boolean") from None
        with self._transition:
            self._update(changes, reload=reload_value)

    def package_rule(self, name: str, level: object = OMITTED) -> None:
        name = normalize_logger_name(name, package_rule=True)
        normalized = OMITTED if level is OMITTED else normalize_log_level(level)
        with self._transition:
            rules = self._rules.copy()
            if normalized is OMITTED:
                rules.pop(name, None)
            else:
                assert isinstance(normalized, int)
                rules[name] = normalized
            if self._stopped:
                self._rules = rules
                return
            authorized = {name} if rules.get(name, OMITTED) != self._rules.get(name, OMITTED) else set()
            self._update({}, rules=rules, authorized=authorized)

    def _update(
        self,
        changes: Mapping[str, object],
        *,
        reload: bool = False,
        rules: dict[str, int] | None = None,
        authorized: set[str] | None = None,
    ) -> None:
        # Called under _transition. Provider construction can fail without
        # publishing configuration or touching any host handlers/gates.
        environment = (
            read_environment() if reload or self._environment is None else self._environment
        )
        overrides = self._overrides.copy()
        for key, value in changes.items():
            if value is OMITTED:
                continue
            if value is None:
                overrides.pop(key, None)
            else:
                overrides[key] = normalize_runtime(key, value)
        candidate_rules = self._rules.copy() if rules is None else rules
        config = build_config(environment, overrides, candidate_rules)
        old = self._snapshot
        console: _Resource | None = None
        sentry: _Resource | None = None
        if config.console_enabled:
            if old and old.console and old.config.timestamp_format == config.timestamp_format:
                console = old.console
            else:
                console = _Resource(ConsoleProvider(timestamp_format=config.timestamp_format))
        if config.sentry_data_source_name:
            construction = (
                config.sentry_data_source_name, config.sentry_environment, config.sentry_release
            )
            old_construction = (
                (old.config.sentry_data_source_name,
                 old.config.sentry_environment, old.config.sentry_release) if old else None
            )
            if old and old.sentry and construction == old_construction:
                sentry = old.sentry
            else:
                from ..proxy.sentry import SentryProvider

                sentry = _Resource(SentryProvider(*construction))
        new = _Snapshot(config, console, sentry)
        with self._state:
            self._reconcile(old.config if old else None, config, authorized or set())
            if self._handler is None:
                self._handler = DispatchHandler(self)
                logging.getLogger().addHandler(self._handler)
            self._environment = environment
            self._overrides = overrides
            self._rules = candidate_rules
            self._snapshot = new
            self._stopped = False
            if old:
                for resource in old.resources:
                    if resource not in new.resources:
                        self._retire(resource)

    def _install_gate(self, logger: logging.Logger, level: int) -> None:
        prior = self._gates.get(logger)
        # A fresh authorized change after a host change remembers that new host
        # baseline; otherwise retain the original level through owned changes.
        baseline = prior[0] if prior and logger.level == prior[1] else logger.level
        self._gates[logger] = (baseline, level)
        logger.setLevel(level)

    def _restore_gate(self, logger: logging.Logger) -> None:
        prior = self._gates.pop(logger, None)
        if prior and logger.level == prior[1]:
            logger.setLevel(prior[0])

    def _restore_handlers(self) -> None:
        root = logging.getLogger()
        for handler in self._detached:
            root.addHandler(handler)
        self._detached.clear()

    def _reconcile(self, old: Config | None, new: Config, authorized: set[str]) -> None:
        root = logging.getLogger()
        if new.manage_root_level and (old is None or not old.manage_root_level):
            self._install_gate(root, logging.NOTSET)
        elif not new.manage_root_level:
            self._restore_gate(root)
        old_rules = old.package_rules if old else {}
        for name in old_rules.keys() - new.package_rules.keys():
            self._restore_gate(logging.getLogger(name))
        for name, value in new.package_rules.items():
            if name in authorized or old_rules.get(name, OMITTED) != value:
                self._install_gate(logging.getLogger(name), NAMED_CREATION_GATE_INT)
        replacing = new.root_handler_policy == REPLACE_POLICY_STR
        was_replacing = old is not None and old.root_handler_policy == REPLACE_POLICY_STR
        if replacing and not was_replacing:
            for handler in root.handlers[:]:
                if handler is not self._handler:
                    self._detached.append(handler)
                    root.removeHandler(handler)
        elif was_replacing and not replacing:
            self._restore_handlers()

    def emit(self, record: logging.LogRecord) -> None:
        # A faulty provider or repr implementation may itself use logging.
        # Suppress recursive owned dispatch without disturbing foreign handlers.
        if getattr(self._emitting, "active", False):
            return
        with self._state:
            snapshot = self._snapshot
            if snapshot is None or record.levelno < snapshot.config.threshold(record.name):
                return
            resources = tuple(
                resource for resource in snapshot.resources
                if resource is snapshot.console or record.levelno >= snapshot.config.sentry_level
            )
            if not resources:
                return
            for resource in resources:
                resource.users += 1
        self._emitting.active = True
        try:
            event = make_event(
                record, snapshot.config.package_name, snapshot.config.duration_precision
            )
            for resource in resources:
                try:
                    resource.provider.emit(event)
                except Exception:
                    # Never expose provider exception strings (which may contain
                    # credentials) or recursively log delivery diagnostics.
                    continue
        finally:
            self._emitting.active = False
            with self._state:
                for resource in resources:
                    self._release(resource)

    def _release(self, resource: _Resource) -> None:
        resource.users -= 1
        self._idle_condition.notify_all()

    def _retire(self, resource: _Resource) -> None:
        resource.retired = True
        self._retired.append(resource)
        self._start_cleanup(resource)

    def _start_cleanup(self, resource: _Resource) -> None:
        if resource.closed or (resource.cleanup and not resource.cleanup.done.is_set()):
            return
        job = _Job()
        resource.cleanup = job

        def cleanup() -> None:
            try:
                with self._idle_condition:
                    self._idle_condition.wait_for(lambda: resource.users == 0)
                result = resource.provider.close(DEFAULT_TIMEOUT_SECONDS_FLOAT)
                with self._state:
                    resource.closed = result
                    job.result = result
            except Exception:
                job.result = False
            finally:
                job.done.set()

        threading.Thread(target=cleanup, name=LIFECYCLE_THREAD_NAME_STR, daemon=True).start()

    def _flush_job(self, resource: _Resource, deadline: float) -> _Job:
        if resource.flushing and not resource.flushing.done.is_set():
            return resource.flushing
        job = _Job()
        resource.flushing = job
        resource.users += 1  # prevents a concurrent retirement from closing it

        def drain() -> None:
            try:
                job.result = resource.provider.flush(max(0.0, deadline - time.monotonic()))
            except Exception:
                job.result = False
            finally:
                with self._state:
                    self._release(resource)
                job.done.set()

        threading.Thread(target=drain, name=LIFECYCLE_THREAD_NAME_STR, daemon=True).start()
        return job

    def flush(self, timeout: float) -> bool:
        deadline = time.monotonic() + _timeout(timeout)
        with self._state:
            resources = self._snapshot.resources if self._snapshot else ()
            jobs = [self._flush_job(resource, deadline) for resource in resources]
            retired = tuple(self._retired)
        for job in jobs:
            job.done.wait(max(0.0, deadline - time.monotonic()))
        return all(job.done.is_set() and job.result for job in jobs) and self._wait_retired(
            retired, deadline
        )

    def _wait_retired(self, resources: tuple[_Resource, ...], deadline: float) -> bool:
        for resource in resources:
            with self._state:
                if resource.closed:
                    continue
                job = resource.cleanup
            if job:
                job.done.wait(max(0.0, deadline - time.monotonic()))
            if not resource.closed:
                return False
        with self._state:
            self._retired = [resource for resource in self._retired if not resource.closed]
        return True

    def shutdown(self, timeout: float) -> bool:
        deadline = time.monotonic() + _timeout(timeout)
        # Do not let a slow concurrent configure consume an unbounded deadline.
        if not self._transition.acquire(timeout=max(0.0, deadline - time.monotonic())):
            return False
        try:
            with self._state:
                self._stopped = True
                old = self._snapshot
                self._snapshot = None
                if self._handler is not None:
                    logging.getLogger().removeHandler(self._handler)
                    self._handler.close()
                    self._handler = None
                self._restore_handlers()
                for logger in tuple(self._gates):
                    self._restore_gate(logger)
                if old:
                    for resource in old.resources:
                        self._retire(resource)
                for resource in self._retired:
                    if resource.users == 0:
                        self._start_cleanup(resource)
                retired = tuple(self._retired)
        finally:
            self._transition.release()
        return self._wait_retired(retired, deadline)


RUNTIME = Runtime()

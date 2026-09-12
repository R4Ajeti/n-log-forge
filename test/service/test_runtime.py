"""Behavioral tests for the process-local logging composition root."""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest

from n_log_forge.core.constant.configuration_constant import (
    ENVIRONMENT_KEYS_MAPPING,
    PACKAGE_RULES_KEY_STR,
)
from n_log_forge.core.constant.runtime_constant import OWNED_HANDLER_NAME_STR
from n_log_forge.core.helper.event import Event, thaw
from n_log_forge.core.proxy import sentry as sentry_module
from n_log_forge.core.service import runtime as runtime_module
from n_log_forge.core.service.configuration import ConfigurationError


class RecordingProvider:
    """Controllable provider boundary with no streams, sleeps, or network work."""

    def __init__(self, timestamp_format: str | None) -> None:
        self.timestamp_format = timestamp_format
        self.events: list[Event] = []
        self.emit_entered = threading.Event()
        self.emit_finished = threading.Event()
        self.emit_release: threading.Event | None = None
        self.flush_entered = threading.Event()
        self.flush_finished = threading.Event()
        self.flush_release: threading.Event | None = None
        self.close_entered = threading.Event()
        self.close_finished = threading.Event()
        self.close_release: threading.Event | None = None
        self.flush_result = True
        self.close_result = True
        self.flush_timeouts: list[float] = []
        self.close_timeouts: list[float] = []
        self._lock = threading.Lock()

    def emit(self, event: Event) -> None:
        self.emit_entered.set()
        if self.emit_release is not None:
            self.emit_release.wait()
        with self._lock:
            self.events.append(event)
        self.emit_finished.set()

    def flush(self, timeout: float) -> bool:
        self.flush_timeouts.append(timeout)
        self.flush_entered.set()
        if self.flush_release is not None:
            self.flush_release.wait()
        self.flush_finished.set()
        return self.flush_result

    def close(self, timeout: float) -> bool:
        self.close_timeouts.append(timeout)
        self.close_entered.set()
        if self.close_release is not None:
            self.close_release.wait()
        self.close_finished.set()
        return self.close_result

    def release(self) -> None:
        for gate in (self.emit_release, self.flush_release, self.close_release):
            if gate is not None:
                gate.set()


class ProviderFactory:
    def __init__(self) -> None:
        self.instances: list[RecordingProvider] = []
        self.fail_formats: set[str | None] = set()
        self._lock = threading.Lock()

    def __call__(self, timestamp_format: str | None = None) -> RecordingProvider:
        if timestamp_format in self.fail_formats:
            raise RuntimeError("controlled provider construction failure")
        provider = RecordingProvider(timestamp_format)
        with self._lock:
            self.instances.append(provider)
        return provider

    def release_all(self) -> None:
        for provider in self.instances:
            provider.release()


class RecordingSentryProvider(RecordingProvider):
    def __init__(
        self, dsn: str, environment: str | None, release: str | None
    ) -> None:
        super().__init__(None)
        self.construction = (str(dsn), environment, release)
        self.emit_calls = 0
        self.emit_error: BaseException | None = None
        self.on_emit: Callable[[], None] | None = None

    def emit(self, event: Event) -> None:
        self.emit_calls += 1
        if self.on_emit is not None:
            self.on_emit()
        if self.emit_error is not None:
            raise self.emit_error
        super().emit(event)


class SentryProviderFactory:
    def __init__(self) -> None:
        self.instances: list[RecordingSentryProvider] = []
        self.fail = False

    def __call__(
        self, dsn: str, environment: str | None, release: str | None
    ) -> RecordingSentryProvider:
        if self.fail:
            raise RuntimeError("controlled Sentry construction failure")
        provider = RecordingSentryProvider(dsn, environment, release)
        self.instances.append(provider)
        return provider


@dataclass
class RuntimeHarness:
    runtime: runtime_module.Runtime
    factory: ProviderFactory
    prefix: str

    def name(self, suffix: str) -> str:
        return f"{self.prefix}.{suffix}"


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch) -> RuntimeHarness:
    root = logging.getLogger()
    original_level = root.level
    original_disabled = root.disabled
    original_handlers = root.handlers[:]
    original_filters = root.filters[:]
    original_manager_disable = logging.root.manager.disable
    prefix = f"nlf_runtime_{uuid.uuid4().hex}"
    for variable in (*ENVIRONMENT_KEYS_MAPPING.values(), PACKAGE_RULES_KEY_STR):
        monkeypatch.delenv(variable, raising=False)
    logging.disable(logging.NOTSET)
    factory = ProviderFactory()
    monkeypatch.setattr(runtime_module, "ConsoleProvider", factory)
    owned_runtime = runtime_module.Runtime()
    value = RuntimeHarness(owned_runtime, factory, prefix)
    try:
        yield value
    finally:
        factory.release_all()
        owned_runtime.shutdown(1.0)
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)
        root.disabled = original_disabled
        root.filters[:] = original_filters
        logging.disable(original_manager_disable)
        for name in tuple(logging.root.manager.loggerDict):
            if name == prefix or name.startswith(prefix + "."):
                logging.root.manager.loggerDict.pop(name, None)


def owned_handlers(runtime: runtime_module.Runtime) -> list[logging.Handler]:
    return [
        handler
        for handler in logging.getLogger().handlers
        if handler.name == OWNED_HANDLER_NAME_STR
        and getattr(handler, "runtime", None) is runtime
    ]


def test_concurrent_first_use_is_lazy_and_installs_one_reusable_pipeline(
    harness: RuntimeHarness,
) -> None:
    root = logging.getLogger()
    initial_level = root.level
    initial_handlers = root.handlers[:]
    assert harness.factory.instances == []
    assert owned_handlers(harness.runtime) == []
    assert root.level == initial_level
    assert root.handlers == initial_handlers

    barrier = threading.Barrier(9)
    results: list[bool] = []
    errors: list[BaseException] = []

    def initialize() -> None:
        try:
            barrier.wait()
            results.append(harness.runtime.enabled(harness.name("worker"), logging.INFO))
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=initialize) for _ in range(8)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(1.0)
    assert all(not thread.is_alive() for thread in threads)
    assert errors == []
    assert results == [True] * 8
    assert len(harness.factory.instances) == 1
    assert len(owned_handlers(harness.runtime)) == 1

    handler = owned_handlers(harness.runtime)[0]
    for level in (logging.DEBUG, logging.WARNING, logging.ERROR):
        harness.runtime.configure({"level": level})
    assert owned_handlers(harness.runtime) == [handler]
    assert len(harness.factory.instances) == 1


def test_failed_initialization_rolls_back_and_later_retries_environment(
    harness: RuntimeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    initial_handlers = root.handlers[:]
    monkeypatch.setenv("LOGGER", "banana")

    with pytest.raises(ConfigurationError, match="environment LOGGER.*level"):
        harness.runtime.enabled(harness.name("retry"), logging.INFO)
    assert root.level == logging.WARNING
    assert root.handlers == initial_handlers
    assert harness.factory.instances == []

    monkeypatch.setenv("LOGGER", "info")
    assert harness.runtime.enabled(harness.name("retry"), logging.INFO)
    assert root.level == logging.NOTSET
    assert len(owned_handlers(harness.runtime)) == 1
    assert len(harness.factory.instances) == 1


def test_failed_reconfiguration_keeps_snapshot_handler_and_provider(
    harness: RuntimeHarness,
) -> None:
    harness.runtime.configure({"level": "info", "packageName": "Before"})
    handler = owned_handlers(harness.runtime)[0]
    provider = harness.factory.instances[0]
    harness.factory.fail_formats.add("%H")

    with pytest.raises(RuntimeError, match="controlled provider"):
        harness.runtime.configure(
            {"timestampFormat": "%H", "level": "debug", "packageName": "After"}
        )

    assert owned_handlers(harness.runtime) == [handler]
    logging.getLogger(harness.name("rollback")).info("retained")
    assert [event.message for event in provider.events] == ["retained"]
    assert provider.events[0].package_name == "Before"
    assert not harness.runtime.enabled(harness.name("rollback"), logging.DEBUG)


def test_failed_environment_reload_preserves_the_previous_complete_snapshot(
    harness: RuntimeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = harness.name("environment")
    monkeypatch.setenv("LOGGER", "warning")
    harness.runtime.configure({}, reload=True)
    handler = owned_handlers(harness.runtime)[0]
    provider = harness.factory.instances[0]
    assert harness.runtime.enabled(name, logging.WARNING)
    assert not harness.runtime.enabled(name, logging.INFO)

    monkeypatch.setenv("LOGGER", "banana")
    with pytest.raises(ConfigurationError, match="environment LOGGER.*level"):
        harness.runtime.configure({}, reload=True)
    assert owned_handlers(harness.runtime) == [handler]
    assert harness.factory.instances == [provider]
    assert harness.runtime.enabled(name, logging.WARNING)
    assert not harness.runtime.enabled(name, logging.INFO)

    monkeypatch.setenv("LOGGER", "debug")
    harness.runtime.configure({})
    assert not harness.runtime.enabled(name, logging.INFO)
    harness.runtime.configure({}, reload=True)
    assert harness.runtime.enabled(name, logging.DEBUG)


def test_incremental_overrides_retain_omissions_and_none_reveals_environment(
    harness: RuntimeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGGER", "warning")
    monkeypatch.setenv("PACKAGE_NAME", "Environment Name")
    harness.runtime.configure({}, reload=True)
    harness.runtime.configure({"level": "debug", "packageName": "Runtime Name"})
    harness.runtime.configure({"durationPrecision": 2})
    name = harness.name("incremental")
    assert harness.runtime.enabled(name, logging.DEBUG)

    logging.getLogger(name).error("runtime overrides")
    assert harness.factory.instances[0].events[-1].package_name == "Runtime Name"

    harness.runtime.configure({"level": None, "packageName": None})
    assert not harness.runtime.enabled(name, logging.INFO)
    assert harness.runtime.enabled(name, logging.WARNING)
    logging.getLogger(name).error("environment revealed")
    assert harness.factory.instances[0].events[-1].package_name == "Environment Name"


def test_environment_reload_removes_values_that_are_now_absent(
    harness: RuntimeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    name = harness.name("removed_environment")
    monkeypatch.setenv("LOGGER", "error")
    harness.runtime.configure({}, reload=True)
    assert not harness.runtime.enabled(name, logging.WARNING)

    monkeypatch.delenv("LOGGER")
    harness.runtime.configure({}, reload=True)
    assert harness.runtime.enabled(name, logging.INFO)


def test_unknown_reset_key_is_rejected_without_changing_active_state(
    harness: RuntimeHarness,
) -> None:
    harness.runtime.configure({"level": "warning"})
    handler = owned_handlers(harness.runtime)[0]
    with pytest.raises(ConfigurationError) as caught:
        harness.runtime.configure({"unknown": None})
    assert caught.value.key == "unknown"
    assert caught.value.source == "runtime"
    assert owned_handlers(harness.runtime) == [handler]
    assert harness.runtime.enabled(harness.name("state"), logging.WARNING)
    assert not harness.runtime.enabled(harness.name("state"), logging.INFO)


def test_root_creation_gate_restoration_and_later_host_changes_are_respected(
    harness: RuntimeHarness,
) -> None:
    root = logging.getLogger()
    root.setLevel(logging.WARNING)
    harness.runtime.configure({})
    assert root.level == logging.NOTSET
    assert harness.runtime.shutdown(1.0)
    assert root.level == logging.WARNING

    harness.runtime.configure({})
    assert root.level == logging.NOTSET
    root.setLevel(logging.ERROR)
    harness.runtime.configure({"packageName": "Unrelated"})
    assert root.level == logging.ERROR
    assert harness.runtime.shutdown(1.0)
    assert root.level == logging.ERROR


def test_manage_root_level_false_preserves_and_restores_the_host_gate(
    harness: RuntimeHarness,
) -> None:
    root = logging.getLogger()
    root.setLevel(logging.ERROR)
    harness.runtime.configure({"level": "debug", "manageRootLevel": False})
    assert root.level == logging.ERROR
    assert not harness.runtime.enabled(harness.name("host-gated"), logging.DEBUG)

    harness.runtime.configure({"manageRootLevel": True})
    assert root.level == logging.NOTSET
    harness.runtime.configure({"manageRootLevel": False})
    assert root.level == logging.ERROR


def test_named_creation_gates_restore_exactly_and_preserve_host_changes(
    harness: RuntimeHarness,
) -> None:
    harness.runtime.configure({})
    first = logging.getLogger(harness.name("first"))
    first.setLevel(logging.ERROR)
    harness.runtime.package_rule(first.name, "debug")
    assert first.level == 1
    harness.runtime.package_rule(first.name)
    assert first.level == logging.ERROR

    second = logging.getLogger(harness.name("second"))
    second.setLevel(logging.CRITICAL)
    harness.runtime.package_rule(second.name, "debug")
    assert second.level == 1
    second.setLevel(logging.WARNING)
    harness.runtime.configure({"packageName": "Unrelated"})
    assert second.level == logging.WARNING
    harness.runtime.package_rule(second.name)
    assert second.level == logging.WARNING


def test_runtime_package_rules_merge_per_exact_name_and_reset_only_that_entry(
    harness: RuntimeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = harness.name("rules")
    child = f"{parent}.api"
    sibling = f"{parent}.worker"
    monkeypatch.setenv("LOGGER", "info")
    monkeypatch.setenv(
        "LOGGER_PACKAGES", f"{parent}=warning,{child}=error"
    )
    harness.runtime.configure({}, reload=True)

    harness.runtime.package_rule(parent, "debug")
    assert harness.runtime.enabled(sibling, logging.DEBUG)
    assert not harness.runtime.enabled(child, logging.WARNING)

    harness.runtime.package_rule(child, 0)
    assert harness.runtime.enabled(child, logging.DEBUG)
    harness.runtime.package_rule(parent)
    assert not harness.runtime.enabled(child, logging.INFO)
    assert harness.runtime.enabled(child, logging.WARNING)

    harness.runtime.package_rule(child)
    assert not harness.runtime.enabled(child, logging.WARNING)
    assert harness.runtime.enabled(child, logging.ERROR)


class TrackingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []
        self.close_calls = 0

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def close(self) -> None:
        self.close_calls += 1
        super().close()


def test_preserve_and_opt_in_replace_own_only_root_handlers(
    harness: RuntimeHarness,
) -> None:
    root = logging.getLogger()
    foreign = TrackingHandler()
    descendant = TrackingHandler()
    root.addHandler(foreign)
    logging.getLogger(harness.name("descendant")).addHandler(descendant)

    harness.runtime.configure({})
    assert foreign in root.handlers
    assert descendant in logging.getLogger(harness.name("descendant")).handlers

    harness.runtime.configure({"rootHandlerPolicy": "replace"})
    assert foreign not in root.handlers
    assert descendant in logging.getLogger(harness.name("descendant")).handlers
    assert foreign.close_calls == 0

    added_later = TrackingHandler()
    root.addHandler(added_later)
    harness.runtime.configure({"level": "debug"})
    assert added_later in root.handlers

    harness.runtime.configure({"rootHandlerPolicy": "preserve"})
    assert root.handlers.count(foreign) == 1
    assert root.handlers.count(added_later) == 1
    assert foreign.close_calls == 0


def test_replace_mode_restores_detached_handlers_on_shutdown(
    harness: RuntimeHarness,
) -> None:
    root = logging.getLogger()
    foreign = TrackingHandler()
    root.addHandler(foreign)
    harness.runtime.configure({"rootHandlerPolicy": "replace"})
    assert foreign not in root.handlers
    assert harness.runtime.shutdown(1.0)
    assert root.handlers.count(foreign) == 1
    assert foreign.close_calls == 0


def test_hierarchy_filter_and_exact_rule_bypass_restrictive_ancestor(
    harness: RuntimeHarness,
) -> None:
    harness.runtime.configure({"level": "debug", "rootHandlerPolicy": "replace"})
    provider = harness.factory.instances[0]
    parent = logging.getLogger(harness.name("package"))
    child = logging.getLogger(harness.name("package.child"))
    parent.setLevel(logging.ERROR)

    child.info("blocked by inherited creation gate")
    assert provider.events == []
    harness.runtime.package_rule(child.name, "debug")
    assert child.level == 1
    child.debug("accepted below ancestor")
    assert [event.message for event in provider.events] == ["accepted below ancestor"]

    provider.events.clear()
    harness.runtime.package_rule(parent.name, "warning")
    harness.runtime.package_rule(child.name)
    child.setLevel(logging.NOTSET)
    child.info("rejected by owned hierarchy")
    child.warning("accepted by owned hierarchy")
    assert [event.message for event in provider.events] == ["accepted by owned hierarchy"]


def test_standard_disabled_global_disable_filters_and_propagation_remain_authoritative(
    harness: RuntimeHarness,
) -> None:
    harness.runtime.configure({"level": "debug", "rootHandlerPolicy": "replace"})
    provider = harness.factory.instances[0]
    logger = logging.getLogger(harness.name("controls"))

    logger.disabled = True
    logger.error("disabled")
    logger.disabled = False
    logging.disable(logging.CRITICAL)
    logger.error("globally disabled")
    logging.disable(logging.NOTSET)

    class Reject(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            return False

    rejection = Reject()
    logger.addFilter(rejection)
    logger.error("filtered")
    logger.removeFilter(rejection)
    logger.propagate = False
    logger.error("not propagated")
    logger.propagate = True
    logger.setLevel(logging.ERROR)
    logger.info("creation gated")
    assert provider.events == []


def test_incoming_record_is_not_mutated_and_custom_severity_is_preserved(
    harness: RuntimeHarness,
) -> None:
    harness.runtime.configure({"level": 0, "rootHandlerPolicy": "replace"})
    provider = harness.factory.instances[0]
    observer = TrackingHandler()
    logging.getLogger().addHandler(observer)
    payload = {"items": [1]}
    logger = logging.getLogger(harness.name("third_party"))

    logger.log(35, "Processed %s", 12, extra={"payload": payload})
    event = provider.events[-1]
    observed = observer.records[-1]
    assert event.level == 35
    assert event.level_name == "Level 35"
    assert event.message == "Processed 12"
    assert observed.msg == "Processed %s"
    assert observed.args == (12,)
    assert "message" not in observed.__dict__
    assert "asctime" not in observed.__dict__
    payload["items"].append(2)
    assert thaw(event.metadata) == {"payload": {"items": [1]}}

    logger.log(60, "above configured range")
    assert provider.events[-1].level == 60
    assert provider.events[-1].level_name == "Level 60"


def test_both_owned_providers_disabled_leave_foreign_delivery_independent(
    harness: RuntimeHarness,
) -> None:
    foreign = TrackingHandler()
    logging.getLogger().addHandler(foreign)
    harness.runtime.configure({"consoleEnabled": False})
    assert harness.factory.instances == []
    assert len(owned_handlers(harness.runtime)) == 1

    logging.getLogger(harness.name("foreign-only")).warning("host output")
    assert [record.getMessage() for record in foreign.records] == ["host output"]


def test_event_materialization_errors_are_isolated_but_base_exceptions_propagate(
    harness: RuntimeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness.runtime.configure({"rootHandlerPolicy": "replace"})
    provider = harness.factory.instances[0]
    logger = logging.getLogger(harness.name("materialize"))

    def fail_event(*args: Any, **kwargs: Any) -> Event:
        raise RuntimeError("broken host record")

    monkeypatch.setattr(runtime_module, "make_event", fail_event)
    logger.info("must not escape")
    assert provider.events == []

    def interrupt_event(*args: Any, **kwargs: Any) -> Event:
        raise KeyboardInterrupt

    monkeypatch.setattr(runtime_module, "make_event", interrupt_event)
    with pytest.raises(KeyboardInterrupt):
        logger.info("interrupt")

    harness.runtime.configure({"timestampFormat": "%H"})
    assert provider.close_entered.wait(1.0)


def test_provider_reuse_and_replacement_wait_for_in_flight_emitters(
    harness: RuntimeHarness,
) -> None:
    harness.runtime.configure({"level": "info", "rootHandlerPolicy": "replace"})
    first = harness.factory.instances[0]
    harness.runtime.configure({"level": "debug", "packageName": "Changed"})
    assert harness.factory.instances == [first]

    first.emit_release = threading.Event()
    logger = logging.getLogger(harness.name("in_flight"))
    emitter = threading.Thread(target=logger.info, args=("old snapshot",))
    emitter.start()
    assert first.emit_entered.wait(1.0)

    harness.runtime.configure({"timestampFormat": "%H:%M"})
    assert len(harness.factory.instances) == 2
    second = harness.factory.instances[1]
    assert not first.close_entered.is_set()
    first.emit_release.set()
    emitter.join(1.0)
    assert not emitter.is_alive()
    assert first.close_entered.wait(1.0)
    assert first.close_finished.wait(1.0)

    logger.info("new snapshot")
    assert [event.message for event in first.events] == ["old snapshot"]
    assert [event.message for event in second.events] == ["new snapshot"]


def test_flush_and_shutdown_use_bounded_jobs_are_retryable_and_restart(
    harness: RuntimeHarness,
) -> None:
    harness.runtime.configure({"level": "warning"})
    provider = harness.factory.instances[0]
    provider.flush_release = threading.Event()
    assert harness.runtime.flush(0.0) is False
    assert provider.flush_entered.wait(1.0)
    provider.flush_release.set()
    assert provider.flush_finished.wait(1.0)
    assert harness.runtime.flush(1.0) is True

    provider.close_release = threading.Event()
    assert harness.runtime.shutdown(0.0) is False
    assert provider.close_entered.wait(1.0)
    assert not harness.runtime.enabled(harness.name("stopped"), logging.ERROR)
    provider.close_release.set()
    assert provider.close_finished.wait(1.0)
    assert harness.runtime.shutdown(1.0) is True
    assert harness.runtime.shutdown(1.0) is True

    stopped_rule = harness.name("stopped.rule")
    restored_root_level = logging.getLogger().level
    harness.runtime.package_rule(stopped_rule, "debug")
    assert len(harness.factory.instances) == 1
    assert owned_handlers(harness.runtime) == []
    assert logging.getLogger().level == restored_root_level
    assert not harness.runtime.enabled(stopped_rule, logging.DEBUG)

    harness.runtime.configure({})
    assert len(harness.factory.instances) == 2
    assert logging.getLogger(stopped_rule).level == 1
    assert harness.runtime.enabled(stopped_rule, logging.DEBUG)
    assert harness.runtime.enabled(harness.name("restarted"), logging.WARNING)
    assert not harness.runtime.enabled(harness.name("restarted"), logging.INFO)


def test_shutdown_of_unused_runtime_does_not_initialize_it(harness: RuntimeHarness) -> None:
    root = logging.getLogger()
    original_level = root.level
    original_handlers = root.handlers[:]
    assert harness.runtime.flush(0.0)
    assert harness.factory.instances == []
    assert harness.runtime.shutdown(0.0)
    assert harness.factory.instances == []
    assert root.level == original_level
    assert root.handlers == original_handlers


@pytest.mark.parametrize("value", [True, False])
def test_lifecycle_timeout_rejects_booleans(harness: RuntimeHarness, value: bool) -> None:
    with pytest.raises(TypeError, match="timeout"):
        harness.runtime.flush(value)
    with pytest.raises(TypeError, match="timeout"):
        harness.runtime.shutdown(value)


@pytest.mark.parametrize("value", [-1.0, float("inf"), float("nan")])
def test_lifecycle_timeout_rejects_negative_or_nonfinite_values(
    harness: RuntimeHarness, value: float
) -> None:
    with pytest.raises(ValueError, match="timeout"):
        harness.runtime.flush(value)
    with pytest.raises(ValueError, match="timeout"):
        harness.runtime.shutdown(value)


def test_simultaneous_logging_and_reconfiguration_publish_coherent_snapshots(
    harness: RuntimeHarness,
) -> None:
    harness.runtime.configure(
        {"level": "debug", "packageName": "Old", "rootHandlerPolicy": "replace"}
    )
    provider = harness.factory.instances[0]
    logger = logging.getLogger(harness.name("concurrent"))
    barrier = threading.Barrier(3)
    first_emitted = threading.Event()
    errors: list[BaseException] = []

    def emit_many() -> None:
        try:
            barrier.wait()
            logger.info("initial accepted event")
            first_emitted.set()
            for index in range(300):
                logger.info("event %s", index)
        except BaseException as error:
            errors.append(error)

    def update_many() -> None:
        try:
            barrier.wait()
            if not first_emitted.wait(1.0):
                raise AssertionError("emitter did not reach the provider boundary")
            for index in range(100):
                harness.runtime.configure(
                    {"packageName": "New" if index % 2 else "Old", "level": 10 + index % 41}
                )
        except BaseException as error:
            errors.append(error)

    emitter = threading.Thread(target=emit_many)
    updater = threading.Thread(target=update_many)
    emitter.start()
    updater.start()
    barrier.wait()
    emitter.join(3.0)
    updater.join(3.0)
    assert not emitter.is_alive()
    assert not updater.is_alive()
    assert errors == []
    assert harness.factory.instances == [provider]
    assert provider.events
    assert {event.package_name for event in provider.events} <= {"Old", "New"}
    assert len(owned_handlers(harness.runtime)) == 1


def test_sentry_and_logger_thresholds_are_conjunctive_and_zero_is_unrestricted(
    harness: RuntimeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentry_factory = SentryProviderFactory()
    monkeypatch.setattr(sentry_module, "SentryProvider", sentry_factory)
    harness.runtime.configure(
        {
            "level": "warning",
            "sentryDataSourceName": "https://public@example.invalid/1",
            "sentryLevel": "debug",
            "rootHandlerPolicy": "replace",
        }
    )
    console = harness.factory.instances[0]
    sentry = sentry_factory.instances[0]
    logger = logging.getLogger(harness.name("thresholds"))

    logger.info("globally rejected")
    logger.warning("accepted by both")
    assert [event.message for event in console.events] == ["accepted by both"]
    assert [event.message for event in sentry.events] == ["accepted by both"]

    harness.runtime.configure({"level": 0, "sentryLevel": 0})
    logger.log(5, "custom low severity")
    assert console.events[-1].level == 5
    assert sentry.events[-1].level == 5
    assert sentry_factory.instances == [sentry]


def test_sentry_reuse_setup_rollback_replacement_and_disable(
    harness: RuntimeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentry_factory = SentryProviderFactory()
    monkeypatch.setattr(sentry_module, "SentryProvider", sentry_factory)
    dsn = "https://public@example.invalid/1"
    harness.runtime.configure(
        {
            "level": "debug",
            "sentryDataSourceName": dsn,
            "sentryEnvironment": "staging",
            "rootHandlerPolicy": "replace",
        }
    )
    first = sentry_factory.instances[0]
    logger = logging.getLogger(harness.name("sentry_lifecycle"))

    harness.runtime.configure(
        {"sentryLevel": "debug", "packageName": "Still the same client"}
    )
    assert sentry_factory.instances == [first]

    sentry_factory.fail = True
    with pytest.raises(RuntimeError, match="controlled Sentry construction"):
        harness.runtime.configure({"sentryRelease": "2.0"})
    logger.error("old snapshot retained")
    assert [event.message for event in first.events] == ["old snapshot retained"]
    assert first.events[0].package_name == "Still the same client"

    sentry_factory.fail = False
    harness.runtime.configure({"sentryRelease": "2.0"})
    second = sentry_factory.instances[1]
    assert second.construction == (dsn, "staging", "2.0")
    assert first.close_entered.wait(1.0)
    logger.error("replacement")
    assert [event.message for event in second.events] == ["replacement"]

    harness.runtime.configure({"sentryDataSourceName": ""})
    assert second.close_entered.wait(1.0)
    logger.error("console only")
    assert [event.message for event in second.events] == ["replacement"]
    assert harness.factory.instances[0].events[-1].message == "console only"


def test_sentry_blank_override_masks_environment_and_none_reveals_it(
    harness: RuntimeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentry_factory = SentryProviderFactory()
    monkeypatch.setattr(sentry_module, "SentryProvider", sentry_factory)
    monkeypatch.setenv(
        "SENTRY_DATA_SOURCE_NAME", "https://environment@example.invalid/99"
    )

    harness.runtime.configure({"sentryDataSourceName": ""}, reload=True)
    assert sentry_factory.instances == []
    harness.runtime.configure({"sentryDataSourceName": None})
    assert len(sentry_factory.instances) == 1
    assert sentry_factory.instances[0].construction[0].endswith(
        "environment@example.invalid/99"
    )


def test_remote_failure_does_not_suppress_console_and_recursive_capture_is_blocked(
    harness: RuntimeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentry_factory = SentryProviderFactory()
    monkeypatch.setattr(sentry_module, "SentryProvider", sentry_factory)
    harness.runtime.configure(
        {
            "sentryDataSourceName": "https://public@example.invalid/1",
            "rootHandlerPolicy": "replace",
        }
    )
    console = harness.factory.instances[0]
    sentry = sentry_factory.instances[0]
    logger = logging.getLogger(harness.name("remote_failure"))

    sentry.emit_error = RuntimeError("remote failure with possible credentials")
    logger.error("console survives")
    assert console.events[-1].message == "console survives"

    sentry.emit_error = None
    sentry.on_emit = lambda: logger.error("recursive provider diagnostic")
    logger.error("outer event")
    assert sentry.emit_calls == 2
    assert [event.message for event in sentry.events] == ["outer event"]
    assert console.events[-1].message == "outer event"

    capture_count = sentry.emit_calls
    # Exercise the owned delivery boundary directly. The real SDK installs a filter on
    # this logger, and host filters are intentionally authoritative before root dispatch.
    sdk_record = logging.LogRecord(
        "sentry_sdk.errors",
        logging.ERROR,
        __file__,
        1,
        "background transport failure",
        (),
        None,
    )
    harness.runtime.emit(sdk_record)
    assert sentry.emit_calls == capture_count
    assert console.events[-1].message == "background transport failure"

    sentry.on_emit = None
    sentry.emit_error = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        logger.error("interrupt")

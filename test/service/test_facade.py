"""Public facade behavior exercised at the owned provider boundary."""

from __future__ import annotations

import inspect
import logging
import uuid
from dataclasses import dataclass
from typing import Any

import pytest

import n_log_forge
from core.constant.configuration_constant import ENVIRONMENT_KEYS_MAPPING, PACKAGE_RULES_KEY_STR
from core.helper.event import Event, thaw
from core.service import facade as facade_module
from core.service import runtime as runtime_module


class FacadeProvider:
    def __init__(self, timestamp_format: str | None = None) -> None:
        self.timestamp_format = timestamp_format
        self.events: list[Event] = []

    def emit(self, event: Event) -> None:
        self.events.append(event)

    def flush(self, timeout: float) -> bool:
        return True

    def close(self, timeout: float) -> bool:
        return True


class FacadeProviderFactory:
    def __init__(self) -> None:
        self.instances: list[FacadeProvider] = []

    def __call__(self, timestamp_format: str | None = None) -> FacadeProvider:
        provider = FacadeProvider(timestamp_format)
        self.instances.append(provider)
        return provider


@dataclass
class FacadeHarness:
    runtime: runtime_module.Runtime
    factory: FacadeProviderFactory
    prefix: str

    def name(self, suffix: str) -> str:
        return f"{self.prefix}.{suffix}"

    @property
    def provider(self) -> FacadeProvider:
        return self.factory.instances[-1]


@pytest.fixture
def facade_harness(monkeypatch: pytest.MonkeyPatch) -> FacadeHarness:
    root = logging.getLogger()
    original_level = root.level
    original_disabled = root.disabled
    original_handlers = root.handlers[:]
    original_filters = root.filters[:]
    original_manager_disable = logging.root.manager.disable
    prefix = f"nlf_facade_{uuid.uuid4().hex}"
    for variable in (*ENVIRONMENT_KEYS_MAPPING.values(), PACKAGE_RULES_KEY_STR):
        monkeypatch.delenv(variable, raising=False)
    logging.disable(logging.NOTSET)
    factory = FacadeProviderFactory()
    monkeypatch.setattr(runtime_module, "ConsoleProvider", factory)
    owned_runtime = runtime_module.Runtime()
    monkeypatch.setattr(runtime_module, "RUNTIME", owned_runtime)
    value = FacadeHarness(owned_runtime, factory, prefix)
    try:
        yield value
    finally:
        owned_runtime.shutdown(1.0)
        for handler in root.handlers[:]:
            root.removeHandler(handler)
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)
        root.disabled = original_disabled
        root.filters[:] = original_filters
        logging.disable(original_manager_disable)
        for name in tuple(facade_module._FACADES):
            if name == prefix or name.startswith(prefix + "."):
                facade_module._FACADES.pop(name, None)
        for name in tuple(logging.root.manager.loggerDict):
            if name == prefix or name.startswith(prefix + "."):
                logging.root.manager.loggerDict.pop(name, None)


def test_public_logger_lookup_is_passive_cached_and_not_a_standard_logger(
    facade_harness: FacadeHarness,
) -> None:
    root = logging.getLogger()
    initial_level = root.level
    initial_handlers = root.handlers[:]
    name = facade_harness.name("lookup")

    first = n_log_forge.getLogger(f"  {name}  ")
    second = n_log_forge.getLogger(name)
    assert first is second
    assert first.name == name
    assert not isinstance(first, logging.Logger)
    assert facade_harness.factory.instances == []
    assert root.level == initial_level
    assert root.handlers == initial_handlers

    for invalid in ("", "   ", "bad..name", "bad name", None):
        with pytest.raises(ValueError):
            n_log_forge.getLogger(invalid)  # type: ignore[arg-type]


def test_configure_is_keyword_only_eager_and_unknown_keywords_are_rejected(
    facade_harness: FacadeHarness,
) -> None:
    with pytest.raises(TypeError):
        n_log_forge.configure("info")  # type: ignore[misc]
    with pytest.raises(TypeError, match="unexpected keyword"):
        n_log_forge.configure(unknown=True)  # type: ignore[call-arg]
    assert facade_harness.factory.instances == []

    n_log_forge.configure()
    assert len(facade_harness.factory.instances) == 1
    assert any(
        getattr(handler, "runtime", None) is facade_harness.runtime
        for handler in logging.getLogger().handlers
    )


def test_existing_facade_observes_updates_shutdown_and_explicit_restart(
    facade_harness: FacadeHarness,
) -> None:
    logger = n_log_forge.getLogger(facade_harness.name("updates"))
    n_log_forge.configure(level="error", rootHandlerPolicy="replace")
    assert not logger.isEnabledFor(logging.INFO)
    assert logger.isEnabledFor(logging.ERROR)

    n_log_forge.configure(level="info")
    assert logger.isEnabledFor(logging.INFO)
    assert n_log_forge.flush(1.0)
    assert n_log_forge.shutdown(1.0)
    assert not logger.isEnabledFor(logging.CRITICAL)
    logger.critical("dropped while stopped")

    n_log_forge.configure()
    assert logger.isEnabledFor(logging.INFO)
    logger.info("after restart")
    assert facade_harness.provider.events[-1].message == "after restart"


def test_rejected_facade_calls_keep_message_and_metadata_values_lazy(
    facade_harness: FacadeHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    n_log_forge.configure(level="info", rootHandlerPolicy="replace")
    logger = n_log_forge.getLogger(facade_harness.name("lazy"))
    conversions: list[str] = []

    class Deferred:
        def __str__(self) -> str:
            conversions.append("str")
            return "materialized"

        def __repr__(self) -> str:
            conversions.append("repr")
            return "Deferred()"

    message_value = Deferred()
    metadata_value = Deferred()

    def unexpected_caller(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("named rejected calls must not inspect the caller")

    monkeypatch.setattr(facade_module, "resolve_caller", unexpected_caller)
    logger.debug("value=%s", message_value, payload=metadata_value)
    assert conversions == []
    assert facade_harness.provider.events == []

    logger.info("value=%s", message_value)
    assert conversions == ["str"]
    assert facade_harness.provider.events[-1].message == "value=materialized"


def _ordinary_wrapper(logger: facade_module.Logger) -> None:
    logger.info("ordinary caller")


def _stacklevel_wrapper(logger: facade_module.Logger) -> None:
    logger.info("selected caller", stacklevel=2)


def _global_stacklevel_wrapper() -> None:
    n_log_forge.logger.info("global selected caller", stacklevel=2)


def test_named_facade_preserves_source_and_actual_caller_with_stacklevel(
    facade_harness: FacadeHarness,
) -> None:
    n_log_forge.configure(level="info", rootHandlerPolicy="replace")
    name = facade_harness.name("named")
    logger = n_log_forge.getLogger(name)
    _ordinary_wrapper(logger)
    expected_line = inspect.currentframe().f_lineno + 1
    _stacklevel_wrapper(logger)

    ordinary, selected = facade_harness.provider.events
    assert ordinary.source == name
    assert ordinary.function == "_ordinary_wrapper"
    assert ordinary.pathname == __file__
    assert selected.source == name
    assert selected.function == (
        "test_named_facade_preserves_source_and_actual_caller_with_stacklevel"
    )
    assert selected.pathname == __file__
    assert selected.lineno == expected_line


def test_global_facade_stacklevel_selects_source_and_record_caller_together(
    facade_harness: FacadeHarness,
) -> None:
    n_log_forge.configure(level="info", rootHandlerPolicy="replace")
    expected_line = inspect.currentframe().f_lineno + 1
    _global_stacklevel_wrapper()
    event = facade_harness.provider.events[-1]
    assert event.source == __name__
    assert event.pathname == __file__
    assert event.function == (
        "test_global_facade_stacklevel_selects_source_and_record_caller_together"
    )
    assert event.lineno == expected_line


def test_global_facade_resolves_each_module_and_package_specific_debug_rule(
    facade_harness: FacadeHarness,
) -> None:
    n_log_forge.configure(level="info", rootHandlerPolicy="replace")
    first_source = facade_harness.name("module_one")
    second_source = facade_harness.name("module_two")
    for source, filename, message in (
        (first_source, "/virtual/one.py", "one"),
        (second_source, "/virtual/two.py", "two"),
    ):
        namespace = {"__name__": source, "logger": n_log_forge.logger}
        exec(compile(f"logger.info({message!r})", filename, "exec"), namespace)

    first, second = facade_harness.provider.events
    assert (first.source, first.pathname, first.function) == (
        first_source,
        "/virtual/one.py",
        "<module>",
    )
    assert (second.source, second.pathname, second.function) == (
        second_source,
        "/virtual/two.py",
        "<module>",
    )

    n_log_forge.setPackageLevel(second_source, "debug")
    namespace = {"__name__": second_source, "logger": n_log_forge.logger}
    exec(compile("logger.debug('package debug')", "/virtual/debug.py", "exec"), namespace)
    assert facade_harness.provider.events[-1].message == "package debug"
    assert facade_harness.provider.events[-1].source == second_source

    n_log_forge.resetPackageLevel(second_source)
    event_count = len(facade_harness.provider.events)
    exec(compile("logger.debug('reset')", "/virtual/reset.py", "exec"), namespace)
    assert len(facade_harness.provider.events) == event_count


def test_facade_controls_metadata_and_collision_validation(
    facade_harness: FacadeHarness,
) -> None:
    n_log_forge.configure(level=0, rootHandlerPolicy="replace")
    logger = n_log_forge.getLogger(facade_harness.name("metadata"))
    logger.info(
        "metadata",
        extra={"left": {"items": [1]}},
        right="value",
        stack_info=True,
    )
    event = facade_harness.provider.events[-1]
    assert thaw(event.metadata) == {"left": {"items": [1]}, "right": "value"}
    assert event.stack_info is not None
    assert "test_facade_controls_metadata_and_collision_validation" in event.stack_info

    with pytest.raises(ValueError, match="Duplicate"):
        logger.info("bad", extra={"same": 1}, same=2)
    with pytest.raises(ValueError, match="reserved"):
        logger.info("bad", extra={"message": "collision"})
    with pytest.raises(ValueError, match="reserved"):
        logger.info("bad", nlf_internal=True)
    with pytest.raises(TypeError, match="mapping"):
        logger.info("bad", extra=[])
    with pytest.raises(ValueError, match="stacklevel"):
        logger.info("bad", stacklevel=True)


def test_exception_and_timing_context_reach_the_provider_boundary(
    facade_harness: FacadeHarness,
) -> None:
    n_log_forge.configure(level="info", rootHandlerPolicy="replace")
    logger = n_log_forge.getLogger(facade_harness.name("operations"))

    with logger.timed("database_query") as timer:
        logger.info("timed")
    timed_event = facade_harness.provider.events[-1]
    assert timed_event.operation == "database_query"
    assert timed_event.elapsed_ns is not None
    assert timed_event.duration != "-"
    assert timer.elapsedSeconds >= 0

    handle = logger.startTimer("explicit")
    logger.info("explicit timer")
    elapsed = handle.stop()
    assert elapsed == handle.stop() == handle.elapsedSeconds
    assert facade_harness.provider.events[-1].operation == "explicit"

    try:
        raise ValueError("root failure")
    except ValueError:
        logger.exception("operation failed", requestId="abc123")
    failure = facade_harness.provider.events[-1]
    assert failure.level == logging.ERROR
    assert thaw(failure.metadata) == {"requestId": "abc123"}
    assert thaw(failure.exception)["values"][-1]["type"] == "ValueError"
    assert "root failure" in failure.exception_text


def test_all_severity_methods_warn_alias_and_log_validation(
    facade_harness: FacadeHarness,
) -> None:
    n_log_forge.configure(level=0, rootHandlerPolicy="replace")
    logger = n_log_forge.getLogger(facade_harness.name("levels"))
    logger.debug("debug")
    logger.info("info")
    logger.warning("warning")
    logger.warn("warn")
    logger.error("error")
    logger.critical("critical")
    logger.log(15, "custom")
    assert [event.level for event in facade_harness.provider.events] == [
        logging.DEBUG,
        logging.INFO,
        logging.WARNING,
        logging.WARNING,
        logging.ERROR,
        logging.CRITICAL,
        15,
    ]

    for invalid in (0, 51, True, 30.0, "30"):
        with pytest.raises(ValueError, match="severity"):
            logger.log(invalid, "invalid")  # type: ignore[arg-type]
        with pytest.raises(ValueError, match="severity"):
            logger.isEnabledFor(invalid)  # type: ignore[arg-type]

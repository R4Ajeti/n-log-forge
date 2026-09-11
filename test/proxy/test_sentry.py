from __future__ import annotations

import builtins
import json
import logging
import queue
import subprocess
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest

from core.constant import sentry_constant as key
from core.helper.event import Event, make_event
from core.proxy.sentry import SentryProvider, _sentry_level

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_RAW_EXAMPLE = _PROJECT_ROOT / "raw" / "proxy" / "sentry"


class _FakeClient:
    def __init__(self, capture_result: str | None = "event-id") -> None:
        self.capture_result = capture_result
        self.captured: list[dict[str, Any]] = []
        self.scopes: list[object | None] = []
        self.flush_calls: list[float] = []
        self.close_calls: list[float] = []
        self.transport: object | None = SimpleNamespace(
            _worker=SimpleNamespace(_queue=queue.Queue())
        )

    def capture_event(
        self, event: dict[str, Any], *, scope: object | None = None
    ) -> str | None:
        self.captured.append(event)
        self.scopes.append(scope)
        return self.capture_result

    def flush(self, timeout: float) -> None:
        self.flush_calls.append(timeout)

    def close(self, timeout: float) -> None:
        self.close_calls.append(timeout)
        self.transport = None


def _provider(monkeypatch: pytest.MonkeyPatch, client: _FakeClient) -> SentryProvider:
    monkeypatch.setattr(SentryProvider, "_create_client", lambda *_args: client)
    return SentryProvider("https://public-key@example.invalid/123")


def _event(level: int = logging.ERROR, level_name: str = "ERROR") -> Event:
    return Event(
        timestamp=datetime(2026, 9, 9, 20, 35, 43, 21_000, tzinfo=UTC),
        level=level,
        level_name=level_name,
        source="payment_gateway.api",
        package_name="Payment Gateway",
        message="Payment provider unavailable",
        metadata=MappingProxyType({"provider": "stripe"}),
        pathname="payment_gateway/api.py",
        lineno=42,
        function="charge",
        exception=None,
        exception_text=None,
        stack_info=None,
        operation="charge_provider",
        elapsed_ns=1_250_000_000,
        duration="1.3s",
    )


def _require_sentry_sdk() -> Any:
    return pytest.importorskip("sentry_sdk", reason="requires the sentry optional extra")


def test_module_import_is_lazy_and_missing_sdk_error_is_actionable() -> None:
    script = """
import builtins

real_import = builtins.__import__

def blocked_import(name, *args, **kwargs):
    if name == "sentry_sdk" or name.startswith("sentry_sdk."):
        raise ModuleNotFoundError("blocked optional dependency")
    return real_import(name, *args, **kwargs)

builtins.__import__ = blocked_import
from core.proxy.sentry import SentryProvider
print("module imported")
try:
    SentryProvider("https://public-key@example.invalid/123")
except ImportError as error:
    print(str(error))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert completed.stderr == ""
    assert completed.stdout.splitlines() == [
        "module imported",
        key.SENTRY_MISSING_DEPENDENCY_ERROR_STR,
    ]


def test_setup_error_removes_sensitive_exception_context(monkeypatch: pytest.MonkeyPatch) -> None:
    secret_dsn = "https://private-key@example.invalid/123"

    def fail_setup(*_args: object) -> None:
        raise RuntimeError(f"SDK rejected {secret_dsn}")

    monkeypatch.setattr(SentryProvider, "_create_client", fail_setup)
    with pytest.raises(ValueError) as caught:
        SentryProvider(secret_dsn)

    assert str(caught.value) == key.SENTRY_CONFIGURATION_ERROR_STR
    assert secret_dsn not in str(caught.value)
    assert "private-key" not in str(caught.value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    provider_frame = caught.value.__traceback__.tb_next
    assert provider_frame is not None
    assert provider_frame.tb_frame.f_locals["dsn"] == key.SENTRY_REDACTED_DSN_STR


def test_emit_preserves_structured_exception_metadata_and_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient()
    provider = _provider(monkeypatch, client)
    try:
        try:
            raise ValueError("low-level failure")
        except ValueError as cause:
            try:
                raise RuntimeError("payment failed") from cause
            except RuntimeError:
                record = logging.LogRecord(
                    "payment_gateway.api",
                    35,
                    "payment_gateway/api.py",
                    42,
                    "Failed payment for %s",
                    ("example-user",),
                    sys.exc_info(),
                    "charge",
                )
        record.stack_info = "Stack (most recent call last):\n  synthetic frame"
        record.__dict__["logger"] = "caller-controlled metadata"
        record.__dict__["requestId"] = "example-123"
        event = replace(
            make_event(record, package_name="Payment Gateway"),
            operation="charge_provider",
            elapsed_ns=1_250_000_000,
        )

        provider.emit(event)

        assert len(client.captured) == 1
        assert client.scopes == [None]
        payload = client.captured[0]
        assert payload["timestamp"] == event.timestamp
        assert payload["level"] == "warning"
        assert payload["logger"] == "payment_gateway.api"
        assert payload["message"] == "Failed payment for example-user"
        assert payload["extra"]["metadata"] == {
            "logger": "caller-controlled metadata",
            "requestId": "example-123",
        }
        assert payload["extra"]["stack_info"] == record.stack_info
        context = payload["contexts"]["n_log_forge"]
        assert context == {
            "level_number": 35,
            "level_name": "Level 35",
            "package": "Payment Gateway",
            "pathname": "payment_gateway/api.py",
            "lineno": 42,
            "function": "charge",
            "operation": "charge_provider",
            "elapsed_ns": 1_250_000_000,
        }
        exceptions = payload["exception"]["values"]
        assert [item["type"] for item in exceptions] == ["ValueError", "RuntimeError"]
        assert exceptions[-1]["value"] == "payment failed"
        assert exceptions[-1]["stacktrace"]["frames"]
    finally:
        provider.close(0)


@pytest.mark.parametrize(
    ("level", "expected"),
    [
        (1, "debug"),
        (19, "debug"),
        (20, "info"),
        (29, "info"),
        (30, "warning"),
        (39, "warning"),
        (40, "error"),
        (49, "error"),
        (50, "fatal"),
    ],
)
def test_custom_numeric_severity_mapping(level: int, expected: str) -> None:
    assert _sentry_level(level) == expected


def test_drop_accounting_flush_and_close_are_repeatable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(capture_result=None)
    provider = _provider(monkeypatch, client)
    provider.emit(_event())
    assert provider.dropped_events == 1
    assert provider.flush(0) is False
    assert provider.flush(0) is True

    transport = client.transport
    assert transport is not None
    pending_queue = transport._worker._queue
    pending_queue.put("pending envelope")
    assert provider.close(0) is False
    assert client.close_calls == []

    pending_queue.get_nowait()
    pending_queue.task_done()
    assert provider.close(0) is True
    assert client.close_calls == [0.0]
    assert provider.close(0) is True
    provider.emit(_event())
    assert len(client.captured) == 1


def test_drop_accounting_saturates_at_its_documented_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(capture_result=None)
    provider = _provider(monkeypatch, client)
    try:
        provider._dropped_events = key.SENTRY_DROP_COUNTER_MAX_INT
        provider.emit(_event())
        assert provider.dropped_events == key.SENTRY_DROP_COUNTER_MAX_INT
    finally:
        provider.close(0)


def test_real_sdk_configuration_and_host_client_are_isolated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentry_sdk = _require_sentry_sdk()
    transport_module = pytest.importorskip("sentry_sdk.transport")

    class HostTransport(transport_module.Transport):
        def capture_envelope(self, _envelope: object) -> None:
            raise AssertionError("host transport must not receive owned events")

    monkeypatch.setenv("SENTRY_DSN", "https://unrelated@example.invalid/9")
    monkeypatch.setenv("SENTRY_ENVIRONMENT", "unrelated-environment")
    monkeypatch.setenv("SENTRY_RELEASE", "unrelated-release")
    monkeypatch.setenv("SENTRY_DEBUG", "true")
    monkeypatch.setenv("SENTRY_KEEP_ALIVE", "true")
    monkeypatch.setenv("SENTRY_PRINT_ENVELOPES", "true")

    host = sentry_sdk.Client(
        dsn="https://host-key@example.invalid/1",
        transport=HostTransport,
        default_integrations=False,
    )
    scopes = (
        sentry_sdk.get_global_scope(),
        sentry_sdk.get_current_scope(),
        sentry_sdk.get_isolation_scope(),
    )
    previous_clients = tuple(scope.client for scope in scopes)
    scopes[0].set_client(host)
    before_owned = tuple(scope.client for scope in scopes)
    provider: SentryProvider | None = None
    try:
        dsn = "https://owned-key@example.invalid/prefix/2"
        provider = SentryProvider(dsn)
        assert tuple(scope.client for scope in scopes) == before_owned
        assert scopes[0].client is host
        assert provider._client is not host

        options = provider._client.options
        assert options["dsn"] == dsn
        assert options["environment"] == "production"
        assert options["release"] == ""
        assert options["server_name"] == ""
        assert options["dist"] == ""
        assert options["default_integrations"] is False
        assert options["auto_enabling_integrations"] is False
        assert options["auto_session_tracking"] is False
        assert options["enable_logs"] is False
        assert options["enable_metrics"] is False
        assert options["debug"] is False
        assert options["include_local_variables"] is False
        assert options["send_default_pii"] is False
        assert options["keep_alive"] is False
        assert options["transport_queue_size"] == key.SENTRY_QUEUE_CAPACITY_INT
        assert provider._client.integrations == {}
        assert isinstance(provider._client.transport, transport_module.HttpTransport)

        provider._client.transport.on_dropped_event("full_queue")
        assert provider.dropped_events == 1
        assert provider.flush(0) is False
        assert provider.flush(0) is True
        assert provider.close(0) is True
        assert host.is_active()
    finally:
        if provider is not None:
            provider.close(0)
        for scope, previous in zip(scopes, previous_clients, strict=True):
            scope.set_client(previous)
        host.close(timeout=0)


def test_partial_sdk_setup_failure_closes_created_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentry_sdk = _require_sentry_sdk()
    transport_module = pytest.importorskip("sentry_sdk.transport")
    created: list[Any] = []

    class PartialClient:
        def __init__(self, **options: object) -> None:
            self.options = dict(options)
            self.transport = None
            self.close_calls: list[float] = []
            created.append(self)

        def close(self, timeout: float) -> None:
            self.close_calls.append(timeout)

    class FailingTransport:
        def __init__(self, _options: object) -> None:
            raise RuntimeError("synthetic transport setup failure")

    monkeypatch.setattr(sentry_sdk, "Client", PartialClient)
    monkeypatch.setattr(transport_module, "HttpTransport", FailingTransport)

    with pytest.raises(ValueError) as caught:
        SentryProvider("https://private-key@example.invalid/123")
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None
    assert len(created) == 1
    assert created[0].close_calls == [key.SENTRY_ZERO_TIMEOUT_SECONDS_FLOAT]


def test_raw_example_is_safe_valid_and_matches_emit_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    input_fixture = json.loads((_RAW_EXAMPLE / "json" / "input.json").read_text())
    output_fixture = json.loads((_RAW_EXAMPLE / "json" / "output.json").read_text())
    request_text = (_RAW_EXAMPLE / "request.txt").read_text()
    provider_arguments = input_fixture["providerArguments"]
    event_data = input_fixture["event"]
    timestamp = datetime.fromisoformat(event_data["timestamp"].replace("Z", "+00:00"))
    event = Event(
        timestamp=timestamp,
        level=event_data["level"],
        level_name=event_data["levelName"],
        source=event_data["source"],
        package_name=event_data["packageName"],
        message=event_data["message"],
        metadata=MappingProxyType(event_data["metadata"]),
        pathname=event_data["pathname"],
        lineno=event_data["lineno"],
        function=event_data["function"],
        exception=event_data["exception"],
        exception_text=event_data["exceptionText"],
        stack_info=event_data["stackInfo"],
        operation=event_data["operation"],
        elapsed_ns=event_data["elapsedNs"],
        duration=event_data["duration"],
    )
    client = _FakeClient()
    monkeypatch.setattr(SentryProvider, "_create_client", lambda *_args: client)
    provider = SentryProvider(
        provider_arguments["dsn"],
        provider_arguments["environment"],
        provider_arguments["release"],
    )
    try:
        result = provider.emit(event)
    finally:
        provider.close(0)

    assert result is output_fixture is None
    assert client.captured[0]["message"] == event_data["message"]
    assert client.captured[0]["extra"]["metadata"] == event_data["metadata"]
    assert "example.invalid" in provider_arguments["dsn"]
    assert "illustrative" in request_text.lower()
    assert "no live request was made" in request_text.lower()


def test_missing_dependency_error_chain_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    real_import = builtins.__import__

    def blocked_import(name: str, *args: object, **kwargs: object) -> Any:
        if name == "sentry_sdk" or name.startswith("sentry_sdk."):
            raise ModuleNotFoundError("synthetic missing SDK")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)
    with pytest.raises(ImportError) as caught:
        SentryProvider("https://private-key@example.invalid/123")
    assert str(caught.value) == key.SENTRY_MISSING_DEPENDENCY_ERROR_STR
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None

"""Explicit, isolated Sentry events using the SDK's bounded HTTP transport.

No Sentry import takes place until a configured provider is constructed. Capture
uses the owned client directly with ``scope=None``: even global SDK processors
and the host's current/isolation scopes cannot enrich or discard these events.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, cast

from core.constant import sentry_constant as key
from core.helper.event import Event, thaw

if TYPE_CHECKING:
    from sentry_sdk import Client


def _sentry_level(level: int) -> str:
    """Map custom severities down to the nearest standard severity band."""
    if level >= logging.CRITICAL:
        return key.SENTRY_FATAL_LEVEL_STR
    if level >= logging.ERROR:
        return key.SENTRY_ERROR_LEVEL_STR
    if level >= logging.WARNING:
        return key.SENTRY_WARNING_LEVEL_STR
    if level >= logging.INFO:
        return key.SENTRY_INFO_LEVEL_STR
    return key.SENTRY_DEBUG_LEVEL_STR


def _payload(event: Event) -> dict[str, Any]:
    context: dict[str, Any] = {
        key.SENTRY_NUMERIC_LEVEL_KEY_STR: event.level,
        key.SENTRY_LEVEL_NAME_KEY_STR: event.level_name,
        key.SENTRY_PACKAGE_KEY_STR: event.package_name,
        key.SENTRY_PATHNAME_KEY_STR: event.pathname,
        key.SENTRY_LINENO_KEY_STR: event.lineno,
        key.SENTRY_FUNCTION_KEY_STR: event.function,
    }
    if event.operation is not None:
        context[key.SENTRY_OPERATION_KEY_STR] = event.operation
        context[key.SENTRY_ELAPSED_NS_KEY_STR] = event.elapsed_ns
    extra: dict[str, Any] = {key.SENTRY_METADATA_KEY_STR: thaw(event.metadata)}
    if event.stack_info is not None:
        extra[key.SENTRY_STACK_INFO_KEY_STR] = event.stack_info
    payload: dict[str, Any] = {
        key.SENTRY_TIMESTAMP_KEY_STR: event.timestamp,
        key.SENTRY_LEVEL_KEY_STR: _sentry_level(event.level),
        key.SENTRY_LOGGER_KEY_STR: event.source,
        key.SENTRY_MESSAGE_KEY_STR: event.message,
        key.SENTRY_EXTRA_KEY_STR: extra,
        key.SENTRY_CONTEXTS_KEY_STR: {key.SENTRY_RECORD_CONTEXT_KEY_STR: context},
    }
    if event.exception is not None:
        payload[key.SENTRY_EXCEPTION_KEY_STR] = thaw(event.exception)
    return payload


class SentryProvider:
    """A client and transport owned solely by this package.

    The SDK queue holds at most 100 waiting envelopes and drops the newest event
    when full. Drop accounting is a bounded integer, with no recursive logging.
    A flush reports new losses once; a later flush can succeed after recovery.
    """

    def __init__(
        self, dsn: str, environment: str | None = None, release: str | None = None
    ) -> None:
        self._counter_lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._dropped_events = 0
        self._reported_drops = 0
        self._closed = False
        try:
            self._client = self._create_client(dsn, environment, release)
        except ImportError:
            raise ImportError(key.SENTRY_MISSING_DEPENDENCY_ERROR_STR) from None
        except Exception:
            # SDK errors can include credentials; suppress their entire chain.
            raise ValueError(key.SENTRY_CONFIGURATION_ERROR_STR) from None

    def _create_client(self, dsn: str, environment: str | None, release: str | None) -> Client:
        from sentry_sdk import Client
        from sentry_sdk.transport import HttpTransport

        owner = self

        class CountedHttpTransport(HttpTransport):
            def on_dropped_event(self, _reason: str) -> None:
                owner._record_drop()

        # SENTRY_PRINT_ENVELOPES unconditionally wraps even explicit transports
        # in SDK 2.69.1. A transportless client followed by direct installation
        # avoids that path without mutating the environment or SDK globals.
        client = Client(
            dsn=key.SENTRY_DISABLED_DSN_STR,
            transport=None,
            environment=environment or key.SENTRY_FALLBACK_ENVIRONMENT_STR,
            # Prevent re-reading SENTRY_RELEASE or running Git on unrelated
            # reconfiguration: the runtime owns the environment snapshot.
            release=release or key.SENTRY_ABSENT_RELEASE_STR,
            server_name=key.SENTRY_DEFAULT_SERVER_NAME_STR,
            dist=key.SENTRY_DEFAULT_DIST_STR,
            default_integrations=False,
            auto_enabling_integrations=False,
            integrations=[],
            auto_session_tracking=False,
            enable_logs=False,
            enable_metrics=False,
            send_client_reports=False,
            enable_backpressure_handling=False,
            debug=False,
            include_local_variables=False,
            include_source_context=False,
            attach_stacktrace=False,
            send_default_pii=False,
            traces_sample_rate=None,
            traces_sampler=None,
            profiles_sample_rate=None,
            profiles_sampler=None,
            profile_session_sample_rate=0.0,
            propagate_traces=False,
            trace_propagation_targets=[],
            functions_to_trace=[],
            enable_db_query_source=False,
            enable_http_request_source=False,
            spotlight=False,
            keep_alive=False,
            transport_queue_size=key.SENTRY_QUEUE_CAPACITY_INT,
            sample_rate=key.SENTRY_ERROR_SAMPLE_RATE_FLOAT,
            shutdown_timeout=key.SENTRY_ZERO_TIMEOUT_SECONDS_FLOAT,
        )
        client.options[key.SENTRY_DSN_KEY_STR] = dsn
        client.transport = CountedHttpTransport(client.options)
        return client

    def _record_drop(self) -> None:
        with self._counter_lock:
            self._dropped_events += 1

    @property
    def dropped_events(self) -> int:
        """Count transport-reported failures/overflow and rejected captures."""
        with self._counter_lock:
            return self._dropped_events

    def emit(self, event: Event) -> None:
        if self._closed:
            return
        # No exception objects or hints reach the asynchronous transport. The
        # runtime isolates ordinary errors, including SDK serialization errors.
        if self._client.capture_event(_payload(event), scope=None) is None:
            self._record_drop()

    def _has_pending_work(self) -> bool:
        transport = self._client.transport
        if transport is None:
            return False
        # SDK flush returns None even on timeout. Inspect its actual queue under
        # the queue condition lock to report completion, including active sends.
        # This version-specific detail is isolated here and covered using the
        # real SDK; an unknown transport shape fails closed.
        worker = getattr(transport, "_worker", None)
        queue = getattr(worker, "_queue", None)
        if queue is None:
            return True
        with queue.all_tasks_done:
            return cast(bool, queue.unfinished_tasks != 0)

    def _flush(self, timeout: float) -> bool:
        if self._closed:
            return True
        self._client.flush(timeout=timeout)
        pending = self._has_pending_work()
        with self._counter_lock:
            new_losses = self._dropped_events != self._reported_drops
            self._reported_drops = self._dropped_events
        return not pending and not new_losses

    def flush(self, timeout: float) -> bool:
        """Report queue drain and new losses; runtime bounds blocking SDK work."""
        with self._lifecycle_lock:
            return self._flush(timeout)

    def close(self, timeout: float) -> bool:
        """Defer transport destruction while queued or active work remains."""
        with self._lifecycle_lock:
            if self._closed:
                return True
            drained = self._flush(timeout)
            if self._has_pending_work():
                return False
            self._client.close(timeout=key.SENTRY_ZERO_TIMEOUT_SECONDS_FLOAT)
            self._closed = True
            return drained

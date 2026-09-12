"""Private delivery contract, independent of any remote SDK."""

from __future__ import annotations

from typing import Protocol

from ..helper.event import Event


class Provider(Protocol):
    """Deliver immutable producer snapshots and manage owned resources.

    The runtime applies severity policy and isolates delivery failures. It invokes
    lifecycle methods outside its configuration lock, in bounded daemon tasks,
    and does not close a provider while an emitter still holds a reference.
    """

    def emit(self, event: Event) -> None:
        """Attempt delivery once without retaining application-owned objects."""
        ...

    def flush(self, timeout: float) -> bool:
        """Drain queued work within the supplied remaining budget."""
        ...

    def close(self, timeout: float) -> bool:
        """Drain and release owned resources; return false while still busy."""
        ...

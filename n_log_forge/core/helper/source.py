"""Private caller attribution and bounded display-name transformation."""

from __future__ import annotations

import io
import re
import sys
import traceback
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from types import FrameType

from ..constant.event_constant import (
    CORE_PACKAGE_MODULE_STR,
    DISPLAY_CACHE_SIZE_INT,
    MAIN_MODULE_STR,
    MODULE_FILE_KEY_STR,
    MODULE_NAME_KEY_STR,
    MODULE_SPEC_KEY_STR,
    PACKAGE_MODULE_STR,
    STANDARD_LOGGING_MODULE_STR,
)


@dataclass(frozen=True)
class Caller:
    source: str
    pathname: str
    lineno: int
    function: str
    stack_info: str | None = None


def _module_source(frame: FrameType) -> str:
    name = frame.f_globals.get(MODULE_NAME_KEY_STR, MAIN_MODULE_STR)
    if not isinstance(name, str) or not name:
        name = MAIN_MODULE_STR
    if name != MAIN_MODULE_STR:
        return name
    spec_name = getattr(frame.f_globals.get(MODULE_SPEC_KEY_STR), "name", None)
    if isinstance(spec_name, str) and spec_name and spec_name != MAIN_MODULE_STR:
        return spec_name
    filename = frame.f_globals.get(MODULE_FILE_KEY_STR)
    if isinstance(filename, str) and filename and not filename.startswith("<"):
        stem = Path(filename).stem
        if stem and stem != MAIN_MODULE_STR:
            return stem
    return MAIN_MODULE_STR


def resolve_caller(stacklevel: int = 1, stack_info: bool = False) -> Caller:
    """Resolve the user's selected frame, skipping library and logging internals."""
    if isinstance(stacklevel, bool) or not isinstance(stacklevel, int) or stacklevel < 1:
        raise ValueError("stacklevel must be a positive integer")
    frame: FrameType | None = sys._getframe(1)
    selected: FrameType | None = None
    try:
        while frame is not None:
            module = frame.f_globals.get(MODULE_NAME_KEY_STR, "")
            internal = isinstance(module, str) and (
                module == PACKAGE_MODULE_STR
                or module.startswith(PACKAGE_MODULE_STR + ".")
                or module == CORE_PACKAGE_MODULE_STR
                or module.startswith(CORE_PACKAGE_MODULE_STR + ".")
                or module == STANDARD_LOGGING_MODULE_STR
                or module.startswith(STANDARD_LOGGING_MODULE_STR + ".")
            )
            if not internal:
                selected = frame
                stacklevel -= 1
                if stacklevel <= 0:
                    break
            frame = frame.f_back
        if selected is None:
            return Caller(MAIN_MODULE_STR, "<unknown>", 0, "<unknown>")
        stack_text = None
        if stack_info:
            with io.StringIO() as stream:
                stream.write("Stack (most recent call last):\n")
                traceback.print_stack(selected, file=stream)
                stack_text = stream.getvalue().rstrip()
        return Caller(
            _module_source(selected),
            selected.f_code.co_filename,
            selected.f_lineno,
            selected.f_code.co_name,
            stack_text,
        )
    finally:
        del frame
        del selected


@lru_cache(maxsize=DISPLAY_CACHE_SIZE_INT)
def package_display_name(source: str) -> str:
    """Title-case words in the source's first path segment; never inspect packages."""
    segment = source.split(".", 1)[0]
    words = [word for word in re.split(r"[_-]+", segment) if word]
    return (" ".join(words) or segment).title()

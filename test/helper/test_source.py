import types

import pytest

from core.helper.source import package_display_name, resolve_caller


@pytest.mark.parametrize(
    ("source", "display"),
    [("my_package.api", "My Package"), ("payment-gateway.api", "Payment Gateway"),
     ("n_log_forge", "N Log Forge"), ("My__Package.api", "My Package")],
)
def test_package_display_name_heuristic(source, display):
    assert package_display_name(source) == display


def test_main_display_name_does_not_retain_empty_separator_words():
    assert package_display_name("__main__") == "Main"


def test_source_preserves_actual_caller_and_stacklevel():
    def wrapper():
        return resolve_caller(stacklevel=2, stack_info=True)

    caller = wrapper()
    assert caller.source == __name__
    assert caller.pathname == __file__
    assert caller.function == "test_source_preserves_actual_caller_and_stacklevel"
    assert caller.lineno > 0
    assert "Stack (most recent call last):" in caller.stack_info


@pytest.mark.parametrize(
    ("spec", "filename", "expected"),
    [(types.SimpleNamespace(name="my_package.runner"), "/app/start.py", "my_package.runner"),
     (None, "/app/my-script.py", "my-script"), (None, "<stdin>", "__main__"),
     (None, None, "__main__")],
)
def test_main_module_spec_script_and_interactive_fallback(spec, filename, expected):
    namespace = {"__name__": "__main__", "__spec__": spec, "resolve": resolve_caller}
    if filename is not None:
        namespace["__file__"] = filename
    exec("caller = resolve()", namespace)
    assert namespace["caller"].source == expected


def test_no_first_caller_cache_between_global_sources():
    for name in ("application.one", "different.two"):
        namespace = {"__name__": name, "resolve": resolve_caller}
        exec("caller = resolve()", namespace)
        assert namespace["caller"].source == name

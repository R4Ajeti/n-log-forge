"""Configuration candidates are pure, immutable, validated policy snapshots."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from core.service.configuration import (
    ConfigurationError,
    build_config,
    normalize_runtime,
    read_environment,
)


@pytest.mark.parametrize(
    ("environment", "expected"),
    [
        ({}, 20),
        ({"DEBUGGING": "true"}, 10),
        ({"DEBUGGING": "true", "LOGGER": "critical"}, 10),
        ({"DEBUGGING": "true", "LOGGER": "0"}, 10),
        ({"DEBUGGING": "false"}, 40),
        ({"DEBUGGING": "false", "LOGGER": "15"}, 15),
        ({"DEBUGGING": "false", "LOGGER": "0"}, 0),
        ({"LOGGER": "warning"}, 30),
        ({"LOGGER": "0"}, 0),
    ],
)
def test_complete_global_decision_table(environment: dict[str, str], expected: int) -> None:
    config = build_config(read_environment(environment), {}, {})
    assert config.global_level == expected
    assert config.threshold("unconfigured.logger") == expected


def test_all_default_fields() -> None:
    config = build_config({}, {}, {})
    assert config.level is None
    assert config.debugging is None
    assert config.console_enabled is True
    assert config.timestamp_format is None
    assert config.package_name is None
    assert config.duration_precision == 1
    assert config.sentry_data_source_name is None
    assert config.sentry_level == 40
    assert config.sentry_environment is None
    assert config.sentry_release is None
    assert config.manage_root_level is True
    assert config.root_handler_policy == "preserve"


def test_environment_empty_values_are_absent_and_unrecognized_settings_are_ignored() -> None:
    environment = read_environment(
        {
            "LOGGER": "",
            "DEBUGGING": "  ",
            "DURATION_PRECISION": "\t\n",
            "LOGGER_PACKAGES": " ",
            "SENTRY_DATA_SOURCE_NAME": " ",
            "SENTRY_ENABLED": "true",
            "SENTRY_DSN": "https://key@example.invalid/1",
            "UNRELATED": "banana",
        }
    )
    assert not environment
    assert build_config(environment, {}, {}).sentry_data_source_name is None


def test_every_supported_environment_setting_is_normalized() -> None:
    config = build_config(
        read_environment(
            {
                "LOGGER": " info ",
                "DEBUGGING": " false ",
                "CONSOLE_ENABLED": " no ",
                "TIMESTAMP_FORMAT": " %H:%M:%S ",
                "PACKAGE_NAME": " My Service ",
                "DURATION_PRECISION": " 6 ",
                "SENTRY_DATA_SOURCE_NAME": " https://key@example.invalid/1 ",
                "SENTRY_LEVEL": " 0 ",
                "SENTRY_ENVIRONMENT": " staging ",
                "SENTRY_RELEASE": " 1.2.3 ",
                "LOGGER_PACKAGES": " pkg = 15 ",
            }
        ),
        {},
        {},
    )
    assert config.global_level == 20
    assert config.console_enabled is False
    assert config.timestamp_format == "%H:%M:%S"
    assert config.package_name == "My Service"
    assert config.duration_precision == 6
    assert config.sentry_data_source_name == "https://key@example.invalid/1"
    assert config.sentry_level == 0
    assert config.sentry_environment == "staging"
    assert config.sentry_release == "1.2.3"
    assert config.threshold("pkg.child") == 15


def test_runtime_precedence_is_per_key_and_debugging_remains_independent() -> None:
    environment = read_environment({"DEBUGGING": "true", "LOGGER": "warning"})
    assert build_config(environment, {"level": "info"}, {}).global_level == 10
    assert build_config(environment, {"debugging": False, "level": "info"}, {}).global_level == 20
    assert build_config(environment, {"debugging": False}, {}).global_level == 30


def test_environment_snapshot_does_not_follow_later_mutation() -> None:
    source = {"LOGGER": "warning", "LOGGER_PACKAGES": "pkg=error"}
    snapshot = read_environment(source)
    source.clear()
    assert build_config(snapshot, {}, {}).threshold("pkg") == 40
    assert build_config(snapshot, {}, {}).global_level == 30
    assert build_config(read_environment(source), {}, {}).global_level == 20


@pytest.mark.parametrize(
    ("environment", "runtime", "key"),
    [
        ({"LOGGER": "banana", "DEBUGGING": "true"}, {"level": "info"}, "level"),
        ({"SENTRY_LEVEL": "banana"}, {"sentryLevel": 40}, "sentryLevel"),
        ({"SENTRY_DATA_SOURCE_NAME": "not-a-dsn"}, {"sentryDataSourceName": ""}, "sentryDataSourceName"),
        ({"DURATION_PRECISION": "7"}, {"durationPrecision": 1}, "durationPrecision"),
        ({"DEBUGGING": "maybe"}, {"debugging": True}, "debugging"),
    ],
)
def test_shadowed_environment_values_still_fail(
    environment: dict[str, str], runtime: dict[str, object], key: str
) -> None:
    with pytest.raises(ConfigurationError) as caught:
        build_config(read_environment(environment), runtime, {})
    assert caught.value.key == key
    assert "environment" in caught.value.source


def test_candidate_builder_revalidates_all_sources() -> None:
    with pytest.raises(ConfigurationError, match="environment.*level"):
        build_config({"level": "banana"}, {"level": 20}, {})
    with pytest.raises(ConfigurationError, match="runtime.*sentryLevel"):
        build_config({}, {"sentryLevel": "banana", "sentryDataSourceName": ""}, {})
    with pytest.raises(ConfigurationError, match="environment.*LOGGER_PACKAGES"):
        build_config({"LOGGER_PACKAGES": {"pkg": "banana"}}, {}, {"pkg": 10})


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("unknown", True),
        ("sentryEnabled", True),
        ("level", None),
        ("consoleEnabled", None),
        ("packageName", " "),
        ("timestampFormat", ""),
        ("sentryEnvironment", ""),
        ("sentryRelease", "\t"),
        ("rootHandlerPolicy", "discard"),
        ("rootHandlerPolicy", "PRESERVE"),
        ("reloadEnvironment", None),
        ("manageRootLevel", 2),
    ],
)
def test_invalid_runtime_values_identify_the_key_and_source(key: str, value: object) -> None:
    with pytest.raises(ConfigurationError) as caught:
        normalize_runtime(key, value)
    assert caught.value.key == key
    assert caught.value.source == "runtime"


@pytest.mark.parametrize("value", [True, "yes", 1, " On "])
def test_reload_environment_uses_the_shared_boolean_parser(value: object) -> None:
    assert normalize_runtime("reloadEnvironment", value) is True


def test_dsn_disable_and_reset_reveal_environment() -> None:
    environment = read_environment({"SENTRY_DATA_SOURCE_NAME": "https://private@example.invalid/1"})
    assert build_config(environment, {}, {}).sentry_data_source_name
    assert build_config(environment, {"sentryDataSourceName": " \t"}, {}).sentry_data_source_name == ""
    assert build_config(environment, {}, {}).sentry_data_source_name


def test_sensitive_configuration_representations_are_redacted() -> None:
    dsn = "https://secret-public:secret-private@example.invalid/prefix/1"
    environment = read_environment({"SENTRY_DATA_SOURCE_NAME": dsn})
    runtime = {"sentryDataSourceName": normalize_runtime("sentryDataSourceName", dsn)}
    config = build_config(environment, runtime, {})
    for representation in (repr(environment), repr(runtime), repr(config)):
        assert dsn not in representation
        assert "secret-public" not in representation
        assert "secret-private" not in representation


def test_dsn_error_chain_does_not_retain_url_parser_secrets() -> None:
    dsn = "https://private@[secret-invalid-host/123"
    with pytest.raises(ConfigurationError) as caught:
        read_environment({"SENTRY_DATA_SOURCE_NAME": dsn})
    assert "private" not in str(caught.value)
    assert "secret-invalid-host" not in str(caught.value)
    assert caught.value.__context__ is None
    assert caught.value.__cause__ is None


def test_hierarchy_specificity_segment_matching_and_case_sensitivity() -> None:
    config = build_config(
        read_environment(
            {
                "LOGGER": "critical",
                "LOGGER_PACKAGES": "pkg=info,pkg.database=warning,pkg.database.query=debug,Foo=35",
            }
        ),
        {},
        {},
    )
    assert config.threshold("pkg.api") == 20
    assert config.threshold("pkg.database.connection") == 30
    assert config.threshold("pkg.database.query.builder") == 10
    assert config.threshold("pkg-other") == 50
    assert config.threshold("Foo.child") == 35
    assert config.threshold("foo.child") == 50


def test_source_merging_precedes_specificity_and_zero_rules_mask_then_inherit() -> None:
    environment = read_environment({"LOGGER": "info", "LOGGER_PACKAGES": "pkg=warning,pkg.api=error"})
    assert build_config(environment, {}, {"pkg": 10}).threshold("pkg.api") == 40
    assert build_config(environment, {}, {"pkg": 10, "pkg.api": 0}).threshold("pkg.api") == 10
    assert build_config(environment, {}, {"pkg": 0, "pkg.api": 0}).threshold("pkg.api") == 20
    assert build_config(environment, {}, {"pkg": 0}).threshold("pkg.worker") == 20
    assert build_config(environment, {}, {}).threshold("pkg.worker") == 30


def test_zero_ancestors_continue_until_first_nonzero_rule() -> None:
    config = build_config({}, {}, {"pkg": 35, "pkg.a": 0, "pkg.a.b": 0})
    assert config.threshold("pkg.a.b.c") == 35


def test_build_does_not_mutate_inputs_and_snapshots_are_deeply_immutable() -> None:
    environment = {"level": 20, "LOGGER_PACKAGES": {"pkg": 30}}
    runtime = {"packageName": "service"}
    runtime_packages = {"pkg.child": 10}
    config = build_config(environment, runtime, runtime_packages)
    runtime_packages["pkg.child"] = 40
    assert config.threshold("pkg.child") == 10
    with pytest.raises(FrozenInstanceError):
        config.global_level = 40  # type: ignore[misc]
    with pytest.raises(TypeError):
        config.package_rules["pkg"] = 50  # type: ignore[index]
    assert environment == {"level": 20, "LOGGER_PACKAGES": {"pkg": 30}}
    assert runtime == {"packageName": "service"}


def test_resolution_cache_cannot_reuse_an_obsolete_threshold() -> None:
    old_config = build_config({}, {}, {"pkg": 10})
    new_config = build_config({}, {}, {"pkg": 30})
    changed_global = build_config({}, {"level": 35}, {})
    for _ in range(10):
        assert old_config.threshold("pkg.api") == 10
        assert new_config.threshold("pkg.api") == 30
        assert changed_global.threshold("pkg.api") == 35


def test_failed_candidate_does_not_change_the_previous_snapshot() -> None:
    previous = build_config(read_environment({"LOGGER": "warning"}), {"packageName": "old"}, {})
    with pytest.raises(ConfigurationError):
        build_config(read_environment({"LOGGER": "info"}), {"durationPrecision": 7}, {})
    assert previous.global_level == 30
    assert previous.package_name == "old"

"""Inert Sentry event contract and transport limits."""

SENTRY_QUEUE_CAPACITY_INT = 100
SENTRY_FALLBACK_ENVIRONMENT_STR = "production"
SENTRY_DISABLED_DSN_STR = ""
SENTRY_DEFAULT_SERVER_NAME_STR = ""
SENTRY_DEFAULT_DIST_STR = ""
SENTRY_ABSENT_RELEASE_STR = ""
SENTRY_ZERO_TIMEOUT_SECONDS_FLOAT = 0.0
SENTRY_ERROR_SAMPLE_RATE_FLOAT = 1.0

SENTRY_DSN_KEY_STR = "dsn"
SENTRY_TIMESTAMP_KEY_STR = "timestamp"
SENTRY_LEVEL_KEY_STR = "level"
SENTRY_LOGGER_KEY_STR = "logger"
SENTRY_MESSAGE_KEY_STR = "message"
SENTRY_EXTRA_KEY_STR = "extra"
SENTRY_METADATA_KEY_STR = "metadata"
SENTRY_CONTEXTS_KEY_STR = "contexts"
SENTRY_RECORD_CONTEXT_KEY_STR = "n_log_forge"
SENTRY_EXCEPTION_KEY_STR = "exception"
SENTRY_STACK_INFO_KEY_STR = "stack_info"
SENTRY_NUMERIC_LEVEL_KEY_STR = "level_number"
SENTRY_LEVEL_NAME_KEY_STR = "level_name"
SENTRY_PACKAGE_KEY_STR = "package"
SENTRY_PATHNAME_KEY_STR = "pathname"
SENTRY_LINENO_KEY_STR = "lineno"
SENTRY_FUNCTION_KEY_STR = "function"
SENTRY_OPERATION_KEY_STR = "operation"
SENTRY_ELAPSED_NS_KEY_STR = "elapsed_ns"

SENTRY_FATAL_LEVEL_STR = "fatal"
SENTRY_ERROR_LEVEL_STR = "error"
SENTRY_WARNING_LEVEL_STR = "warning"
SENTRY_INFO_LEVEL_STR = "info"
SENTRY_DEBUG_LEVEL_STR = "debug"

SENTRY_MISSING_DEPENDENCY_ERROR_STR = (
    'Sentry requires the optional SDK; install it with pip install "n-log-forge[sentry]"'
)
SENTRY_CONFIGURATION_ERROR_STR = (
    "Unable to initialize sentryDataSourceName from effective configuration "
    "(DSN redacted); verify the optional SDK installation and Sentry settings"
)

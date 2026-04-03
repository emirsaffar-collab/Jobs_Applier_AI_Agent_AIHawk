"""
Custom exceptions for the AIHawk Job Application Bot.
Provides a structured exception hierarchy for clear error categorisation
and consistent error handling across the application.
"""


class AIHawkError(Exception):
    """Base exception for all AIHawk application errors."""

    def __init__(self, message: str, details: str = ""):
        super().__init__(message)
        self.message = message
        self.details = details

    def __str__(self) -> str:
        if self.details:
            return f"{self.message}: {self.details}"
        return self.message


# ---------------------------------------------------------------------------
# Configuration errors
# ---------------------------------------------------------------------------

class ConfigurationError(AIHawkError):
    """Raised when application configuration is invalid or missing."""
    pass


class MissingConfigKeyError(ConfigurationError):
    """Raised when a required configuration key is absent."""

    def __init__(self, key: str, config_path: str = ""):
        details = f"in {config_path}" if config_path else ""
        super().__init__(f"Missing required configuration key '{key}'", details)
        self.key = key
        self.config_path = config_path


class InvalidConfigValueError(ConfigurationError):
    """Raised when a configuration value fails validation."""

    def __init__(self, key: str, value, expected: str, config_path: str = ""):
        details = f"in {config_path}" if config_path else ""
        super().__init__(
            f"Invalid value '{value}' for key '{key}' (expected {expected})",
            details,
        )
        self.key = key
        self.value = value
        self.expected = expected


# ---------------------------------------------------------------------------
# File / storage errors
# ---------------------------------------------------------------------------

class FileOperationError(AIHawkError):
    """Raised when a file system operation fails."""
    pass


class MissingFileError(FileOperationError):
    """Raised when a required file cannot be found."""

    def __init__(self, path: str):
        super().__init__(f"Required file not found: {path}")
        self.path = path


class FileWriteError(FileOperationError):
    """Raised when writing to a file fails."""

    def __init__(self, path: str, reason: str = ""):
        super().__init__(f"Failed to write file: {path}", reason)
        self.path = path


# ---------------------------------------------------------------------------
# Database errors
# ---------------------------------------------------------------------------

class DatabaseError(AIHawkError):
    """Raised when a database operation fails."""
    pass


class RecordNotFoundError(DatabaseError):
    """Raised when an expected database record does not exist."""

    def __init__(self, model: str, identifier):
        super().__init__(f"{model} with identifier '{identifier}' not found")
        self.model = model
        self.identifier = identifier


# ---------------------------------------------------------------------------
# Document generation errors
# ---------------------------------------------------------------------------

class DocumentGenerationError(AIHawkError):
    """Raised when resume or cover-letter generation fails."""
    pass


class StyleNotFoundError(DocumentGenerationError):
    """Raised when the requested document style cannot be located."""

    def __init__(self, style_name: str):
        super().__init__(f"Document style '{style_name}' not found")
        self.style_name = style_name


class PDFConversionError(DocumentGenerationError):
    """Raised when HTML-to-PDF conversion fails."""

    def __init__(self, reason: str = ""):
        super().__init__("PDF conversion failed", reason)


# ---------------------------------------------------------------------------
# LLM / API errors
# ---------------------------------------------------------------------------

class LLMError(AIHawkError):
    """Raised when an LLM API call fails."""
    pass


class LLMAPIKeyError(LLMError):
    """Raised when the LLM API key is missing or invalid."""

    def __init__(self):
        super().__init__("LLM API key is missing or invalid")


class LLMRateLimitError(LLMError):
    """Raised when the LLM API rate limit is exceeded."""

    def __init__(self, retry_after: int = 0):
        details = f"retry after {retry_after}s" if retry_after else ""
        super().__init__("LLM API rate limit exceeded", details)
        self.retry_after = retry_after


class LLMResponseError(LLMError):
    """Raised when the LLM returns an unexpected or unparseable response."""

    def __init__(self, reason: str = ""):
        super().__init__("Unexpected LLM response", reason)


# ---------------------------------------------------------------------------
# Task / async errors
# ---------------------------------------------------------------------------

class TaskError(AIHawkError):
    """Raised when a background task encounters an error."""
    pass


class TaskNotFoundError(TaskError):
    """Raised when a task ID cannot be resolved."""

    def __init__(self, task_id: str):
        super().__init__(f"Task '{task_id}' not found")
        self.task_id = task_id


class TaskAlreadyRunningError(TaskError):
    """Raised when attempting to start a task that is already in progress."""

    def __init__(self, task_id: str):
        super().__init__(f"Task '{task_id}' is already running")
        self.task_id = task_id


# ---------------------------------------------------------------------------
# Browser / Selenium errors
# ---------------------------------------------------------------------------

class BrowserError(AIHawkError):
    """Raised when the Selenium browser cannot be initialised or used."""
    pass


class BrowserInitError(BrowserError):
    """Raised when the Chrome browser fails to start."""

    def __init__(self, reason: str = ""):
        super().__init__("Failed to initialise Chrome browser", reason)


# ---------------------------------------------------------------------------
# Web / HTTP errors
# ---------------------------------------------------------------------------

class WebError(AIHawkError):
    """Raised for HTTP / web-layer errors."""
    pass


class AuthenticationError(WebError):
    """Raised when a request is not authenticated."""

    def __init__(self):
        super().__init__("Authentication required")


class AuthorizationError(WebError):
    """Raised when a request lacks the required permissions."""

    def __init__(self):
        super().__init__("Insufficient permissions")

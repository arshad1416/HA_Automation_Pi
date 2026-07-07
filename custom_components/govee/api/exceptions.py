"""API layer exceptions.

Lightweight exceptions without Home Assistant dependencies.
The coordinator layer wraps these in translatable HA exceptions.
"""

from __future__ import annotations


class GoveeApiError(Exception):
    """Base exception for Govee API errors."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class GoveeAuthError(GoveeApiError):
    """Authentication failed - invalid API key or credentials."""

    def __init__(
        self, message: str = "Invalid API key", code: int | None = None
    ) -> None:
        super().__init__(message, code=code if code is not None else 401)


class GoveeRateLimitError(GoveeApiError):
    """Rate limit exceeded - too many requests."""

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message, code=429)
        self.retry_after = retry_after


class GoveeLoginRejectedError(GoveeApiError):
    """Login request rejected by Govee API with a non-standard status code.

    Distinct from GoveeAuthError (bad credentials) and connection errors.
    Typically indicates a deprecated endpoint or unsupported request format.
    """

    def __init__(self, message: str = "Login rejected by Govee API") -> None:
        super().__init__(message)


class Govee2FARequiredError(GoveeApiError):
    """Govee requires a 2FA verification code to complete login.

    Raised when the login endpoint returns JSON status 454 and no
    verification code was provided. The caller should request a code
    via the verification endpoint and retry login with the code.
    """

    def __init__(self, message: str = "Verification code required") -> None:
        super().__init__(message, code=454)


class Govee2FACodeInvalidError(GoveeApiError):
    """The provided 2FA verification code was invalid or expired.

    Raised when the login endpoint returns JSON status 454 after a
    verification code was provided, indicating the code is wrong or expired.
    """

    def __init__(self, message: str = "Invalid or expired verification code") -> None:
        super().__init__(message, code=454)


class GoveeConnectionError(GoveeApiError):
    """Network or connection error."""

    def __init__(self, message: str = "Failed to connect to Govee API") -> None:
        super().__init__(message)


class GoveeDeviceNotFoundError(GoveeApiError):
    """Device not found (expected for group devices)."""

    def __init__(self, message: str = "Device not found") -> None:
        super().__init__(message, code=400)

"""API layer for Govee integration.

Contains REST client, MQTT client, and authentication.
"""

from .auth import GoveeAuthClient, GoveeIotCredentials, validate_govee_credentials
from .client import GoveeApiClient
from .exceptions import (
    Govee2FACodeInvalidError,
    Govee2FARequiredError,
    GoveeApiError,
    GoveeAuthError,
    GoveeConnectionError,
    GoveeDeviceNotFoundError,
    GoveeLoginRejectedError,
    GoveeRateLimitError,
)
from .mqtt import GoveeAwsIotClient

__all__ = [
    # Client
    "GoveeApiClient",
    # Auth
    "GoveeAuthClient",
    "GoveeIotCredentials",
    "validate_govee_credentials",
    # MQTT
    "GoveeAwsIotClient",
    # Exceptions
    "Govee2FACodeInvalidError",
    "Govee2FARequiredError",
    "GoveeApiError",
    "GoveeAuthError",
    "GoveeConnectionError",
    "GoveeDeviceNotFoundError",
    "GoveeLoginRejectedError",
    "GoveeRateLimitError",
]

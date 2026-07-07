"""Protocol interfaces for Govee integration.

Defines contracts between layers following Hexagonal/Clean Architecture.
"""

from .api import IApiClient, IAuthProvider
from .state import IStateProvider

__all__ = [
    "IApiClient",
    "IAuthProvider",
    "IStateProvider",
]

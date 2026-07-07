"""Scene cache manager for Govee integration.

Manages scene and DIY scene caches with TTL, extracted from the coordinator
to reduce its responsibility surface.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from .api.client import GoveeApiClient
from .api.exceptions import GoveeApiError
from .models.device import GoveeDevice

_LOGGER = logging.getLogger(__name__)

# Scene cache time-to-live (24 hours)
SCENE_CACHE_TTL = 86400


class SceneCacheManager:
    """Manages scene and DIY scene caches with TTL.

    Provides lazy-loading scene data from the Govee API with a 24-hour
    cache to avoid rate limit pressure. Concurrent requests for the same
    device are deduplicated so only one API call is made. Stale entries
    for removed devices are cleaned up when requested.
    """

    def __init__(
        self, api_client: GoveeApiClient, cache_ttl: int = SCENE_CACHE_TTL
    ) -> None:
        """Initialize the scene cache manager.

        Args:
            api_client: Govee REST API client.
            cache_ttl: Cache time-to-live in seconds (default 24 hours).
        """
        self._api_client = api_client
        self._cache_ttl = cache_ttl

        # Scene cache {device_id: (timestamp, [scenes])}
        self._scene_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

        # DIY scene cache {device_id: (timestamp, [scenes])}
        self._diy_scene_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

        # In-flight request deduplication
        self._scene_inflight: dict[str, asyncio.Task[list[dict[str, Any]]]] = {}
        self._diy_scene_inflight: dict[str, asyncio.Task[list[dict[str, Any]]]] = {}

    @property
    def scene_cache_count(self) -> int:
        """Return number of devices with cached scenes."""
        return len(self._scene_cache)

    @property
    def diy_scene_cache_count(self) -> int:
        """Return number of devices with cached DIY scenes."""
        return len(self._diy_scene_cache)

    def cleanup_stale(self, active_device_ids: set[str]) -> None:
        """Remove cache entries for devices no longer discovered.

        Args:
            active_device_ids: Set of currently active device IDs.
        """
        stale_ids = set(self._scene_cache) - active_device_ids
        stale_ids |= set(self._diy_scene_cache) - active_device_ids
        for stale_id in stale_ids:
            self._scene_cache.pop(stale_id, None)
            self._diy_scene_cache.pop(stale_id, None)
        if stale_ids:
            _LOGGER.debug("Cleaned scene cache for %d removed devices", len(stale_ids))

    async def async_get_scenes(
        self,
        device_id: str,
        device: GoveeDevice | None,
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Get available scenes for a device.

        Concurrent requests for the same device are deduplicated so only
        one API call is made; additional callers share the result.

        Args:
            device_id: Device identifier.
            device: Device instance (needed for sku on cache miss).
            refresh: Force refresh from API.

        Returns:
            List of scene definitions.
        """
        if not refresh and device_id in self._scene_cache:
            cached_ts, cached_scenes = self._scene_cache[device_id]
            cache_age = time.monotonic() - cached_ts
            if cache_age < self._cache_ttl:
                _LOGGER.debug(
                    "Returning %d cached scenes for %s (age: %ds)",
                    len(cached_scenes),
                    device_id,
                    int(cache_age),
                )
                return cached_scenes
            _LOGGER.debug(
                "Scene cache expired for %s (age: %ds), refreshing",
                device_id,
                int(cache_age),
            )

        if not device:
            _LOGGER.warning("Device %s not found for scene fetch", device_id)
            return []

        # Deduplicate concurrent requests for the same device
        if device_id in self._scene_inflight:
            _LOGGER.debug("Joining in-flight scene request for %s", device.name)
            return await self._scene_inflight[device_id]

        task = asyncio.ensure_future(self._fetch_and_cache_scenes(device_id, device))
        self._scene_inflight[device_id] = task
        try:
            return await task
        finally:
            self._scene_inflight.pop(device_id, None)

    async def _fetch_and_cache_scenes(
        self, device_id: str, device: GoveeDevice
    ) -> list[dict[str, Any]]:
        """Fetch scenes from API and update cache.

        Args:
            device_id: Device identifier.
            device: Device instance.

        Returns:
            List of scene definitions.
        """
        _LOGGER.debug(
            "Fetching scenes from API for %s (sku=%s)",
            device.name,
            device.sku,
        )

        try:
            scenes = await self._api_client.get_dynamic_scenes(device_id, device.sku)
            self._scene_cache[device_id] = (time.monotonic(), scenes)
            _LOGGER.info(
                "Fetched and cached %d scenes for %s",
                len(scenes),
                device.name,
            )
            return scenes
        except GoveeApiError as err:
            _LOGGER.error(
                "API error fetching scenes for %s: %s",
                device.name,
                err,
            )
            # Return cached scenes if available, otherwise empty list
            cached_entry = self._scene_cache.get(device_id)
            cached = cached_entry[1] if cached_entry else []
            _LOGGER.debug("Returning %d cached scenes after error", len(cached))
            return cached

    async def async_get_diy_scenes(
        self,
        device_id: str,
        device: GoveeDevice | None,
        refresh: bool = False,
    ) -> list[dict[str, Any]]:
        """Get available DIY scenes for a device.

        Concurrent requests for the same device are deduplicated so only
        one API call is made; additional callers share the result.

        Args:
            device_id: Device identifier.
            device: Device instance (needed for sku on cache miss).
            refresh: Force refresh from API.

        Returns:
            List of DIY scene definitions.
        """
        if not refresh and device_id in self._diy_scene_cache:
            cached_ts, cached_scenes = self._diy_scene_cache[device_id]
            cache_age = time.monotonic() - cached_ts
            if cache_age < self._cache_ttl:
                _LOGGER.debug(
                    "Returning %d cached DIY scenes for %s (age: %ds)",
                    len(cached_scenes),
                    device_id,
                    int(cache_age),
                )
                return cached_scenes
            _LOGGER.debug(
                "DIY scene cache expired for %s (age: %ds), refreshing",
                device_id,
                int(cache_age),
            )

        if not device:
            _LOGGER.warning("Device %s not found for DIY scene fetch", device_id)
            return []

        # Deduplicate concurrent requests for the same device
        if device_id in self._diy_scene_inflight:
            _LOGGER.debug("Joining in-flight DIY scene request for %s", device.name)
            return await self._diy_scene_inflight[device_id]

        task = asyncio.ensure_future(
            self._fetch_and_cache_diy_scenes(device_id, device)
        )
        self._diy_scene_inflight[device_id] = task
        try:
            return await task
        finally:
            self._diy_scene_inflight.pop(device_id, None)

    async def _fetch_and_cache_diy_scenes(
        self, device_id: str, device: GoveeDevice
    ) -> list[dict[str, Any]]:
        """Fetch DIY scenes from API and update cache.

        Args:
            device_id: Device identifier.
            device: Device instance.

        Returns:
            List of DIY scene definitions.
        """
        _LOGGER.debug(
            "Fetching DIY scenes from API for %s (sku=%s)",
            device.name,
            device.sku,
        )

        try:
            scenes = await self._api_client.get_diy_scenes(device_id, device.sku)
            self._diy_scene_cache[device_id] = (time.monotonic(), scenes)
            _LOGGER.info(
                "Fetched and cached %d DIY scenes for %s",
                len(scenes),
                device.name,
            )
            return scenes
        except GoveeApiError as err:
            _LOGGER.error(
                "API error fetching DIY scenes for %s: %s",
                device.name,
                err,
            )
            # Return cached scenes if available, otherwise empty list
            cached_entry = self._diy_scene_cache.get(device_id)
            cached = cached_entry[1] if cached_entry else []
            _LOGGER.debug("Returning %d cached DIY scenes after error", len(cached))
            return cached

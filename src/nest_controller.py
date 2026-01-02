"""Nest thermostat control via Google Smart Device Management API."""

import logging
from dataclasses import dataclass
from typing import List, Optional

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from .auth import TokenManager

logger = logging.getLogger(__name__)

# SDM API base URL
SDM_API_BASE = "https://smartdevicemanagement.googleapis.com/v1"


@dataclass
class Thermostat:
    """Represents a Nest thermostat device."""

    device_id: str
    name: str
    display_name: str
    current_mode: str
    ambient_temperature_celsius: Optional[float] = None
    humidity_percent: Optional[float] = None


class NestController:
    """Controls Nest thermostats via the SDM API."""

    def __init__(self, project_id: str, token_manager: TokenManager):
        self.project_id = project_id
        self.token_manager = token_manager
        self._devices_cache: Optional[List[Thermostat]] = None

    def _get_headers(self) -> dict:
        """Get headers for API requests."""
        headers = self.token_manager.get_auth_header()
        headers["Content-Type"] = "application/json"
        return headers

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    async def list_devices(self, force_refresh: bool = False) -> List[Thermostat]:
        """List all Nest thermostat devices.

        Args:
            force_refresh: If True, bypass cache and fetch fresh data.

        Returns:
            List of Thermostat objects.
        """
        if self._devices_cache and not force_refresh:
            return self._devices_cache

        url = f"{SDM_API_BASE}/enterprises/{self.project_id}/devices"
        logger.info(f"Fetching devices from: {url}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url, headers=self._get_headers())
            response.raise_for_status()
            data = response.json()

        thermostats = []
        devices = data.get("devices", [])
        logger.info(f"Found {len(devices)} devices")

        for device in devices:
            device_id = device.get("name", "").split("/")[-1]
            traits = device.get("traits", {})

            # Check if it's a thermostat
            if "sdm.devices.traits.ThermostatMode" not in traits:
                logger.debug(f"Skipping non-thermostat device: {device_id}")
                continue

            # Extract device info
            info_trait = traits.get("sdm.devices.traits.Info", {})
            mode_trait = traits.get("sdm.devices.traits.ThermostatMode", {})
            temp_trait = traits.get("sdm.devices.traits.Temperature", {})
            humidity_trait = traits.get("sdm.devices.traits.Humidity", {})

            thermostat = Thermostat(
                device_id=device_id,
                name=device.get("name", ""),
                display_name=info_trait.get("customName", "Unknown"),
                current_mode=mode_trait.get("mode", "UNKNOWN"),
                ambient_temperature_celsius=temp_trait.get("ambientTemperatureCelsius"),
                humidity_percent=humidity_trait.get("ambientHumidityPercent"),
            )
            thermostats.append(thermostat)
            logger.info(
                f"Found thermostat: {thermostat.display_name} "
                f"(ID: {thermostat.device_id}, Mode: {thermostat.current_mode})"
            )

        self._devices_cache = thermostats
        return thermostats

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError)),
    )
    async def set_thermostat_mode(self, device_id: str, mode: str) -> bool:
        """Set thermostat mode (HEAT, COOL, HEATCOOL, OFF).

        Args:
            device_id: The thermostat device ID.
            mode: The mode to set (HEAT, COOL, HEATCOOL, OFF).

        Returns:
            True if successful, False otherwise.
        """
        url = f"{SDM_API_BASE}/enterprises/{self.project_id}/devices/{device_id}:executeCommand"

        payload = {
            "command": "sdm.devices.commands.ThermostatMode.SetMode",
            "params": {"mode": mode},
        }

        logger.info(f"Setting thermostat {device_id} to mode: {mode}")

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url, headers=self._get_headers(), json=payload
            )

            if response.status_code == 200:
                logger.info(f"Successfully set thermostat {device_id} to {mode}")
                return True
            else:
                logger.error(
                    f"Failed to set thermostat mode: {response.status_code} - {response.text}"
                )
                response.raise_for_status()
                return False

    async def turn_off_thermostat(self, device_id: str) -> bool:
        """Turn off a thermostat.

        Args:
            device_id: The thermostat device ID.

        Returns:
            True if successful, False otherwise.
        """
        return await self.set_thermostat_mode(device_id, "OFF")

    async def turn_off_thermostats(self, device_ids: List[str]) -> dict:
        """Turn off multiple thermostats.

        Args:
            device_ids: List of device IDs to turn off.

        Returns:
            Dictionary mapping device_id to success status.
        """
        results = {}

        for device_id in device_ids:
            try:
                success = await self.turn_off_thermostat(device_id)
                results[device_id] = success
            except Exception as e:
                logger.error(f"Failed to turn off thermostat {device_id}: {e}")
                results[device_id] = False

        return results

    async def get_thermostat_status(self, device_id: str) -> Optional[Thermostat]:
        """Get current status of a specific thermostat.

        Args:
            device_id: The thermostat device ID.

        Returns:
            Thermostat object or None if not found.
        """
        devices = await self.list_devices(force_refresh=True)
        for device in devices:
            if device.device_id == device_id:
                return device
        return None

    async def discover_and_log_devices(self) -> List[Thermostat]:
        """Discover all thermostats and log their IDs for configuration.

        This is useful for initial setup to find device IDs.

        Returns:
            List of discovered thermostats.
        """
        logger.info("=" * 60)
        logger.info("THERMOSTAT DISCOVERY")
        logger.info("=" * 60)

        try:
            devices = await self.list_devices(force_refresh=True)

            if not devices:
                logger.warning("No thermostats found. Check your Device Access configuration.")
            else:
                logger.info(f"Found {len(devices)} thermostat(s):")
                for device in devices:
                    logger.info("-" * 40)
                    logger.info(f"  Name: {device.display_name}")
                    logger.info(f"  Device ID: {device.device_id}")
                    logger.info(f"  Current Mode: {device.current_mode}")
                    if device.ambient_temperature_celsius:
                        temp_f = (device.ambient_temperature_celsius * 9 / 5) + 32
                        logger.info(
                            f"  Temperature: {device.ambient_temperature_celsius:.1f}°C / {temp_f:.1f}°F"
                        )
                    if device.humidity_percent:
                        logger.info(f"  Humidity: {device.humidity_percent}%")

            logger.info("=" * 60)
            logger.info("To control specific thermostats, set NEST_DEVICE_IDS env var")
            logger.info("Example: NEST_DEVICE_IDS=device-id-1,device-id-2")
            logger.info("=" * 60)

            return devices

        except Exception as e:
            logger.error(f"Failed to discover devices: {e}")
            raise

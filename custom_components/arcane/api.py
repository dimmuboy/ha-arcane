import asyncio
import logging
from typing import Any, Dict

import aiohttp
import async_timeout

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 30
REDEPLOY_TIMEOUT = 300


class ArcaneAuthError(Exception):
    """Error to indicate there is invalid auth."""


class ArcaneConnectionError(Exception):
    """Error to indicate there is a connection issue."""


class ArcaneAPI:
    def __init__(
        self,
        host: str,
        api_key: str,
        env_id: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self._host = host.rstrip("/")
        if not (self._host.startswith("http://") or self._host.startswith("https://")):
            self._host = f"http://{self._host}"

        self._api_key = api_key.strip()
        self._env_id = env_id
        self._session = session
        self._headers = {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def get_containers(self) -> Dict[str, Any]:
        url = f"{self._host}/api/environments/{self._env_id}/containers"
        try:
            async with async_timeout.timeout(TIMEOUT):
                response = await self._session.get(url, headers=self._headers)
                if response.status == 401:
                    raise ArcaneAuthError("Invalid API Key")
                response.raise_for_status()
                return await response.json()
        except aiohttp.ClientError as exception:
            _LOGGER.error("Error fetching data from Arcane: %s", exception)
            raise
        except Exception as exception:
            _LOGGER.error("Unexpected error fetching data from Arcane: %s", exception)
            raise

    async def control_container(self, container_id: str, action: str) -> None:
        if action not in ["start", "stop", "restart"]:
            raise ValueError(f"Invalid action: {action}")

        url = f"{self._host}/api/environments/{self._env_id}/containers/{container_id}/{action}"
        try:
            async with async_timeout.timeout(TIMEOUT):
                response = await self._session.post(url, headers=self._headers)
                response.raise_for_status()
        except aiohttp.ClientError as exception:
            _LOGGER.error("Error controlling container %s: %s", container_id, exception)
            raise
        except Exception as exception:
            _LOGGER.error(
                "Unexpected error controlling container %s: %s", container_id, exception
            )
            raise

    async def redeploy_container(self, container_id: str) -> Dict[str, Any]:
        """Redeploy container by asking Arcane to pull the latest image and recreate it."""
        url = f"{self._host}/api/environments/{self._env_id}/containers/{container_id}/redeploy"
        try:
            _LOGGER.info("Starting redeploy for container %s", container_id)
            _LOGGER.debug("Redeploy URL: %s", url)

            async with async_timeout.timeout(REDEPLOY_TIMEOUT):
                response = await self._session.post(url, headers=self._headers)

                _LOGGER.info("Redeploy response status: %d", response.status)
                _LOGGER.debug("Response headers: %s", response.headers)

                if response.status == 401:
                    error_text = await response.text()
                    _LOGGER.error("Authentication failed: %s", error_text)
                    raise ArcaneAuthError("Invalid API Key")

                if response.status >= 400:
                    error_text = await response.text()
                    _LOGGER.error(
                        "Redeploy failed with status %d: %s",
                        response.status,
                        error_text,
                    )
                    raise Exception(f"HTTP {response.status}: {error_text}")

                try:
                    result = await response.json()
                    _LOGGER.info("Redeploy successful, response: %s", result)
                    return result
                except (aiohttp.ContentTypeError, ValueError) as e:
                    _LOGGER.debug("Non-JSON response from redeploy endpoint: %s", e)
                    return {"success": True}

        except asyncio.TimeoutError as e:
            error_msg = f"Redeploy timeout (exceeded {REDEPLOY_TIMEOUT}s)"
            _LOGGER.error(error_msg)
            raise Exception(error_msg) from e
        except aiohttp.ClientError as e:
            error_msg = f"Client error during redeploy: {type(e).__name__}: {e}"
            _LOGGER.error(error_msg)
            raise Exception(error_msg) from e
        except ArcaneAuthError:
            raise
        except Exception as e:
            error_msg = f"Unexpected error redeploying container {container_id}: {type(e).__name__}: {e}"
            _LOGGER.error(error_msg, exc_info=True)
            raise Exception(error_msg) from e

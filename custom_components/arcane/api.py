import logging
from typing import Any, Dict, List

import aiohttp
import async_timeout

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 30  # Increased timeout for redeploy operations


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
        """Redeploy container (pull latest image and recreate).
        
        This is the correct endpoint to use for updating a container to the latest image.
        Arcane automatically detects image updates through updateInfo in container data.
        
        Returns the response from Arcane API.
        Raises exceptions on failure.
        """
        url = f"{self._host}/api/environments/{self._env_id}/containers/{container_id}/redeploy"
        try:
            async with async_timeout.timeout(TIMEOUT):
                _LOGGER.debug("Sending redeploy request to: %s", url)
                response = await self._session.post(url, headers=self._headers)
                
                # Log response status
                _LOGGER.debug("Redeploy response status: %s", response.status)
                
                if response.status == 401:
                    raise ArcaneAuthError("Invalid API Key")
                
                # Handle various status codes
                if response.status >= 400:
                    error_text = await response.text()
                    _LOGGER.error(
                        "Redeploy failed with status %s: %s",
                        response.status,
                        error_text,
                    )
                    raise Exception(f"Redeploy failed: {response.status} - {error_text}")
                
                # Try to parse as JSON, but handle empty responses
                try:
                    result = await response.json()
                    _LOGGER.debug("Redeploy response: %s", result)
                    return result
                except (aiohttp.ContentTypeError, ValueError):
                    # Empty or non-JSON response is OK for successful redeploy
                    _LOGGER.debug("Redeploy successful (empty response)")
                    return {"success": True}
                    
        except asyncio.TimeoutError as exception:
            _LOGGER.error("Timeout redeploying container %s", container_id)
            raise Exception(f"Redeploy timeout for container {container_id}") from exception
        except aiohttp.ClientError as exception:
            _LOGGER.error("Client error redeploying container %s: %s", container_id, exception)
            raise Exception(f"Client error: {exception}") from exception
        except Exception as exception:
            _LOGGER.error(
                "Unexpected error redeploying container %s: %s",
                container_id,
                exception,
            )
            raise


# Import asyncio at module level
import asyncio

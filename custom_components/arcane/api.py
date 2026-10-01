import logging
from typing import Any

import aiohttp
import async_timeout

_LOGGER = logging.getLogger(__name__)

TIMEOUT = 30


class ArcaneAuthError(Exception):
    """Error to indicate there is invalid auth."""


class ArcaneConnectionError(Exception):
    """Error to indicate there is a connection issue."""


class ArcaneAPI:
    """Client for the Arcane Manager API."""

    def __init__(
        self,
        host: str,
        api_key: str,
        session: aiohttp.ClientSession,
    ) -> None:
        self._host = host.rstrip("/")
        if not self._host.startswith(("http://", "https://")):
            self._host = f"http://{self._host}"

        self._api_key = api_key.strip()
        self._session = session
        self._headers = {
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: int = TIMEOUT,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Perform an authenticated Arcane API request."""
        url = f"{self._host}/api{path}"
        try:
            async with async_timeout.timeout(timeout):
                response = await self._session.request(
                    method, url, headers=self._headers, json=json
                )
                if response.status in (401, 403):
                    raise ArcaneAuthError("Invalid or insufficient Arcane API key")
                response.raise_for_status()

                if response.status == 204:
                    return {"success": True}

                try:
                    return await response.json()
                except (aiohttp.ContentTypeError, ValueError):
                    return {"success": True}
        except ArcaneAuthError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exception:
            raise ArcaneConnectionError(
                f"Error communicating with Arcane at {url}: {exception}"
            ) from exception

    async def get_environments(self) -> dict[str, Any]:
        """Return all environments visible to the API key."""
        return await self._request("GET", "/environments?start=0&limit=100")

    async def get_containers(self, environment_id: str) -> dict[str, Any]:
        """Return containers for an environment."""
        return await self._request(
            "GET",
            f"/environments/{environment_id}/containers?start=0&limit=100",
        )

    async def get_projects(self, environment_id: str) -> dict[str, Any]:
        """Return Compose projects for an environment."""
        return await self._request(
            "GET",
            f"/environments/{environment_id}/projects?start=0&limit=100",
        )

    async def control_project(
        self, environment_id: str, project_id: str, action: str
    ) -> dict[str, Any]:
        """Run a supported Compose project action."""
        if action not in {"restart", "redeploy"}:
            raise ValueError(f"Invalid project action: {action}")

        return await self._request(
            "POST",
            f"/environments/{environment_id}/projects/{project_id}/{action}",
            timeout=300,
        )

    async def update_project(
        self, environment_id: str, project_id: str
    ) -> dict[str, Any]:
        """Pull latest images and recreate all services in a project."""
        return await self._request(
            "POST",
            f"/environments/{environment_id}/projects/{project_id}/update-services",
            timeout=300,
            json={},
        )

    async def control_container(
        self, environment_id: str, container_id: str, action: str
    ) -> None:
        """Start, stop, or restart a container."""
        if action not in {"start", "stop", "restart"}:
            raise ValueError(f"Invalid action: {action}")

        await self._request(
            "POST",
            f"/environments/{environment_id}/containers/{container_id}/{action}",
        )

    async def update_container(
        self, environment_id: str, container_id: str
    ) -> dict[str, Any]:
        """Update a container using Arcane's updater strategy."""
        return await self._request(
            "POST",
            f"/environments/{environment_id}/containers/{container_id}/update",
            timeout=300,
        )

    async def redeploy_container(
        self, environment_id: str, container_id: str
    ) -> dict[str, Any]:
        """Pull the latest image and recreate a container."""
        return await self._request(
            "POST",
            f"/environments/{environment_id}/containers/{container_id}/redeploy",
            timeout=300,
        )

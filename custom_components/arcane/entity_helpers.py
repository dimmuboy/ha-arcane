from __future__ import annotations

from typing import Any

from .const import DOMAIN


def container_device_info(container: dict[str, Any]) -> dict[str, Any]:
    """Return the parent device for a container."""
    environment_id = str(container.get("_environment_id", "unknown"))
    project_key = container.get("_project_key")

    if isinstance(project_key, str) and project_key:
        return {
            "identifiers": {(DOMAIN, f"project:{project_key}")},
        }

    return {
        "identifiers": {(DOMAIN, f"standalone:{environment_id}")},
        "name": "Standalone containers",
        "manufacturer": "Arcane",
        "model": "Standalone Docker Containers",
        "via_device": (DOMAIN, f"environment:{environment_id}"),
    }

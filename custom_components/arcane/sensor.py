from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import ArcaneDataUpdateCoordinator
from .const import DOMAIN, SIGNAL_NEW_CONTAINERS, SIGNAL_NEW_PROJECTS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: ArcaneDataUpdateCoordinator = hass.data[DOMAIN][entry.entry_id]

    environment_entities = []
    for environment_id in coordinator.data["environments"]:
        for sensor_type in (
            "Containers",
            "Running",
            "Stopped",
            "Images",
            "Docker version",
            "Critical vulnerabilities",
            "High vulnerabilities",
        ):
            environment_entities.append(
                ArcaneEnvironmentSensor(coordinator, environment_id, sensor_type)
            )
    if environment_entities:
        async_add_entities(environment_entities)

    def add_container_sensors(keys: set[str] | None = None) -> None:
        if keys is None:
            keys = set(coordinator.data["containers"])

        entities = []
        for key in keys:
            entities.extend(
                (
                    ArcaneSensor(coordinator, key, "State"),
                    ArcaneSensor(coordinator, key, "Image"),
                    ArcaneSensor(coordinator, key, "CPU"),
                    ArcaneSensor(coordinator, key, "Memory"),
                    ArcaneSensor(coordinator, key, "Memory limit"),
                )
            )
        if entities:
            async_add_entities(entities)

    add_container_sensors()

    def add_project_sensors(keys: set[str] | None = None) -> None:
        if keys is None:
            keys = set(coordinator.data.get("projects", {}))
        entities = []
        for key in keys:
            entities.extend(
                (
                    ArcaneProjectSensor(coordinator, key, "Status"),
                    ArcaneProjectSensor(coordinator, key, "Services"),
                    ArcaneProjectSensor(coordinator, key, "Running services"),
                    ArcaneProjectSensor(coordinator, key, "Updates available"),
                )
            )
        if entities:
            async_add_entities(entities)

    add_project_sensors()

    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{SIGNAL_NEW_CONTAINERS}_{entry.entry_id}",
            add_container_sensors,
        )
    )
    entry.async_on_unload(
        async_dispatcher_connect(
            hass,
            f"{SIGNAL_NEW_PROJECTS}_{entry.entry_id}",
            add_project_sensors,
        )
    )


class ArcaneSensor(CoordinatorEntity, SensorEntity):
    def __init__(
        self,
        coordinator: ArcaneDataUpdateCoordinator,
        container_key: str,
        sensor_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._container_key = container_key
        self._sensor_type = sensor_type
        self._attr_unique_id = f"{container_key}_{sensor_type.lower()}"
        self._attr_has_entity_name = True
        self._attr_name = sensor_type
        icons = {
            "State": "mdi:docker",
            "Image": "mdi:image",
            "CPU": "mdi:cpu-64-bit",
            "Memory": "mdi:memory",
            "Memory limit": "mdi:memory",
        }
        self._attr_icon = icons.get(sensor_type, "mdi:docker")
        if sensor_type == "CPU":
            self._attr_native_unit_of_measurement = "%"
        elif sensor_type in {"Memory", "Memory limit"}:
            self._attr_native_unit_of_measurement = "MiB"

    @property
    def _container(self) -> dict[str, Any]:
        return self.coordinator.data["containers"].get(self._container_key, {})

    @property
    def device_info(self) -> dict[str, Any]:
        container = self._container
        environment_id = container.get("_environment_id", "unknown")
        environment_name = container.get("_environment_name", environment_id)
        name = container.get("names", [self._container_key])[0].lstrip("/")
        return {
            "identifiers": {(DOMAIN, self._container_key)},
            "name": name,
            "manufacturer": "Arcane",
            "model": f"Container · {environment_name}",
            "via_device": (DOMAIN, f"environment:{environment_id}"),
        }

    @property
    def native_value(self) -> str | None:
        container = self._container
        if self._sensor_type == "State":
            return container.get("state")
        if self._sensor_type == "Image":
            return container.get("image")
        sample = container.get("resourceSample")
        if not isinstance(sample, dict):
            return None
        if self._sensor_type == "CPU":
            return round(sample.get("cpuPercent", 0), 2)
        if self._sensor_type == "Memory":
            return round(sample.get("memoryUsageBytes", 0) / 1048576, 1)
        if self._sensor_type == "Memory limit":
            return round(sample.get("memoryLimitBytes", 0) / 1048576, 1)
        return None



class ArcaneEnvironmentSensor(CoordinatorEntity, SensorEntity):
    """Summary sensor for an Arcane environment."""

    def __init__(
        self,
        coordinator: ArcaneDataUpdateCoordinator,
        environment_id: str,
        sensor_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._environment_id = environment_id
        self._sensor_type = sensor_type
        self._attr_unique_id = f"environment:{environment_id}_{sensor_type.lower()}"
        self._attr_has_entity_name = True
        self._attr_name = sensor_type
        self._attr_icon = "mdi:docker"

    @property
    def _environment(self) -> dict[str, Any]:
        return self.coordinator.data["environments"].get(self._environment_id, {})

    @property
    def device_info(self) -> dict[str, Any]:
        environment = self._environment
        return {
            "identifiers": {(DOMAIN, f"environment:{self._environment_id}")},
            "name": environment.get("name", self._environment_id),
            "manufacturer": "Arcane",
            "model": f"Environment · {environment.get('type', 'Docker')}",
        }

    @property
    def native_value(self) -> str | int | None:
        containers = [
            container
            for container in self.coordinator.data["containers"].values()
            if container.get("_environment_id") == self._environment_id
        ]
        if self._sensor_type == "Containers":
            return len(containers)
        if self._sensor_type == "Running":
            return sum(container.get("state") == "running" for container in containers)
        if self._sensor_type == "Stopped":
            return sum(container.get("state") != "running" for container in containers)

        docker_info = self._environment.get("_docker_info")
        if not isinstance(docker_info, dict):
            docker_info = {}
        if self._sensor_type == "Images":
            return docker_info.get("Images")
        if self._sensor_type == "Docker version":
            return docker_info.get("ServerVersion")

        vulnerabilities = self._environment.get("_vulnerabilities")
        if not isinstance(vulnerabilities, dict):
            vulnerabilities = {}
        if self._sensor_type == "Critical vulnerabilities":
            return vulnerabilities.get("critical")
        if self._sensor_type == "High vulnerabilities":
            return vulnerabilities.get("high")
        return None



class ArcaneProjectSensor(CoordinatorEntity, SensorEntity):
    """Sensor for an Arcane Compose project."""

    def __init__(
        self,
        coordinator: ArcaneDataUpdateCoordinator,
        project_key: str,
        sensor_type: str,
    ) -> None:
        super().__init__(coordinator)
        self._project_key = project_key
        self._sensor_type = sensor_type
        slug = sensor_type.lower().replace(" ", "_")
        self._attr_unique_id = f"project:{project_key}_{slug}"
        self._attr_has_entity_name = True
        self._attr_name = sensor_type
        self._attr_icon = "mdi:docker"

    @property
    def _project(self) -> dict[str, Any]:
        return self.coordinator.data.get("projects", {}).get(self._project_key, {})

    @property
    def device_info(self) -> dict[str, Any]:
        project = self._project
        environment_id = project.get("_environment_id", "unknown")
        return {
            "identifiers": {(DOMAIN, f"project:{self._project_key}")},
            "name": project.get("name", self._project_key),
            "manufacturer": "Arcane",
            "model": "Docker Compose Project",
            "via_device": (DOMAIN, f"environment:{environment_id}"),
        }

    @property
    def native_value(self) -> str | int | None:
        project = self._project
        if self._sensor_type == "Status":
            return project.get("status")
        if self._sensor_type == "Services":
            return project.get("serviceCount")
        if self._sensor_type == "Running services":
            return project.get("runningCount")
        update_info = project.get("updateInfo")
        if isinstance(update_info, dict):
            return update_info.get("imagesWithUpdates", 0)
        return 0

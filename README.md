# Arcane for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Arcane is a modern, self-hosted Docker management platform. This integration allows you to monitor, control, and update your Docker containers directly from Home Assistant. Note that this is mostly a vibe-coded integration and I'm still deciding whether I wish to maintain it long-term.

## Features

- **Monitor Container State:** Real-time status of your Docker containers.
- **Control Containers:** Start, Stop, and Restart containers from the HA dashboard.
- **Update Containers:** Install available image updates through Home Assistant update entities.
- **Graceful Shutdown:** Stops containers gracefully.
- **Sensor Data:** Monitor container images and status.

## Installation

### HACS (Recommended)

1. Open HACS in Home Assistant.
2. Click on **Integrations**.
3. Click the three dots in the top right corner and select **Custom repositories**.
4. Paste `https://github.com/dimmuboy/ha-arcane` and select **Integration** as the category.
5. Click **Add**.
6. Find the **Arcane** integration and click **Download**.
7. Restart Home Assistant.

### Manual

1. Download the `arcane` folder from `custom_components/` in this repository.
2. Copy the folder to your `custom_components/` directory in Home Assistant.
3. Restart Home Assistant.

## Configuration

1. Go to **Settings** -> **Devices & Services**.
2. Click **Add Integration**.
3. Search for **Arcane**.
4. Enter your Arcane Host, API Key, and Environment ID (default is `0` for local).

## Container Updates

Home Assistant update entities use Arcane's redeploy endpoint. Arcane pulls the latest image and recreates the container while preserving its existing configuration. The update entity is disabled when Arcane reports that redeploy is disabled for a container, such as the Arcane server container itself.

## License

MIT

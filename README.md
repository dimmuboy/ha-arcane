# Arcane for Home Assistant

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://github.com/hacs/integration)

Arcane is a modern, self-hosted Docker management platform. This integration allows you to monitor, control, and update your Docker containers directly from Home Assistant. Note that this is mostly a vibe-coded integration and I'm still deciding whether I wish to maintain it long-term.

## Features

- Automatic discovery of all environments managed by one Arcane Manager, including Edge environments
- Environment devices with Docker container, image, version, and vulnerability summaries
- Container devices with state, image, CPU, memory usage, memory limit, start/stop, restart, redeploy, and update controls
- Docker Compose project devices with status, service counts, restart, redeploy, and project-wide updates
- Environment-aware stable entity identities, so identical container and project names can exist in different environments
- Configurable polling interval
- Home Assistant diagnostics with the API key redacted
- Local polling through the Arcane API


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
4. Enter your Arcane Host, API Key, and ng configuration. The update entity is disabled when Arcane reports that redeploy is disabled for a container, such as the Arcane server container itself.

## License

MIT

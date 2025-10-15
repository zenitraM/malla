# Malla

Malla (_Mesh_, in Spanish) is an ([AI-built](./AI.md)) tool that logs Meshtastic packets from an MQTT broker into a SQLite database and exposes a web UI to get some interesting data insights from them.

## Running Instances
Check out some instances with running data from community MQTT servers:
- meshtastic.es (Spain): https://malla.meshtastic.es
- meshworks.ru (Russia/Moscow): https://malla.meshworks.ru/

## Meshworks Fork Enhancements

This repository is a Meshworks-maintained fork of [zenitraM/malla](https://github.com/zenitraM/malla) with the following additions:

- Includes the upstream protocol-diversity fix (no 10-item cap) plus extra integration coverage.
- Ships refreshed dark-mode assets and README screenshots generated directly from this fork.
- Provides ready-to-use local demo tooling (fixtures + `scripts/generate_screenshots.py`) aligned with our infrastructure needs.

All other functionality stays compatible with the original project so upstream changes can be merged easily.

## Features

### 🚀 Key Highlights

• **End-to-end capture** – Logs every packet from your Meshtastic MQTT broker straight into an optimised SQLite database.

• **Live dashboard** – Real-time counters for total / active nodes, packet rate, signal quality bars and network-health indicators (auto-refresh).

• **Packet browser** – Lightning-fast table with powerful filtering (time range, node, port, RSSI/SNR, type), pagination and one-click CSV export.

• **Node explorer** – Detailed hardware, role, battery and signal info for every node – searchable picker plus online/offline badges.

• **Traceroutes** – Historical list view to inspect packet paths across the mesh network.

• **Map view** – Leaflet map with live node locations, RF-link overlays and role colour-coding.

• **Network graph** – Force-directed graph visualising multi-hop links and RF distances between nodes / gateways.

• **Toolbox** – Hop-analysis tables, gateway-compare matrix and "longest links" explorer for deep dives.

• **Analytics charts** – 7-day trends, RSSI distribution, top talkers, hop distribution and more (Plotly powered).

• **Single-source config** – One `config.yaml` (or `MALLA_*` env-vars) drives both the capture tool and the web UI.

• **One-command launch** – `malla-capture` and `malla-web` wrapper scripts get you up and running in seconds.

<!-- screenshots:start -->
![dashboard](.screenshots/dashboard.jpg)
![nodes](.screenshots/nodes.jpg)
![packets](.screenshots/packets.jpg)
![traceroutes](.screenshots/traceroutes.jpg)
![map](.screenshots/map.jpg)
![traceroute_graph](.screenshots/traceroute_graph.jpg)
![hop_analysis](.screenshots/hop_analysis.jpg)
![gateway_compare](.screenshots/gateway_compare.jpg)
![longest_links](.screenshots/longest_links.jpg)
<!-- screenshots:end -->

## Prerequisites

- Python 3.13+
- Access to a Meshtastic MQTT broker
- Modern web browser with JavaScript enabled

## Installation

### Using Docker (Recommended)

The easiest way to run Malla is using Docker. Pre-built images are available from GitHub Container Registry:

1. **Copy the environment configuration:**
   ```bash
   cp env.example .env
   ```

2. **Edit the configuration:**
   ```bash
   $EDITOR .env  # Set your MQTT broker address and other settings
   ```

3. **Start the services:**
   ```bash
   docker-compose up -d
   ```

4. **View logs:**
   ```bash
   docker-compose logs -f
   ```

5. **Access the web UI:**
   - Open http://localhost:5008 in your browser

**For development with local code changes:**
```bash
# Edit docker-compose.yml to uncomment the 'build: .' lines
# Then build and run:
docker-compose up --build -d
```

**Manual Docker run (advanced):**
```bash
# Run the capture service
docker run -d \
  --name malla-capture \
  -v malla_data:/app/data \
  -e MALLA_MQTT_BROKER_ADDRESS=your.mqtt.broker.address \
  ghcr.io/zenitram/malla:latest \
  /app/.venv/bin/malla-capture

# Run the web UI
docker run -d \
  --name malla-web \
  -p 5008:5008 \
  -v malla_data:/app/data \
  ghcr.io/zenitram/malla:latest
```

### Using uv

You can also install and run Malla directly using [uv](https://docs.astral.sh/uv/):
1. **Clone or download** the project files to your preferred directory
   ```bash
   git clone https://github.com/zenitraM/malla.git
   cd malla
   ```

2. **Install uv** if you don't have it installed yet:
   ```bash
   curl -LsSf https://astral.sh/uv/install.sh | sh
   ```

3. **Create a configuration file** by copying the sample file:
   ```bash
   cp config.sample.yaml config.yaml
   $EDITOR config.yaml  # tweak values as desired
   ```

4. **Start it** with `uv run` in the project directory, which should pull the required dependencies.
   ```bash
   # Start the web UI
   uv run malla-web

   # Start the MQTT capture tool
   uv run malla-capture
   ```

### Using Nix
The project also comes with a Nix flake and a devshell - if you have Nix installed or run NixOS it will set up
`uv` for you together with the exact system dependencies that run on CI (Playwright, etc.):

```bash
nix develop --command uv run malla-web
nix develop --command uv run malla-capture
```

## Quick Start

The system consists of two components that work together:

### 1. MQTT Data Capture

This tool connects to your Meshtastic MQTT broker and captures all mesh packets to a SQLite database. You will need to configure the MQTT broker address in the `config.yaml` file (or set the `MALLA_MQTT_BROKER_ADDRESS` environment variable) before starting it. See [Configuration Options](#configuration-options) for the entire set of settings.

```yaml
mqtt_broker_address: "your.mqtt.broker.address"
```

You can use this tool with your own MQTT broker that you've got your own nodes connected to, or with a public broker if you've got permission to do so.

**Start the capture tool:**
```bash
uv run malla-capture
```

### 2. Web UI

The web interface for browsing and analyzing the captured data.

**Start the web UI:**
```bash
uv run malla-web
```

**Access the web interface:**
- Local: http://localhost:5008

## Running Both Tools Together

For a complete monitoring setup, run both tools simultaneously:

**Terminal 1 - Data Capture:**
```bash
export MALLA_MQTT_BROKER_ADDRESS="127.0.0.1"  # Replace with your broker
./malla-capture
```

**Terminal 2 - Web UI:**
```bash
./malla-web
```

Both tools use the same SQLite database concurrently using thread-safe connections.

## Docker Configuration

When using Docker, configuration is handled through environment variables defined in your `.env` file:

### Production Deployment with Gunicorn

For production deployments, Malla supports running with Gunicorn, a production-ready WSGI server that provides better performance and stability than Flask's development server.

**Option 1: Using environment variable (recommended)**
```bash
# In your .env file:
MALLA_WEB_COMMAND=/app/.venv/bin/malla-web-gunicorn
```

**Option 2: Using the production override file**
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Option 3: Direct script execution**
```bash
# For local development with uv:
uv run malla-web-gunicorn

# Or using the executable script:
./malla-web-gunicorn
```

The Gunicorn configuration automatically:
- Uses multiple worker processes based on CPU cores
- Enables proper logging and monitoring
- Configures appropriate timeouts and connection limits
- Provides better concurrent request handling

**Benefits of Gunicorn over Flask dev server:**
- Production-ready with proper process management
- Better performance under load
- Automatic worker process recycling
- Proper signal handling for graceful shutdowns
- Enhanced logging and monitoring capabilities

### Environment File Setup
1. **Copy the example:**
   ```bash
   cp env.example .env
   ```

2. **Configure your settings:**
   ```bash
   # Required: Set your MQTT broker address
   MALLA_MQTT_BROKER_ADDRESS=your.mqtt.broker.address

   # Optional: Customize other settings
   MALLA_NAME=My Malla Instance
   MALLA_WEB_PORT=5008
   MALLA_SECRET_KEY=your-production-secret-key
   ```

### Key Configuration Options
- `MALLA_MQTT_BROKER_ADDRESS`: Your MQTT broker IP/hostname (**required**)
- `MALLA_MQTT_PORT`: MQTT broker port (default: 1883)
- `MALLA_MQTT_USERNAME`/`MALLA_MQTT_PASSWORD`: MQTT authentication (optional)
- `MALLA_WEB_PORT`: Port to expose the web UI (default: 5008)
- `MALLA_NAME`: Display name in the web interface

### Data Persistence
Data is automatically stored in a Docker volume (`malla_data`) and persists across container restarts. No manual volume setup is required when using `docker-compose`.

## Configuration Options

### YAML configuration file *(recommended)*

Malla will automatically look for a file named `config.yaml` in the **current
working directory** when it starts.  You can point to an alternative file by
setting the `MALLA_CONFIG_FILE` environment variable.

If the file is not found, all built-in defaults are used (see
`config.sample.yaml`).

Copy the sample file and customise it:

```bash
cp config.sample.yaml config.yaml
$EDITOR config.yaml  # tweak values as required
```

The file is **git-ignored** so you will never accidentally commit secrets such
as your `secret_key`.

The following keys are recognised:

| YAML key        | Type   | Default                                  | Description                                   | Env-var override |
| --------------- | ------ | ---------------------------------------- | --------------------------------------------- | ---------------- |
| `name`          | str    | `"Malla"`                                | Display name shown in the navigation bar.     | `MALLA_NAME` |
| `home_markdown` | str    | `""`                                     | Markdown rendered on the dashboard homepage.  | `MALLA_HOME_MARKDOWN` |
| `secret_key`    | str    | `"dev-secret-key-change-in-production"` | Flask session secret key (change in prod!). (currently unused)   | `MALLA_SECRET_KEY` |
| `database_file` | str    | `"meshtastic_history.db"`                | SQLite database file location.                | `MALLA_DATABASE_FILE` |
| `host`          | str    | `"0.0.0.0"`                              | Interface to bind the web server to.          | `MALLA_HOST` |
| `port`          | int    | `5008`                                   | TCP port for the web server.                  | `MALLA_PORT` |
| `debug`         | bool   | `false`                                  | Run Flask in debug mode (unsafe for prod!).   | `MALLA_DEBUG` |
| `mqtt_broker_address` | str | `"127.0.0.1"`                      | MQTT broker hostname or IP address.           | `MALLA_MQTT_BROKER_ADDRESS` |
| `mqtt_port`     | int    | `1883`                                   | MQTT broker port.                              | `MALLA_MQTT_PORT` |
| `mqtt_username` | str    | `""`                                     | MQTT broker username (optional).               | `MALLA_MQTT_USERNAME` |
| `mqtt_password` | str    | `""`                                     | MQTT broker password (optional).               | `MALLA_MQTT_PASSWORD` |
| `mqtt_topic_prefix` | str | `"msh"`                                 | MQTT topic prefix for Meshtastic messages.    | `MALLA_MQTT_TOPIC_PREFIX` |
| `mqtt_topic_suffix` | str | `"/+/+/+/#"`                           | MQTT topic suffix pattern.                     | `MALLA_MQTT_TOPIC_SUFFIX` |
| `default_channel_key` | str | `"1PG7OiApB1nwvP+rz05pAQ=="`         | Default channel key for decryption (base64).  | `MALLA_DEFAULT_CHANNEL_KEY` |

Environment variables **always override** values coming from the YAML file.

## Contributing

Feel free to submit issues, feature requests, or pull requests to improve Malla!

## License

This project is licensed under the [MIT](LICENSE) license.

# Malla - Meshtastic Mesh Health Web UI

Always reference these instructions first and fallback to search or bash commands only when you encounter unexpected information that does not match the info here.

## Working Effectively

Bootstrap, build, and test the repository:
- Install uv package manager: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Add uv to PATH: `export PATH="/home/runner/.local/bin:$PATH"`
- Install dependencies: `uv sync` -- takes 5 seconds on first run
- Install development dependencies: `uv sync --dev` -- takes <1 second if dependencies already exist

Test the codebase:
- Check test environment: `uv run python run_tests.py --check`
- Run unit tests: `uv run python run_tests.py unit -v` -- takes 1.4 seconds. NEVER CANCEL.
- Run integration tests: `uv run python run_tests.py integration -v` -- takes 4.3 seconds. NEVER CANCEL.
- Run full test suite: `make check` -- takes 3 minutes. NEVER CANCEL. Set timeout to 240+ seconds.
- Install Playwright browsers (for e2e tests): `uv run playwright install` -- takes 12 seconds

Lint and format code:
- Lint only: `make lint` -- takes 4.8 seconds
- Format code: `make format` -- takes <0.1 seconds  
- Check + test: `make check` -- runs lint + full test suite, takes 3 minutes. NEVER CANCEL.

Run the applications:
- ALWAYS run the bootstrapping steps first
- Web UI: `uv run malla-web` (development server, Flask)
- Web UI (production): `uv run malla-web-gunicorn` (Gunicorn WSGI server)
- MQTT capture: `uv run malla-capture` (requires MQTT broker configuration)
- Access web UI at: http://localhost:5008
- **Note**: Always use `uv run` commands. The wrapper scripts (`./malla-web`, `./malla-capture`) require the virtual environment to be activated.

## Validation

- **CRITICAL**: ALL TESTS MUST PASS - Do not break existing tests under any circumstances
- **MANDATORY**: ABSOLUTELY POSITIVELY RUN ALL OF THE TEST SUITE to verify your CHANGES ALL THE TIME
- **MANDATORY**: Always run `make check` before considering work finished - this runs the full CI pipeline (takes 3 minutes)
- **REQUIRED**: Run `make format` and `make lint` before committing or CI will fail
- **NON-NEGOTIABLE**: Fix all linting errors before committing - formatting issues can be auto-fixed with `make format`
- **NON-NEGOTIABLE**: YOU SHALL NOT BREAK THE TESTS - Test failures indicate broken functionality that must be debugged and fixed, not ignored
- **FAILURE**: Discovering test failures only when they run on CI is a failure worth -100 points
- **MANDATORY**: If there's something missing for you to run tests, dig until you've found them and update your own configuration if needed

**Complete validation workflow (MANDATORY before finishing):**
1. Format code: `make format` (auto-fixes formatting issues)
2. Lint code: `make lint` (must pass completely)
3. Run comprehensive CI checks: `make check` (ALL tests must pass - 430+ tests including 44 unit, 168 integration)
4. Manual validation: Start web UI `uv run malla-web` and verify basic functionality
5. Only commit changes after ALL validation passes

**Critical validation points:**
- Web UI starts and serves HTTP 200 on port 5008
- API endpoints return valid JSON responses
- Database gets created automatically
- **ALL unit tests pass (44 tests)**
- **ALL integration tests pass (168 tests)**
- E2E tests may fail in sandboxed environments due to missing browser dependencies (expected)
- ANY test regression indicates broken functionality that MUST be fixed

## Critical Timeouts and "NEVER CANCEL" Warnings

**NEVER CANCEL: Full test suite takes 3 minutes. Set timeout to 240+ seconds.**
**NEVER CANCEL: Build operations are fast (<10 seconds) but CI includes comprehensive testing.**
**NEVER CANCEL: Playwright browser installation takes 12 seconds.**

## Configuration

**IMPORTANT**: Copy configuration before running:
```bash
cp config.sample.yaml config.yaml
```

Configuration can be done via:
1. YAML file: `config.yaml` (recommended for development)
2. Environment variables: Prefix all settings with `MALLA_` (recommended for production)

Key settings:
- `mqtt_broker_address`: MQTT broker hostname/IP (required for capture tool)
- `database_file`: SQLite database location (default: "meshtastic_history.db")
- `host`/`port`: Web server bind address (default: 0.0.0.0:5008)

## Docker Deployment

For production deployment:
```bash
# Copy environment configuration
cp env.example .env
# Edit .env with your MQTT broker address and settings
docker-compose up -d
```

For development with local changes:
```bash
# Edit docker-compose.yml to uncomment 'build: .' lines
docker-compose up --build -d
```

## Common Tasks

### Repository Structure
```
├── src/malla/           # Main application code
│   ├── web_ui.py       # Flask web application entry point
│   ├── mqtt_capture.py # MQTT capture tool entry point
│   ├── routes/         # Web UI routes and API endpoints
│   ├── models/         # Data models and database interaction
│   ├── services/       # Business logic services  
│   ├── templates/      # Jinja2 HTML templates
│   └── static/         # CSS, JavaScript, and static assets
├── tests/              # Test suite (unit, integration, e2e)
├── .github/workflows/  # CI/CD pipelines
├── malla-web*          # Executable wrapper scripts
├── pyproject.toml      # Project configuration and dependencies
├── Makefile           # Common development commands
└── run_tests.py       # Test runner script
```

### Wrapper Scripts
- `./malla-web` - Flask development server
- `./malla-web-gunicorn` - Gunicorn production server  
- `./malla-capture` - MQTT capture tool

### Package Management
- Dependencies: managed via `uv` and locked in `uv.lock`
- Python version: 3.13+ required
- Virtual environment: automatically created by `uv` in `.venv/`

### Database
- SQLite database with automatic schema migrations
- Default location: `meshtastic_history.db` 
- Contains packet history, node info, and location data
- Shared between capture tool and web UI with thread-safe connections

### Key Technologies
- **Backend**: Python 3.13, Flask, SQLite
- **Frontend**: HTML, CSS, JavaScript, Plotly, Leaflet maps
- **Testing**: pytest, Playwright (e2e)
- **Build**: uv package manager, Makefile
- **Deploy**: Docker, Gunicorn
- **CI**: GitHub Actions with Nix

### Testing Categories
- **Unit tests**: Fast isolated component tests (~1.4s)
- **Integration tests**: API and database integration tests (~4.3s)  
- **E2E tests**: Full browser automation tests (included in 3min full suite)
- Run specific categories: `uv run python run_tests.py [unit|integration|all] -v`

## Troubleshooting

**Import errors**: Run `uv sync` to ensure dependencies are installed
**Test failures**: Run `uv run python run_tests.py --check` to verify test environment
**Python version errors**: Use `uv run` commands, not direct python calls
**MQTT connection errors**: Expected when no broker configured, application starts correctly
**Playwright browser errors**: Run `uv run playwright install` and note that some system dependencies may be missing in sandboxed environments
**Linting failures**: Run `make format` to auto-fix formatting issues

## Development Workflow

1. Make code changes
2. **MANDATORY**: Format code: `make format` (auto-fixes formatting issues)
3. **MANDATORY**: Run linting: `make lint` (must pass completely before committing)
4. **MANDATORY**: Run comprehensive tests: `make check` (ALL TESTS MUST PASS - takes 3 minutes, NEVER CANCEL)
5. Manual testing: `uv run malla-web` and verify functionality works as expected
6. Commit changes ONLY after all CI checks pass and all tests pass

**CRITICAL: Never commit code that breaks existing tests. Test failures indicate broken functionality that must be debugged and fixed. The test suite exists to prevent regressions - respect it.**

**Test counts for validation:**
- Unit tests: 44 tests (must all pass)
- Integration tests: 168 tests (must all pass) 
- E2E tests: Expected to fail in sandboxed environments due to missing browser dependencies
- Total passing tests: 212+ tests required for successful validation

The codebase is well-structured with comprehensive testing. Always validate changes by running the full test suite and manually testing core functionality.
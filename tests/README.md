# Testing System for Meshtastic Mesh Health Web UI

This directory contains a comprehensive test suite for the Meshtastic Mesh Health Web UI application. The test system is designed to ensure reliability, maintainability, and correctness of all application components.

## Test Structure

```
tests/
├── __init__.py              # Test package
├── conftest.py              # Pytest configuration and fixtures
├── README.md                # This file
├── fixtures/                # Test data and database fixtures
│   ├── __init__.py
│   └── database_fixtures.py # Creates test database with known data
├── integration/             # Integration tests with test database
│   ├── __init__.py
│   └── test_api_endpoints.py # Complete API endpoint testing
└── unit/                    # Unit tests for isolated components
    ├── __init__.py
    └── test_traceroute_packet.py # TraceroutePacket class tests
```

## Test Categories

### 🔧 Unit Tests (`tests/unit/`)
- Test individual functions, classes, and methods in isolation
- No database or external dependencies required
- Fast execution, suitable for rapid development feedback
- Examples: TraceroutePacket logic, utility functions, data transformations

### 🌐 Integration Tests (`tests/integration/`)
- Test complete API endpoints with a test database
- Verify end-to-end functionality with realistic data
- Use fixture database with known test data
- Examples: API endpoint responses, database queries, data consistency

### 🚀 API Tests (marked with `@pytest.mark.api`)
- Focus specifically on API endpoint behavior
- Test request/response formats, status codes, data structures
- Verify table server-side processing
- Can run across both unit and integration test directories

## Test Database

The test suite uses a completely separate SQLite database created with realistic fixture data:

- **5 test nodes** with different roles (REPEATER, CLIENT, ROUTER, etc.)
- **120+ test packets** over the last 24 hours with various types:
  - Text messages
  - Position packets
  - Node info packets
  - Traceroute packets
- **12 traceroute scenarios** testing different path configurations
- **280+ location history records** showing node movement over 7 days

The test database is created fresh for each test session and automatically cleaned up.

## Quick Start

### 1. Install Test Dependencies

```bash
# Install test dependencies
python run_tests.py --install

# Or manually:
pip install -e .[test]
```

### 2. Check Test Environment

```bash
python run_tests.py --check
```

### 3. Run Tests

```bash
# Run all tests
python run_tests.py all -v

# Run specific test categories
python run_tests.py unit -v          # Unit tests only
python run_tests.py integration -v   # Integration tests only
python run_tests.py api -v           # API tests only

# Run with coverage report
python run_tests.py all --coverage
```

## Test Markers

Tests are organized using pytest markers:

- `@pytest.mark.unit` - Unit tests
- `@pytest.mark.integration` - Integration tests
- `@pytest.mark.api` - API-specific tests
- `@pytest.mark.slow` - Slow-running tests

Run specific test types:
```bash
pytest -m unit          # Only unit tests
pytest -m integration   # Only integration tests
pytest -m "api and not slow"  # API tests excluding slow ones
```

## Test Configuration

The test system uses pytest with these key configurations:

- **Test Discovery**: Automatically finds `test_*.py` files
- **Fixtures**: Shared test setup in `conftest.py`
- **Database Isolation**: Each test uses a fresh database
- **Coverage Reporting**: HTML and terminal coverage reports
- **Parallel Execution**: Tests can run in parallel (when supported)

## Writing New Tests

### Unit Tests Example

```python
import pytest
from your_module import your_function

class TestYourFunction:
    @pytest.mark.unit
    def test_basic_functionality(self):
        result = your_function("input")
        assert result == "expected_output"

    @pytest.mark.unit
    def test_edge_case(self):
        with pytest.raises(ValueError):
            your_function(None)
```

### Integration Tests Example

```python
import pytest

class TestAPIEndpoint:
    @pytest.mark.integration
    @pytest.mark.api
    def test_endpoint_returns_valid_data(self, client, helpers):
        response = client.get('/api/test')
        helpers.assert_api_response_structure(response, ['data', 'status'])

        data = response.get_json()
        assert data['status'] == 'success'
```

## Available Fixtures

The test system provides several useful fixtures:

### Database Fixtures
- `test_database_path` - Path to temporary test database
- `test_database` - Populated test database
- `app` - Flask application with test configuration
- `client` - Flask test client for API requests

### Data Fixtures
- `test_packet_data` - Sample packet data
- `test_traceroute_data` - Sample traceroute data
- `test_node_data` - Sample node data

### Helper Fixtures
- `helpers` - TestHelpers class with utility methods
- `runner` - Flask CLI test runner

## Coverage Reporting

Generate detailed coverage reports:

```bash
# Generate HTML coverage report
python run_tests.py coverage

# View coverage report
open htmlcov/index.html
```

The coverage report shows:
- Line-by-line code coverage
- Missing coverage highlighting
- Branch coverage analysis
- Module-level coverage summaries

## Test Data Summary

The fixture database contains:
- **5 nodes** representing different hardware and roles
- **120 regular packets** (text, position, node info)
- **12 traceroute packets** with various path scenarios
- **280 location records** showing movement patterns
- **Realistic timestamps** spanning the last 7 days

## Continuous Integration

The test suite is designed to integrate with CI/CD systems:

```yaml
# Example GitHub Actions workflow
- name: Run Tests
  run: |
    python run_tests.py --install
    python run_tests.py all --coverage

- name: Upload Coverage
  uses: codecov/codecov-action@v1
  with:
    file: ./coverage.xml
```

## Performance Considerations

- **Unit tests**: < 1 second per test
- **Integration tests**: 1-5 seconds per test
- **Full test suite**: < 2 minutes total
- **Database creation**: < 1 second

## Debugging Tests

### Run Specific Tests
```bash
# Run a specific test file
pytest tests/unit/test_traceroute_packet.py -v

# Run a specific test method
pytest tests/unit/test_traceroute_packet.py::TestTraceroutePacketBasic::test_simple_forward_traceroute -v

# Run tests matching a pattern
pytest -k "traceroute" -v
```

### Debug Mode
```bash
# Run tests with debugging output
pytest --pdb -v

# Run tests with print statements visible
pytest -s -v
```

### Test Database Inspection

The test database can be inspected during development:

```python
# In a test, add this to examine the database:
import sqlite3
conn = sqlite3.connect(test_database)
cursor = conn.cursor()
cursor.execute("SELECT COUNT(*) FROM packet_history")
print(f"Packet count: {cursor.fetchone()[0]}")
```

## Best Practices

1. **Isolate Tests**: Each test should be independent
2. **Use Fixtures**: Leverage shared setup and teardown
3. **Descriptive Names**: Test method names should describe what they test
4. **Test Edge Cases**: Include error conditions and boundary cases
5. **Mock External Dependencies**: Use mocks for external services
6. **Keep Tests Fast**: Aim for fast feedback during development

## Troubleshooting

### Common Issues

**Import Errors**: Make sure the package is installed in development mode:
```bash
pip install -e .
```

**Database Issues**: Ensure test database cleanup is working:
```bash
python run_tests.py --check
```

**Slow Tests**: Run only fast tests during development:
```bash
pytest -m "not slow" -v
```

**Coverage Issues**: Ensure all source files are included:
```bash
pytest --cov=. --cov-report=term-missing
```

### Getting Help

1. Check test logs for specific error messages
2. Run tests with `-v` flag for verbose output
3. Use `--pdb` flag to drop into debugger on failures
4. Examine the fixture database to understand test data

The test system is designed to be comprehensive, fast, and maintainable. It provides confidence in code changes and helps catch regressions early in the development process.

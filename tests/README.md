# Watch Monitor Test Suite

This directory contains a comprehensive test suite for the watch monitor application, designed to ensure reliability and maintain high code quality.

## Test Structure

The test suite is organized as follows:

```
tests/
├── conftest.py              # Shared fixtures and configuration
├── test_models.py           # Tests for WatchData and ScrapingSession models
├── test_utils.py           # Tests for utility functions
├── test_persistence.py     # Tests for data persistence layer
├── test_notifications.py   # Tests for Discord notification system
├── test_scrapers.py        # Tests for scraper implementations
├── test_monitor.py         # Integration tests for the main orchestrator
└── README.md               # This file
```

## Key Testing Features

### 🔄 Async Support
- Full support for testing async/await functions
- Proper handling of asyncio event loops
- Concurrent behavior testing

### 🎭 Comprehensive Mocking
- Mock aiohttp sessions for HTTP requests
- Mock Discord webhook responses
- Mock file I/O operations
- Mock logger instances

### 📊 High Coverage
- Targets >80% code coverage
- Tests both success and failure paths
- Edge case validation
- Error handling verification

### 🚀 Performance Testing
- Rate limiting behavior
- Concurrent scraping
- Timeout handling
- Resource cleanup

## Test Categories

### Unit Tests
- **models.py**: Data model validation, text cleaning, composite ID generation
- **utils.py**: Price parsing, year extraction, condition mapping, retry logic
- **persistence.py**: JSON file operations, data retention policies
- **notifications.py**: Discord embed formatting, webhook communication

### Integration Tests
- **scrapers.py**: HTML parsing, detail fetching, error handling
- **monitor.py**: End-to-end monitoring cycles, concurrent site scraping

## Running Tests

### Prerequisites
```bash
pip install -r requirements.txt
```

### Quick Start
```bash
# Run all tests with coverage
python3 -m pytest

# Fast run without coverage (development)
python3 run_tests.py --fast

# Run specific test file
python3 run_tests.py --file models

# Run in parallel for speed
python3 run_tests.py --parallel
```

### Test Runner Options

The `run_tests.py` script provides convenient options:

```bash
# Test selection
python3 run_tests.py --unit           # Unit tests only
python3 run_tests.py --integration    # Integration tests only
python3 run_tests.py --file test_name # Specific test file
python3 run_tests.py --test func_name # Specific test function

# Execution modes
python3 run_tests.py --parallel       # Parallel execution
python3 run_tests.py --fast           # Skip coverage for speed
python3 run_tests.py --verbose        # Detailed output

# Development helpers
python3 run_tests.py --lf             # Last failed tests only
python3 run_tests.py --exitfirst      # Stop on first failure
python3 run_tests.py --pdb            # Debug on failure
```

### Coverage Reports

Tests generate multiple coverage reports:
- **HTML**: `htmlcov/index.html` - Interactive coverage browser
- **Terminal**: Inline coverage summary
- **XML**: `coverage.xml` - For CI/CD integration

## Test Fixtures

### Key Fixtures (conftest.py)
- `temp_dir`: Temporary directory for test files
- `mock_aiohttp_session`: Mock HTTP client with configurable responses
- `mock_logger`: Mock logger for testing log output
- `sample_watch_data`: Realistic watch data for testing
- `test_site_config`: Site configuration for scraper testing

### Utility Functions
- `create_test_watch()`: Generate test watch data
- `create_test_scraping_session()`: Generate test session data
- `AsyncContextManagerMock`: Mock async context managers

## Best Practices Applied

### ✅ Test Organization
- One test class per main class/module
- Descriptive test method names
- Logical grouping of related tests

### ✅ Isolation
- Each test is independent
- Temporary files cleaned up automatically
- Mock objects reset between tests

### ✅ Real-world Scenarios
- Tests use realistic data (actual watch names, prices, URLs)
- Error conditions that occur in production
- Network timeouts and rate limiting

### ✅ Maintainability
- DRY principle with shared fixtures
- Clear test documentation
- Parameterized tests for multiple scenarios

## Common Test Patterns

### Testing Async Functions
```python
@pytest.mark.asyncio
async def test_async_function(mock_aiohttp_session):
    result = await some_async_function(mock_aiohttp_session)
    assert result is not None
```

### Mocking HTTP Responses
```python
def test_with_mock_response(mock_aiohttp_session):
    mock_aiohttp_session.get.return_value.__aenter__.return_value.status = 200
    mock_aiohttp_session.get.return_value.__aenter__.return_value.text.return_value = "response"
```

### Testing Error Handling
```python
def test_error_handling(mock_logger):
    with pytest.raises(SomeException):
        function_that_should_fail()
    mock_logger.error.assert_called()
```

## Continuous Integration

The test suite is designed for CI/CD integration:

- **Exit codes**: Proper exit codes for CI systems
- **XML reports**: Compatible with most CI platforms
- **Parallel execution**: Faster CI runs
- **Timeout handling**: Prevents hanging builds

### Example CI Configuration
```yaml
# GitHub Actions example
- name: Run tests
  run: |
    pip install -r requirements.txt
    python3 run_tests.py --parallel --no-cov
```

## Debugging Tests

### Failed Test Investigation
```bash
# Re-run only failed tests
python3 run_tests.py --lf --verbose

# Drop into debugger on failure
python3 run_tests.py --pdb --exitfirst

# Run specific failing test
python3 -m pytest tests/test_models.py::TestWatchData::test_specific_case -v -s
```

### Coverage Analysis
```bash
# Generate detailed coverage report
python3 run_tests.py --cov-html
open htmlcov/index.html
```

## Performance Considerations

The test suite is optimized for developer productivity:

- **Fast feedback**: Quick tests for development cycle
- **Parallel execution**: Utilizes multiple CPU cores
- **Smart mocking**: Avoids actual network calls
- **Efficient fixtures**: Reused across tests where appropriate

## Contributing

When adding new tests:

1. **Follow naming conventions**: `test_<function_name>_<scenario>`
2. **Add docstrings**: Explain what the test validates
3. **Use appropriate fixtures**: Reuse existing fixtures when possible
4. **Test edge cases**: Don't just test the happy path
5. **Update this README**: Document any new patterns or utilities

## Troubleshooting

### Common Issues

**Import Errors**: Ensure you're running tests from the project root directory
```bash
cd /path/to/watch_monitor_refactored
python3 -m pytest
```

**Async Warnings**: These are expected and can be ignored:
```
RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited
```

**Coverage Too Low**: Check which files need more test coverage:
```bash
python3 run_tests.py --cov-html
# Open htmlcov/index.html to see coverage details
```

**Slow Tests**: Use parallel execution or fast mode:
```bash
python3 run_tests.py --parallel --fast
```
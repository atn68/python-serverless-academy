# Python Lambda Serverless

Serverless application with idempotent payment and notification handlers.

## Requirements

- Python 3.7
- pyenv (recommended for Python version management)

## Setup

### 1. Install Python 3.7 with pyenv

```bash
pyenv install 3.7.17
pyenv local 3.7.17
```

### 2. Create and activate virtual environment (optional but recommended)

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Upgrade pip

```bash
pip install --upgrade pip
```

### 4. Install dependencies

```bash
pip install -r requirements-dev.txt
```

This installs:
- `boto3` - AWS SDK
- `pytest` - Testing framework
- `pytest-mock` - Mock fixtures for pytest
- `moto` - AWS service mocking
- `black` - Code formatter
- `ruff` - Linter
- Local packages (`idempotency-lib`, `notification-lib`)

## Running Tests

### Run all tests

```bash
pytest
```

### Run tests with verbose output

```bash
pytest -v
```

### Run specific test file

```bash
pytest tests/test_payment.py
pytest tests/test_notification.py
pytest packages/idempotency-lib/tests/test_idempotency.py
```

### Run specific test class or method

```bash
pytest tests/test_payment.py::TestPaymentHandler
pytest tests/test_payment.py::TestPaymentHandler::test_new_payment_returns_201
```

## Linting

### Run ruff linter

```bash
ruff check .
```

### Run black formatter (check mode)

```bash
black --check .
```

### Auto-format with black

```bash
black .
```

## Project Structure

```
.
├── handlers/                  # Lambda handlers
│   ├── notification.py
│   └── payment.py
├── packages/
│   ├── idempotency-lib/      # Idempotency library
│   └── notification-lib/     # Notification library
├── tests/                    # Integration tests
│   ├── test_notification.py
│   └── test_payment.py
├── requirements.txt          # Production dependencies
├── requirements-dev.txt      # Development dependencies
├── pyproject.toml           # Linting configuration
└── serverless.yml           # Serverless Framework config
```

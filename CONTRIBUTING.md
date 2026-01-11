# Contributing to KubeOpt AI

Thank you for your interest in contributing to KubeOpt AI! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please be respectful and constructive in all interactions. We're building something together.

## Getting Started

### Prerequisites

- Python 3.12+
- PostgreSQL 14+
- Prometheus (for metrics collection)
- Anthropic API key (for Claude integration)

### Development Setup

1. **Fork and clone the repository**

   ```bash
   git clone https://github.com/YOUR_USERNAME/kubeopt.git
   cd kubeopt
   ```

2. **Create a virtual environment**

   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

3. **Configure environment variables**

   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Initialize the database**

   ```bash
   # Start PostgreSQL locally or via Docker
   createdb kubeopt
   alembic upgrade head
   ```

5. **Run the application**

   ```bash
   python run.py
   ```

6. **Verify setup**

   ```bash
   curl http://localhost:5000/api/v1/health
   ```

## Development Workflow

### Branch Naming

Use these prefixes for your branches:

- `feat/` - New features
- `fix/` - Bug fixes
- `docs/` - Documentation changes
- `refactor/` - Code refactoring
- `chore/` - Maintenance tasks

Example: `feat/add-cost-alerts`

### Commit Messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add namespace budget alerts
fix: correct memory calculation for StatefulSets
docs: update API documentation
refactor: simplify metrics collector
test: add anomaly detection tests
chore: update dependencies
```

### Making Changes

1. Create a feature branch from `main`:

   ```bash
   git checkout -b feat/your-feature
   ```

2. Make your changes with clear, focused commits

3. Write or update tests for your changes

4. Ensure all tests pass:

   ```bash
   pytest tests/unit/ -v --cov=kubeopt_ai
   ```

5. Run code quality checks:

   ```bash
   ruff check .
   ruff format .
   mypy .
   ```

## Testing

### Running Tests

```bash
# All unit tests
pytest tests/unit/ -v

# With coverage
pytest tests/unit/ -v --cov=kubeopt_ai --cov-report=html

# Specific test file
pytest tests/unit/test_cost_engine.py -v

# Run tests matching a pattern
pytest -k "test_anomaly" -v
```

### Writing Tests

- Place unit tests in `tests/unit/`
- Mock external services (Prometheus, Claude API, Kubernetes)
- Target 80% coverage on new code
- Include edge cases and error scenarios

Example test structure:

```python
import pytest
from unittest.mock import Mock, patch

class TestCostEngine:
    """Tests for the cost calculation engine."""

    def test_calculate_monthly_cost_aws(self):
        """Should calculate correct monthly cost for AWS."""
        # Arrange
        engine = CostEngine(provider="aws", region="us-east-1")

        # Act
        cost = engine.calculate(cpu_cores=2, memory_gb=4)

        # Assert
        assert cost > 0
        assert isinstance(cost, float)

    @patch('kubeopt_ai.core.cost_engine.get_pricing')
    def test_handles_missing_pricing(self, mock_pricing):
        """Should handle missing pricing data gracefully."""
        mock_pricing.return_value = None
        engine = CostEngine(provider="unknown")

        with pytest.raises(PricingNotFoundError):
            engine.calculate(cpu_cores=1, memory_gb=1)
```

## Code Style

### Python

- Follow PEP 8 (enforced by Ruff)
- Use type hints for function signatures
- Write docstrings for public functions and classes
- Keep functions focused and under 50 lines when possible

### Formatting

We use Ruff for formatting and linting:

```bash
# Format code
ruff format .

# Check for issues
ruff check .

# Fix auto-fixable issues
ruff check --fix .
```

### Type Checking

```bash
mypy .
```

## Pull Request Process

1. **Update documentation** if needed (README, CHANGELOG, API docs)

2. **Ensure all checks pass**:
   - Tests: `pytest tests/unit/ -v`
   - Linting: `ruff check .`
   - Types: `mypy .`

3. **Create a pull request** with:
   - Clear title describing the change
   - Description of what and why
   - Link to related issues
   - Test plan or verification steps

4. **Address review feedback** promptly

5. **Squash commits** if requested before merge

### PR Template

```markdown
## Summary
Brief description of changes.

## Type of Change
- [ ] Bug fix
- [ ] New feature
- [ ] Documentation
- [ ] Refactoring

## Testing
- [ ] Unit tests added/updated
- [ ] Manual testing performed

## Checklist
- [ ] Code follows project style
- [ ] Tests pass locally
- [ ] Documentation updated
```

## Architecture Guidelines

### Adding New API Endpoints

1. Create route in `kubeopt_ai/routes/`
2. Define Pydantic schemas in `kubeopt_ai/core/schemas.py`
3. Implement business logic in `kubeopt_ai/core/`
4. Add tests in `tests/unit/`
5. Update OpenAPI docs if needed

### Database Changes

1. Modify models in `kubeopt_ai/core/models.py`
2. Create migration: `alembic revision -m "description" --autogenerate`
3. Review generated migration
4. Test migration: `alembic upgrade head`
5. Test rollback: `alembic downgrade -1`

## Getting Help

- **Questions**: Open a GitHub Discussion
- **Bugs**: Open a GitHub Issue with reproduction steps
- **Features**: Open a GitHub Issue describing the use case

## Recognition

Contributors are recognized in:
- Release notes
- GitHub contributor graphs
- Project documentation

Thank you for contributing!

# KubeOpt AI

**AI-Driven Kubernetes Resource & Cost Optimizer**

KubeOpt AI analyzes your Kubernetes workloads and provides intelligent recommendations for optimizing resource requests, limits, and HPA configurations using Claude AI.

## Features

- **Manifest Scanning**: Automatically parse Kubernetes Deployments, StatefulSets, DaemonSets, and HPAs
- **Metrics Collection**: Gather CPU and memory usage data from Prometheus
- **AI-Powered Analysis**: Generate optimization suggestions using Claude AI
- **Diff Generation**: Human-readable diffs showing proposed changes
- **REST API**: Simple API for triggering and retrieving optimization runs
- **Database Persistence**: Store optimization history and results in PostgreSQL

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        KubeOpt AI                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │   Scanner    │  │   Metrics    │  │     LLM      │          │
│  │  (K8s YAML)  │  │  Collector   │  │   Client     │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                  │                  │
│         └────────────┬────┴──────────────────┘                  │
│                      │                                          │
│              ┌───────┴───────┐                                  │
│              │   Optimizer   │                                  │
│              │    Service    │                                  │
│              └───────┬───────┘                                  │
│                      │                                          │
│  ┌───────────────────┴───────────────────┐                     │
│  │              Flask API                 │                     │
│  └───────────────────┬───────────────────┘                     │
│                      │                                          │
└──────────────────────┼──────────────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         │             │             │
    ┌────┴────┐  ┌─────┴─────┐  ┌────┴────┐
    │ Claude  │  │ Prometheus│  │PostgreSQL│
    │   API   │  │           │  │          │
    └─────────┘  └───────────┘  └──────────┘
```

## Quick Start

### Prerequisites

- Python 3.12+
- PostgreSQL 14+
- Prometheus (for metrics collection)
- Anthropic API key (for Claude)

### Local Development Setup

1. **Clone and setup environment**:
   ```bash
   git clone https://github.com/your-org/kubeopt-ai.git
   cd kubeopt-ai

   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

2. **Configure environment variables**:
   ```bash
   export DATABASE_URL="postgresql://kubeopt:kubeopt@localhost:5432/kubeopt"
   export PROMETHEUS_BASE_URL="http://localhost:9090"
   export LLM_API_KEY="your-anthropic-api-key"
   export FLASK_ENV="development"
   ```

3. **Initialize the database**:
   ```bash
   # Create database
   createdb kubeopt

   # Run migrations
   flask db upgrade
   ```

4. **Run the application**:
   ```bash
   # Development server
   python run.py

   # Or with Gunicorn (production-like)
   gunicorn -w 4 -b 0.0.0.0:5000 'run:app'
   ```

5. **Verify it's running**:
   ```bash
   curl http://localhost:5000/api/v1/health
   ```

## Configuration

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `DATABASE_URL` | PostgreSQL connection URL | `postgresql://kubeopt:kubeopt@localhost:5432/kubeopt` |
| `PROMETHEUS_BASE_URL` | Prometheus server URL | `http://prometheus:9090` |
| `LLM_API_KEY` | Anthropic API key | (required) |
| `LLM_MODEL_NAME` | Claude model to use | `claude-sonnet-4-20250514` |
| `KUBEOPT_DEFAULT_LOOKBACK_DAYS` | Default metrics lookback period | `7` |
| `FLASK_ENV` | Flask environment | `development` |
| `SECRET_KEY` | Flask secret key | (required in production) |
| `LOG_LEVEL` | Logging level | `INFO` |

## API Usage

### Create an Optimization Run

```bash
curl -X POST http://localhost:5000/api/v1/optimize/run \
  -H "Content-Type: application/json" \
  -d '{
    "manifest_path": "/path/to/k8s/manifests",
    "lookback_days": 7
  }'
```

Response:
```json
{
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "completed",
  "manifest_path": "/path/to/k8s/manifests",
  "lookback_days": 7,
  "summary": {
    "workload_count": 5,
    "suggestion_count": 12,
    "status": "completed"
  }
}
```

### Get Optimization Run Details

```bash
curl http://localhost:5000/api/v1/optimize/run/550e8400-e29b-41d4-a716-446655440000
```

Response includes:
- Run metadata (status, timestamps)
- Workload snapshots with current configuration
- AI-generated suggestions with reasoning
- Diff-style change summaries

### List Optimization Runs

```bash
curl "http://localhost:5000/api/v1/optimize/runs?limit=10&offset=0"
```

### Health Check

```bash
# Basic health
curl http://localhost:5000/api/v1/health

# Readiness (includes DB check)
curl http://localhost:5000/api/v1/health/ready

# Liveness
curl http://localhost:5000/api/v1/health/live
```

## Database Migrations

```bash
# Create a new migration after model changes
flask db revision -m "describe change" --autogenerate

# Apply pending migrations
flask db upgrade

# Roll back one migration
flask db downgrade -1
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=kubeopt_ai --cov-report=html

# Run specific test file
pytest tests/unit/test_k8s_scanner.py -v

# Run with verbose output
pytest -v --tb=short
```

## Kubernetes Deployment

### Build and Push Docker Image

```bash
# Build the image
docker build -t your-registry/kubeopt-ai:v1.0.0 .

# Push to registry
docker push your-registry/kubeopt-ai:v1.0.0
```

### Deploy to Kubernetes

1. **Create namespace**:
   ```bash
   kubectl apply -f k8s/namespace.yaml
   ```

2. **Create secrets** (do not use the template file directly):
   ```bash
   kubectl create secret generic kubeopt-ai-secrets \
     --namespace kubeopt \
     --from-literal=DATABASE_URL='postgresql://user:password@host:5432/kubeopt' \
     --from-literal=LLM_API_KEY='your-anthropic-api-key' \
     --from-literal=SECRET_KEY='your-flask-secret-key'
   ```

3. **Apply configurations and deployment**:
   ```bash
   kubectl apply -f k8s/configmap.yaml
   kubectl apply -f k8s/service.yaml
   kubectl apply -f k8s/deployment.yaml
   ```

4. **Optional: Configure ingress**:
   ```bash
   # Edit k8s/ingress.yaml to set your domain
   kubectl apply -f k8s/ingress.yaml
   ```

5. **Verify deployment**:
   ```bash
   kubectl -n kubeopt get pods
   kubectl -n kubeopt logs -f deployment/kubeopt-ai
   ```

## Project Structure

```
kubeopt-ai/
├── kubeopt_ai/              # Application package
│   ├── __init__.py
│   ├── app.py               # Flask app factory
│   ├── config.py            # Configuration classes
│   ├── extensions.py        # Flask extensions
│   ├── routes/              # API endpoints
│   │   ├── health.py        # Health check endpoints
│   │   └── optimize.py      # Optimization endpoints
│   ├── core/                # Business logic
│   │   ├── models.py        # SQLAlchemy models
│   │   ├── schemas.py       # Pydantic schemas
│   │   ├── k8s_scanner.py   # K8s manifest parser
│   │   ├── metrics_collector.py  # Prometheus integration
│   │   ├── optimizer_service.py  # Orchestration
│   │   └── yaml_diff.py     # Diff generation
│   └── llm/                 # LLM integration
│       ├── client.py        # Claude API client
│       └── prompts.py       # Prompt templates
├── migrations/              # Alembic migrations
├── k8s/                     # Kubernetes manifests
├── tests/                   # Test suite
├── requirements.txt
├── Dockerfile
├── run.py                   # Application entrypoint
└── README.md
```

## How It Works

1. **Scan Manifests**: The K8s scanner parses YAML files to extract workload configurations including resource requests, limits, replica counts, and HPA settings.

2. **Collect Metrics**: The metrics collector queries Prometheus for historical CPU and memory usage data (avg, p95, max) over the configured lookback period.

3. **Generate Suggestions**: The workload data and metrics are sent to Claude AI, which analyzes usage patterns and recommends optimized configurations.

4. **Create Diffs**: The diff generator produces human-readable change summaries showing current vs. proposed values with reasoning.

5. **Persist Results**: All data is stored in PostgreSQL for auditing and historical reference.

## Security Considerations

- Never commit secrets to git
- Use Kubernetes Secrets or external secret managers
- Run containers as non-root user
- Enable TLS for production deployments
- Configure rate limiting on ingress
- Validate and sanitize all inputs

## Contributing

1. Fork the repository
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Make your changes with tests
4. Run the test suite: `pytest`
5. Submit a pull request

## License

MIT License - see LICENSE file for details.

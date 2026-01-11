# Changelog

All notable changes to KubeOpt AI will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Nothing yet

## [1.0.0] - 2026-01-11

### Added

#### Core Optimization
- AI-powered optimization engine using Claude for intelligent rightsizing recommendations
- Kubernetes manifest scanner supporting Deployments, StatefulSets, DaemonSets, Jobs, and CronJobs
- Prometheus metrics collector with configurable lookback periods (avg, p95, max)
- YAML diff generation showing proposed changes in human-readable format

#### Cost Intelligence
- Cost projection engine with multi-cloud pricing (AWS, GCP, Azure, on-prem)
- Regional pricing support (us-east-1, eu-west-1, etc.)
- Per-workload and aggregate cost calculations
- Monthly and annual savings projections

#### Anomaly Detection
- Statistical analysis (Z-score, IQR, rolling averages)
- Pattern recognition for memory leaks, CPU spikes, resource drift, saturation
- Severity scoring (Low, Medium, High, Critical)
- Real-time monitoring with configurable time windows

#### Automation
- Scheduled optimization runs with cron expressions (daily, weekly, monthly)
- Auto-apply recommendations with safety guardrails
- Maximum change limits and namespace exclusions
- One-click rollback to previous configuration
- Approval workflows for large changes

#### Enterprise Features
- Multi-cluster management from single instance
- RBAC with JWT authentication
- Role-based permissions and team isolation
- Comprehensive audit logging with retention policies
- Rate limiting (configurable, default 100/hour)
- Webhook notifications (Slack, Teams, Discord, generic HTTP)

#### API & Documentation
- RESTful API with versioned endpoints (`/api/v1/`)
- OpenAPI 3.0 specification with Swagger UI (`/api/docs`)
- Health, readiness, and liveness endpoints
- Historical trends and metrics analysis

#### Infrastructure
- PostgreSQL database with SQLAlchemy ORM
- Alembic migrations
- Docker multi-stage build with non-root user
- Kubernetes deployment manifests
- Prometheus integration

### Security
- JWT-based authentication with refresh tokens
- Password hashing with secure defaults
- Input validation with Pydantic schemas
- Rate limiting protection
- Audit trail for all operations
- SSL/TLS support for cluster connections

---

[Unreleased]: https://github.com/xanthar/kubeopt/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/xanthar/kubeopt/releases/tag/v1.0.0

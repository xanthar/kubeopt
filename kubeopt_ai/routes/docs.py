"""
OpenAPI documentation routes for KubeOpt AI.

Provides Swagger UI and ReDoc documentation endpoints.
"""

import logging
from flask import Blueprint, jsonify, render_template_string

logger = logging.getLogger(__name__)

docs_bp = Blueprint("docs", __name__)


# OpenAPI 3.0 Specification
OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {
        "title": "KubeOpt AI API",
        "description": """
AI-Driven Kubernetes Resource & Cost Optimizer API.

## Features

- **Optimization Runs**: Create and manage optimization runs for K8s workloads
- **Cost Insights**: Get cost projections and anomaly detection
- **Multi-Cluster**: Manage multiple Kubernetes clusters
- **Historical Trends**: Analyze historical metrics and predict future usage
- **Real-time Monitoring**: Stream real-time metrics and alerts
- **Webhooks**: Configure notification webhooks for alerts
- **RBAC**: Role-based access control with team support

## Authentication

Most endpoints require JWT authentication. Obtain tokens via `/api/v1/auth/login`.

Include the token in the Authorization header:
```
Authorization: Bearer <token>
```
        """,
        "version": "1.0.0",
        "contact": {
            "name": "KubeOpt AI Team",
        },
        "license": {
            "name": "MIT",
        },
    },
    "servers": [
        {
            "url": "/api/v1",
            "description": "API v1",
        },
    ],
    "tags": [
        {"name": "Health", "description": "Health check endpoints"},
        {"name": "Optimization", "description": "Optimization run management"},
        {"name": "Insights", "description": "Cost and anomaly insights"},
        {"name": "Clusters", "description": "Multi-cluster management"},
        {"name": "History", "description": "Historical metrics and trends"},
        {"name": "Real-time", "description": "Real-time monitoring"},
        {"name": "Webhooks", "description": "Webhook configuration"},
        {"name": "Auth", "description": "Authentication and authorization"},
        {"name": "Audit", "description": "Audit logs"},
    ],
    "paths": {
        "/health": {
            "get": {
                "tags": ["Health"],
                "summary": "Health check",
                "description": "Check API health status",
                "responses": {
                    "200": {
                        "description": "API is healthy",
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {
                                        "status": {"type": "string", "example": "healthy"},
                                        "version": {"type": "string", "example": "1.0.0"},
                                    },
                                },
                            },
                        },
                    },
                },
            },
        },
        "/clusters": {
            "get": {
                "tags": ["Clusters"],
                "summary": "List clusters",
                "description": "List all registered Kubernetes clusters",
                "parameters": [
                    {"name": "team_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "status", "in": "query", "schema": {"type": "string", "enum": ["active", "inactive", "unreachable", "pending"]}},
                    {"name": "provider", "in": "query", "schema": {"type": "string", "enum": ["aws", "gcp", "azure", "on_prem", "other"]}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100}},
                    {"name": "offset", "in": "query", "schema": {"type": "integer", "default": 0}},
                ],
                "responses": {
                    "200": {
                        "description": "List of clusters",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ClusterList"},
                            },
                        },
                    },
                },
            },
            "post": {
                "tags": ["Clusters"],
                "summary": "Register cluster",
                "description": "Register a new Kubernetes cluster",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ClusterCreate"},
                        },
                    },
                },
                "responses": {
                    "201": {
                        "description": "Cluster created",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/Cluster"},
                            },
                        },
                    },
                    "400": {"description": "Invalid request"},
                },
            },
        },
        "/clusters/{cluster_id}": {
            "get": {
                "tags": ["Clusters"],
                "summary": "Get cluster",
                "parameters": [
                    {"name": "cluster_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
                ],
                "responses": {
                    "200": {
                        "description": "Cluster details",
                        "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Cluster"}}},
                    },
                    "404": {"description": "Cluster not found"},
                },
            },
            "put": {
                "tags": ["Clusters"],
                "summary": "Update cluster",
                "parameters": [
                    {"name": "cluster_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
                ],
                "requestBody": {
                    "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ClusterUpdate"}}},
                },
                "responses": {
                    "200": {"description": "Cluster updated"},
                    "404": {"description": "Cluster not found"},
                },
            },
            "delete": {
                "tags": ["Clusters"],
                "summary": "Delete cluster",
                "parameters": [
                    {"name": "cluster_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
                ],
                "responses": {
                    "204": {"description": "Cluster deleted"},
                    "404": {"description": "Cluster not found"},
                },
            },
        },
        "/clusters/{cluster_id}/test": {
            "post": {
                "tags": ["Clusters"],
                "summary": "Test cluster connection",
                "parameters": [
                    {"name": "cluster_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
                ],
                "responses": {
                    "200": {
                        "description": "Connection test result",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ConnectionTestResult"},
                            },
                        },
                    },
                },
            },
        },
        "/history/metrics": {
            "get": {
                "tags": ["History"],
                "summary": "Get metrics history",
                "parameters": [
                    {"name": "namespace", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "workload_name", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "container_name", "in": "query", "required": True, "schema": {"type": "string"}},
                    {"name": "cluster_id", "in": "query", "schema": {"type": "string"}},
                    {"name": "days", "in": "query", "schema": {"type": "integer", "default": 7}},
                ],
                "responses": {
                    "200": {"description": "Historical metrics"},
                },
            },
        },
        "/history/trends/analyze": {
            "post": {
                "tags": ["History"],
                "summary": "Run trend analysis",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/TrendAnalysisRequest"},
                        },
                    },
                },
                "responses": {
                    "201": {"description": "Analysis created"},
                    "400": {"description": "Insufficient data"},
                },
            },
        },
        "/optimize": {
            "post": {
                "tags": ["Optimization"],
                "summary": "Create optimization run",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/OptimizationRequest"},
                        },
                    },
                },
                "responses": {
                    "201": {"description": "Optimization run created"},
                },
            },
        },
        "/optimize/{run_id}": {
            "get": {
                "tags": ["Optimization"],
                "summary": "Get optimization run",
                "parameters": [
                    {"name": "run_id", "in": "path", "required": True, "schema": {"type": "string", "format": "uuid"}},
                ],
                "responses": {
                    "200": {"description": "Optimization run details"},
                    "404": {"description": "Run not found"},
                },
            },
        },
        "/insights/cost": {
            "post": {
                "tags": ["Insights"],
                "summary": "Calculate cost projection",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/CostRequest"},
                        },
                    },
                },
                "responses": {
                    "200": {"description": "Cost projection results"},
                },
            },
        },
        "/insights/anomalies": {
            "post": {
                "tags": ["Insights"],
                "summary": "Detect anomalies",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/AnomalyRequest"},
                        },
                    },
                },
                "responses": {
                    "200": {"description": "Anomaly detection results"},
                },
            },
        },
        "/webhooks": {
            "get": {
                "tags": ["Webhooks"],
                "summary": "List webhooks",
                "responses": {
                    "200": {"description": "List of webhooks"},
                },
            },
            "post": {
                "tags": ["Webhooks"],
                "summary": "Create webhook",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/WebhookCreate"},
                        },
                    },
                },
                "responses": {
                    "201": {"description": "Webhook created"},
                },
            },
        },
        "/auth/login": {
            "post": {
                "tags": ["Auth"],
                "summary": "Login",
                "requestBody": {
                    "required": True,
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "required": ["email", "password"],
                                "properties": {
                                    "email": {"type": "string", "format": "email"},
                                    "password": {"type": "string", "format": "password"},
                                },
                            },
                        },
                    },
                },
                "responses": {
                    "200": {"description": "Login successful, returns tokens"},
                    "401": {"description": "Invalid credentials"},
                },
            },
        },
        "/audit/logs": {
            "get": {
                "tags": ["Audit"],
                "summary": "List audit logs",
                "parameters": [
                    {"name": "action", "in": "query", "schema": {"type": "string"}},
                    {"name": "resource_type", "in": "query", "schema": {"type": "string"}},
                    {"name": "limit", "in": "query", "schema": {"type": "integer", "default": 100}},
                ],
                "responses": {
                    "200": {"description": "Audit log entries"},
                },
            },
        },
    },
    "components": {
        "schemas": {
            "Cluster": {
                "type": "object",
                "properties": {
                    "id": {"type": "string", "format": "uuid"},
                    "name": {"type": "string"},
                    "display_name": {"type": "string"},
                    "description": {"type": "string"},
                    "provider": {"type": "string", "enum": ["aws", "gcp", "azure", "on_prem", "other"]},
                    "region": {"type": "string"},
                    "status": {"type": "string", "enum": ["active", "inactive", "unreachable", "pending"]},
                    "prometheus_url": {"type": "string"},
                    "labels": {"type": "object"},
                    "created_at": {"type": "string", "format": "date-time"},
                    "updated_at": {"type": "string", "format": "date-time"},
                },
            },
            "ClusterCreate": {
                "type": "object",
                "required": ["name"],
                "properties": {
                    "name": {"type": "string"},
                    "display_name": {"type": "string"},
                    "description": {"type": "string"},
                    "provider": {"type": "string", "enum": ["aws", "gcp", "azure", "on_prem", "other"]},
                    "region": {"type": "string"},
                    "api_server_url": {"type": "string"},
                    "prometheus_url": {"type": "string"},
                    "labels": {"type": "object"},
                },
            },
            "ClusterUpdate": {
                "type": "object",
                "properties": {
                    "display_name": {"type": "string"},
                    "description": {"type": "string"},
                    "prometheus_url": {"type": "string"},
                    "labels": {"type": "object"},
                },
            },
            "ClusterList": {
                "type": "object",
                "properties": {
                    "clusters": {"type": "array", "items": {"$ref": "#/components/schemas/Cluster"}},
                    "count": {"type": "integer"},
                    "limit": {"type": "integer"},
                    "offset": {"type": "integer"},
                },
            },
            "ConnectionTestResult": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "message": {"type": "string"},
                    "kubernetes_version": {"type": "string"},
                    "prometheus_reachable": {"type": "boolean"},
                    "latency_ms": {"type": "number"},
                },
            },
            "TrendAnalysisRequest": {
                "type": "object",
                "required": ["namespace", "workload_name", "container_name"],
                "properties": {
                    "cluster_id": {"type": "string"},
                    "namespace": {"type": "string"},
                    "workload_name": {"type": "string"},
                    "container_name": {"type": "string"},
                    "days": {"type": "integer", "default": 30},
                },
            },
            "OptimizationRequest": {
                "type": "object",
                "required": ["manifest_source_path"],
                "properties": {
                    "manifest_source_path": {"type": "string"},
                    "lookback_days": {"type": "integer", "default": 7},
                    "cluster_id": {"type": "string"},
                },
            },
            "CostRequest": {
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {"type": "string", "format": "uuid"},
                    "provider": {"type": "string", "enum": ["aws", "gcp", "azure", "on_prem"]},
                    "region": {"type": "string"},
                },
            },
            "AnomalyRequest": {
                "type": "object",
                "required": ["run_id"],
                "properties": {
                    "run_id": {"type": "string", "format": "uuid"},
                    "sensitivity": {"type": "number", "default": 2.0},
                },
            },
            "WebhookCreate": {
                "type": "object",
                "required": ["name", "url"],
                "properties": {
                    "name": {"type": "string"},
                    "url": {"type": "string", "format": "uri"},
                    "webhook_type": {"type": "string", "enum": ["slack", "teams", "discord", "generic"]},
                    "severity_filter": {"type": "string"},
                },
            },
            "Error": {
                "type": "object",
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {"type": "object"},
                    "trace_id": {"type": "string"},
                },
            },
        },
        "securitySchemes": {
            "bearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
            },
        },
    },
    "security": [
        {"bearerAuth": []},
    ],
}


# Swagger UI HTML template
SWAGGER_UI_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>KubeOpt AI API - Swagger UI</title>
    <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui.css">
    <style>
        html { box-sizing: border-box; overflow-y: scroll; }
        *, *:before, *:after { box-sizing: inherit; }
        body { margin: 0; background: #fafafa; }
        .swagger-ui .topbar { display: none; }
    </style>
</head>
<body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5.9.0/swagger-ui-bundle.js"></script>
    <script>
        window.onload = function() {
            SwaggerUIBundle({
                url: "/api/docs/openapi.json",
                dom_id: '#swagger-ui',
                deepLinking: true,
                presets: [
                    SwaggerUIBundle.presets.apis,
                    SwaggerUIBundle.SwaggerUIStandalonePreset
                ],
                layout: "StandaloneLayout"
            });
        };
    </script>
</body>
</html>
"""


# ReDoc HTML template
REDOC_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>KubeOpt AI API - ReDoc</title>
    <meta charset="utf-8"/>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css?family=Montserrat:300,400,700|Roboto:300,400,700" rel="stylesheet">
    <style>
        body { margin: 0; padding: 0; }
    </style>
</head>
<body>
    <redoc spec-url='/api/docs/openapi.json'></redoc>
    <script src="https://cdn.redoc.ly/redoc/latest/bundles/redoc.standalone.js"></script>
</body>
</html>
"""


@docs_bp.route("/api/docs")
def swagger_ui():
    """Serve Swagger UI documentation."""
    return render_template_string(SWAGGER_UI_TEMPLATE)


@docs_bp.route("/api/redoc")
def redoc():
    """Serve ReDoc documentation."""
    return render_template_string(REDOC_TEMPLATE)


@docs_bp.route("/api/docs/openapi.json")
def openapi_spec():
    """Return OpenAPI specification as JSON."""
    return jsonify(OPENAPI_SPEC)

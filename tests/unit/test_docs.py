"""
Unit tests for OpenAPI documentation (F029).
"""

import pytest


class TestOpenAPIDocs:
    """Tests for OpenAPI documentation endpoints."""

    def test_swagger_ui_endpoint(self, client):
        """Test GET /api/docs returns Swagger UI."""
        response = client.get("/api/docs")

        assert response.status_code == 200
        assert b"swagger-ui" in response.data.lower()
        assert b"KubeOpt" in response.data

    def test_redoc_endpoint(self, client):
        """Test GET /api/redoc returns ReDoc UI."""
        response = client.get("/api/redoc")

        assert response.status_code == 200
        assert b"redoc" in response.data.lower()
        assert b"KubeOpt" in response.data

    def test_openapi_spec_endpoint(self, client):
        """Test GET /api/docs/openapi.json returns valid OpenAPI spec."""
        response = client.get("/api/docs/openapi.json")

        assert response.status_code == 200
        assert response.content_type == "application/json"

        data = response.get_json()

        # Validate OpenAPI structure
        assert "openapi" in data
        assert data["openapi"].startswith("3.")  # OpenAPI 3.x
        assert "info" in data
        assert "paths" in data
        assert "components" in data

    def test_openapi_spec_info(self, client):
        """Test OpenAPI spec info section."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        info = data["info"]
        assert "title" in info
        assert "KubeOpt" in info["title"]
        assert "version" in info
        assert "description" in info

    def test_openapi_spec_servers(self, client):
        """Test OpenAPI spec servers section."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        assert "servers" in data
        assert len(data["servers"]) > 0
        assert "url" in data["servers"][0]

    def test_openapi_spec_tags(self, client):
        """Test OpenAPI spec has required tags."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        assert "tags" in data
        tag_names = [t["name"] for t in data["tags"]]

        expected_tags = ["Health", "Clusters", "History", "Optimization", "Webhooks", "Auth"]
        for tag in expected_tags:
            assert tag in tag_names, f"Missing tag: {tag}"

    def test_openapi_spec_paths(self, client):
        """Test OpenAPI spec has expected paths."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        paths = data["paths"]

        # Check for key endpoints
        expected_paths = [
            "/health",
            "/clusters",
            "/clusters/{cluster_id}",
            "/history/metrics",
            "/history/trends/analyze",
            "/optimize",
            "/webhooks",
            "/auth/login",
        ]

        for path in expected_paths:
            assert path in paths, f"Missing path: {path}"

    def test_openapi_spec_cluster_operations(self, client):
        """Test OpenAPI spec has cluster CRUD operations."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        cluster_path = data["paths"]["/clusters"]
        assert "get" in cluster_path  # List
        assert "post" in cluster_path  # Create

        cluster_id_path = data["paths"]["/clusters/{cluster_id}"]
        assert "get" in cluster_id_path  # Get
        assert "put" in cluster_id_path  # Update
        assert "delete" in cluster_id_path  # Delete

    def test_openapi_spec_schemas(self, client):
        """Test OpenAPI spec has component schemas."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        schemas = data["components"]["schemas"]

        expected_schemas = [
            "Cluster",
            "ClusterCreate",
            "ClusterList",
            "ConnectionTestResult",
            "TrendAnalysisRequest",
            "Error",
        ]

        for schema in expected_schemas:
            assert schema in schemas, f"Missing schema: {schema}"

    def test_openapi_spec_cluster_schema(self, client):
        """Test Cluster schema has required properties."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        cluster_schema = data["components"]["schemas"]["Cluster"]
        properties = cluster_schema["properties"]

        expected_properties = [
            "id", "name", "provider", "status", "prometheus_url", "created_at"
        ]

        for prop in expected_properties:
            assert prop in properties, f"Missing property in Cluster schema: {prop}"

    def test_openapi_spec_security_schemes(self, client):
        """Test OpenAPI spec has security schemes."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        security_schemes = data["components"]["securitySchemes"]
        assert "bearerAuth" in security_schemes

        bearer_auth = security_schemes["bearerAuth"]
        assert bearer_auth["type"] == "http"
        assert bearer_auth["scheme"] == "bearer"
        assert bearer_auth["bearerFormat"] == "JWT"

    def test_openapi_spec_global_security(self, client):
        """Test OpenAPI spec has global security requirement."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        assert "security" in data
        assert len(data["security"]) > 0
        assert "bearerAuth" in data["security"][0]

    def test_openapi_spec_content_types(self, client):
        """Test OpenAPI spec operations use correct content types."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        # Check POST /clusters uses JSON
        post_clusters = data["paths"]["/clusters"]["post"]
        assert "requestBody" in post_clusters
        assert "application/json" in post_clusters["requestBody"]["content"]

    def test_openapi_spec_responses(self, client):
        """Test OpenAPI spec has proper response definitions."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        # Check GET /clusters/{id} responses
        get_cluster = data["paths"]["/clusters/{cluster_id}"]["get"]
        assert "responses" in get_cluster
        assert "200" in get_cluster["responses"]
        assert "404" in get_cluster["responses"]

    def test_openapi_spec_parameters(self, client):
        """Test OpenAPI spec has path parameters."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        # Check /clusters/{cluster_id} has path parameter
        get_cluster = data["paths"]["/clusters/{cluster_id}"]["get"]
        assert "parameters" in get_cluster

        param_names = [p["name"] for p in get_cluster["parameters"]]
        assert "cluster_id" in param_names

    def test_swagger_ui_loads_spec(self, client):
        """Test Swagger UI references the correct spec URL."""
        response = client.get("/api/docs")

        assert b"openapi.json" in response.data

    def test_redoc_loads_spec(self, client):
        """Test ReDoc references the correct spec URL."""
        response = client.get("/api/redoc")

        assert b"openapi.json" in response.data


class TestOpenAPISpecValidation:
    """Tests for OpenAPI spec validation."""

    def test_spec_version_valid(self, client):
        """Test OpenAPI version is valid."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        version = data["openapi"]
        assert version in ["3.0.0", "3.0.1", "3.0.2", "3.0.3", "3.1.0"]

    def test_paths_have_operations(self, client):
        """Test all paths have at least one operation."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        http_methods = ["get", "post", "put", "patch", "delete", "options", "head"]

        for path, path_item in data["paths"].items():
            operations = [m for m in http_methods if m in path_item]
            assert len(operations) > 0, f"Path {path} has no operations"

    def test_operations_have_responses(self, client):
        """Test all operations have responses defined."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        http_methods = ["get", "post", "put", "patch", "delete"]

        for path, path_item in data["paths"].items():
            for method in http_methods:
                if method in path_item:
                    operation = path_item[method]
                    assert "responses" in operation, f"{method.upper()} {path} missing responses"
                    assert len(operation["responses"]) > 0

    def test_schemas_have_types(self, client):
        """Test all schemas have type defined."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        for name, schema in data["components"]["schemas"].items():
            assert "type" in schema or "$ref" in schema, f"Schema {name} missing type"

    def test_tags_have_names(self, client):
        """Test all tags have names."""
        response = client.get("/api/docs/openapi.json")
        data = response.get_json()

        for tag in data["tags"]:
            assert "name" in tag
            assert len(tag["name"]) > 0

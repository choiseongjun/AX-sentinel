from services.incident.app.main import app


def test_incident_api_contract_is_preserved_after_layering() -> None:
    paths = app.openapi()["paths"]

    assert "post" in paths["/api/v1/telemetry"]
    assert "get" in paths["/api/v1/telemetry"]
    assert "post" in paths["/api/v1/incidents/simulate"]
    assert "get" in paths["/api/v1/incidents"]
    assert "get" in paths["/api/v1/incidents/{incident_id}"]
    assert "patch" in paths["/api/v1/incidents/{incident_id}/status"]

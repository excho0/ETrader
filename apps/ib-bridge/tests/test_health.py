from fastapi.testclient import TestClient

from app.app import create_app
from app.core.config import Settings

def test_health() -> None:
    app = create_app(Settings(env="test", auto_connect_on_startup=False, auth_enabled=False))

    with TestClient(app) as client:
        response = client.get("/api/v1/health")

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] in {"ready", "degraded"}
        assert "connected" in payload
        assert payload["target_mode"] in {"paper", "live", "auto"}
        assert "connected_mode" in payload
        assert "host" in payload
        assert "port" in payload

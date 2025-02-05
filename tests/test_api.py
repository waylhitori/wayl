
import pytest
from fastapi.testclient import TestClient
from wayl.api.main import app
from wayl.api.dependencies import get_current_user

@pytest.fixture
def client():
    return TestClient(app)

@pytest.fixture
def mock_current_user(mocker):
    user = mocker.Mock()
    user.id = str(uuid4())
    mocker.patch('wayl.api.dependencies.get_current_user', return_value=user)
    return user

class TestAgentAPI:
    def test_create_agent(self, client, mock_current_user):
        response = client.post(
            "/api/v1/agents",
            json={
                "name": "Test Agent",
                "model_id": "deepseek-7b"
            }
        )
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Test Agent"

    def test_list_agents(self, client, mock_current_user):
        response = client.get("/api/v1/agents")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    def test_chat_with_agent(self, client, mock_current_user):
        agent_id = str(uuid4())
        response = client.post(
            f"/api/v1/agents/{agent_id}/chat",
            json={"message": "Hello"}
        )
        assert response.status_code == 200
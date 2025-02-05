
import pytest
from uuid import uuid4
from wayl.core.agent import Agent
from wayl.core.model import ModelManager


class TestAgent:
    @pytest.fixture
    def agent(self):
        return Agent(
            name="Test Agent",
            model_id="deepseek-7b",
            owner_id=uuid4()
        )

    def test_agent_initialization(self, agent):
        assert agent.name == "Test Agent"
        assert agent.model_id == "deepseek-7b"
        assert agent.conversation_history == []

    def test_generate_response(self, agent, mocker):
        mock_model = mocker.patch('wayl.core.model.ModelManager.get_model')
        mock_model.return_value.generate.return_value = "Test response"

        response = agent.generate_response("Test input")
        assert response == "Test response"
        assert len(agent.conversation_history) == 2


class TestModelManager:
    def test_get_model(self, mocker):
        mocker.patch('os.environ.get', return_value="test/path")
        model = ModelManager.get_model("test-model")
        assert model.model_id == "test-model"

    def test_list_available_models(self, mocker):
        mocker.patch('os.listdir', return_value=["model1.bin", "model2.bin"])
        models = ModelManager.list_available_models()
        assert models == ["model1", "model2"]
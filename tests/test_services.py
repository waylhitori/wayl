
import pytest
from uuid import uuid4
from wayl.services.agent_service import AgentService
from wayl.services.payment_service import PaymentService


class TestAgentService:
    @pytest.fixture
    def agent_service(self):
        return AgentService()

    async def test_create_agent(self, agent_service, mocker):
        mock_crud = mocker.patch('wayl.db.crud.create_agent')
        agent_data = {
            "name": "Test Agent",
            "model_id": "deepseek-7b"
        }
        agent = await agent_service.create_agent(agent_data, uuid4())
        assert agent.name == "Test Agent"
        mock_crud.assert_called_once()


class TestPaymentService:
    @pytest.fixture
    def payment_service(self, mocker):
        mock_token = mocker.Mock()
        return PaymentService(token_client=mock_token)

    async def test_check_user_limits(self, payment_service, mocker):
        mock_get_token_info = mocker.patch.object(
            payment_service, 'get_token_info',
            return_value={"benefits": {"daily_requests": 100}}
        )
        mock_get_usage = mocker.patch(
            'wayl.db.crud.get_today_usage',
            return_value=mocker.Mock(request_count=50)
        )

        await payment_service.check_user_limits(uuid4())
        mock_get_token_info.assert_called_once()
        mock_get_usage.assert_called_once()
from typing import List, Optional, Dict
from uuid import UUID
from ..core.agent import Agent
from ..db import crud
from fastapi import HTTPException
from redis import Redis
import logging
from prometheus_client import Counter, Histogram

logger = logging.getLogger(__name__)

# Metrics
agent_creation = Counter('agent_creation_total', 'Total agent creations')
agent_deletion = Counter('agent_deletion_total', 'Total agent deletions')
response_time = Histogram('agent_response_time_seconds', 'Response generation time')


class AgentService:
    def __init__(self, redis_client: Optional[Redis] = None):
        self.redis = redis_client

    async def create_agent(
            self,
            agent_data: Dict,
            owner_id: UUID
    ) -> Agent:
        agent_creation.inc()
        try:
            token_info = await self._get_token_info(owner_id)
            current_agents = await crud.count_user_agents(owner_id)

            if current_agents >= token_info["benefits"]["max_agents"]:
                raise HTTPException(
                    status_code=403,
                    detail="Maximum agent limit reached"
                )

            agent = Agent(
                name=agent_data["name"],
                model_id=agent_data["model_id"],
                owner_id=owner_id,
                parameters=agent_data.get("parameters"),
                system_prompt=agent_data.get("system_prompt"),
                redis_client=self.redis
            )

            await crud.create_agent(agent.to_dict())
            return agent

        except Exception as e:
            logger.error(f"Agent creation failed: {str(e)}")
            raise

    async def generate_response(
            self,
            agent_id: str,
            message: str,
            user_id: UUID
    ) -> str:
        with response_time.time():
            agent = await self._get_agent(agent_id, user_id)
            conversation = await crud.get_or_create_conversation(agent_id)
            return await agent.generate_response(message, conversation.id)

    async def update_agent(
            self,
            agent_id: str,
            agent_data: Dict,
            user_id: UUID
    ) -> Agent:
        agent = await self._get_agent(agent_id, user_id)

        if "name" in agent_data:
            agent.name = agent_data["name"]
        if "system_prompt" in agent_data:
            agent.system_prompt = agent_data["system_prompt"]
        if "parameters" in agent_data:
            agent.update_parameters(agent_data["parameters"])

        await crud.update_agent(agent.id, agent.to_dict())
        return agent

    async def delete_agent(self, agent_id: str, user_id: UUID) -> bool:
        agent_deletion.inc()
        agent = await self._get_agent(agent_id, user_id)
        success = await crud.delete_agent(agent.id)

        if success and self.redis:
            await self.redis.delete(f"agent:{agent.id}")

        return success

    async def list_agents(self, user_id: UUID) -> List[Agent]:
        agents = await crud.list_user_agents(user_id)
        return [Agent(**agent_data) for agent_data in agents]

    async def _get_agent(self, agent_id: str, user_id: UUID) -> Agent:
        agent = await crud.get_agent(agent_id)
        if not agent or str(agent["owner_id"]) != str(user_id):
            raise HTTPException(status_code=404, detail="Agent not found")
        return Agent(**agent)

    async def _get_token_info(self, user_id: UUID) -> Dict:
        from ..services.payment_service import PaymentService
        payment_service = PaymentService()
        return await payment_service.get_token_info(user_id)
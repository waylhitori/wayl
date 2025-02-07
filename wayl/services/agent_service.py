from typing import List, Optional, Dict
from uuid import UUID
from ..core.agent import Agent
from ..db import crud
from fastapi import HTTPException, Depends
from redis import Redis
import logging
from prometheus_client import Counter, Histogram
from sqlalchemy.orm import Session
from ..db.database import get_db
from ..services.payment_service import PaymentService
from ..core.model import ModelManager
import asyncio
from fastapi.responses import StreamingResponse
import asyncio


logger = logging.getLogger(__name__)

# Metrics
agent_creation = Counter('agent_creation_total', 'Total agent creations')
agent_deletion = Counter('agent_deletion_total', 'Total agent deletions')
response_time = Histogram('agent_response_time_seconds', 'Response generation time')


class AgentService:
    def __init__(
            self,
            redis_client: Optional[Redis] = None,
            db: Session = Depends(get_db),
            payment_service: PaymentService = Depends()
    ):
        self.redis = redis_client
        self.db = db
        self.payment_service = payment_service
        self.model_manager = ModelManager()
        self._lock = asyncio.Lock()

    async def create_agent(
            self,
            agent_data: Dict,
            owner_id: UUID
    ) -> Agent:
        agent_creation.inc()
        try:
            token_info = await self.payment_service.get_token_info(owner_id)
            current_agents = await crud.count_user_agents(owner_id, self.db)

            if current_agents >= token_info["benefits"]["max_agents"]:
                raise HTTPException(
                    status_code=403,
                    detail="Maximum agent limit reached"
                )

            if agent_data["model_id"] not in token_info["benefits"]["model_access"]:
                raise HTTPException(
                    status_code=403,
                    detail="Selected model not available for your token level"
                )

            agent = Agent(
                name=agent_data["name"],
                model_id=agent_data["model_id"],
                owner_id=owner_id,
                parameters=agent_data.get("parameters"),
                system_prompt=agent_data.get("system_prompt"),
                redis_client=self.redis
            )

            db_agent = await crud.create_agent(agent.to_dict(), self.db)
            await self._preload_model(agent.model_id)

            return Agent(**db_agent.__dict__, redis_client=self.redis)

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
            try:
                agent = await self._get_agent(agent_id, user_id)
                await self.payment_service.check_user_limits(user_id)

                conversation = await crud.get_or_create_conversation(agent_id, self.db)
                response = await agent.generate_response(message, conversation.id)

                input_tokens = len(message.split())
                output_tokens = len(response.split())
                await self.payment_service.update_usage_metrics(
                    user_id,
                    input_tokens,
                    output_tokens
                )

                return response

            except Exception as e:
                logger.error(f"Response generation failed: {str(e)}")
                raise

    async def update_agent(
            self,
            agent_id: str,
            agent_data: Dict,
            user_id: UUID
    ) -> Agent:
        async with self._lock:
            agent = await self._get_agent(agent_id, user_id)

            update_data = {}
            if "name" in agent_data:
                update_data["name"] = agent_data["name"]
            if "system_prompt" in agent_data:
                update_data["system_prompt"] = agent_data["system_prompt"]
            if "parameters" in agent_data:
                update_data["parameters"] = {
                    **agent.parameters,
                    **agent_data["parameters"]
                }

            db_agent = await crud.update_agent(agent_id, update_data, self.db)
            return Agent(**db_agent.__dict__, redis_client=self.redis)

    async def delete_agent(
            self,
            agent_id: str,
            user_id: UUID
    ) -> bool:
        agent_deletion.inc()
        try:
            agent = await self._get_agent(agent_id, user_id)
            success = await crud.delete_agent(agent.id, self.db)

            if success and self.redis:
                async with self._lock:
                    keys = await self.redis.keys(f"agent:{agent.id}:*")
                    if keys:
                        await self.redis.delete(*keys)

            return success

        except Exception as e:
            logger.error(f"Agent deletion failed: {str(e)}")
            raise

    async def list_agents(
            self,
            user_id: UUID,
            limit: int = 50,
            offset: int = 0
    ) -> List[Agent]:
        try:
            db_agents = await crud.list_user_agents(user_id, self.db)
            return [
                Agent(**agent.__dict__, redis_client=self.redis)
                for agent in db_agents
            ]
        except Exception as e:
            logger.error(f"Listing agents failed: {str(e)}")
            raise

    async def _get_agent(
            self,
            agent_id: str,
            user_id: UUID
    ) -> Agent:
        db_agent = await crud.get_agent(agent_id, self.db)
        if not db_agent or str(db_agent.owner_id) != str(user_id):
            raise HTTPException(status_code=404, detail="Agent not found")

        return Agent(**db_agent.__dict__, redis_client=self.redis)

    async def _preload_model(self, model_id: str):
        try:
            model = await self.model_manager.get_model(model_id)
            await model.load()
        except Exception as e:
            logger.warning(f"Model preloading failed: {str(e)}")


async def generate_stream_response(
        self,
        agent_id: str,
        message: str,
        user_id: UUID
) -> StreamingResponse:
    try:
        agent = await self._get_agent(agent_id, user_id)
        await self.payment_service.check_user_limits(user_id)

        async def response_generator():
            conversation = await crud.get_or_create_conversation(agent_id, self.db)
            response_queue = asyncio.Queue()

            async def process_response():
                try:
                    response = await agent.generate_response(
                        message,
                        conversation.id,
                        stream=True,
                        response_queue=response_queue
                    )
                    await response_queue.put(None)  # Signal completion
                except Exception as e:
                    await response_queue.put(e)

            # Start processing in background
            asyncio.create_task(process_response())

            # Stream responses
            while True:
                chunk = await response_queue.get()
                if chunk is None:
                    break
                if isinstance(chunk, Exception):
                    raise chunk
                yield f"data: {chunk}\n\n"

            # Update metrics after completion
            input_tokens = len(message.split())
            output_tokens = len("".join(response_queue.get_all()))
            await self.payment_service.update_usage_metrics(
                user_id,
                input_tokens,
                output_tokens
            )

        return StreamingResponse(
            response_generator(),
            media_type="text/event-stream"
        )

    except Exception as e:
        logger.error(f"Stream response generation failed: {str(e)}")
        raise
from typing import Dict, List, Optional, Any
from uuid import UUID, uuid4
from datetime import datetime
import json
import logging
from redis import Redis
from ..core.model import ModelManager
from ..db.crud import save_message, get_conversation_history
from ..config.settings import settings

logger = logging.getLogger(__name__)


class Agent:
    def __init__(
            self,
            name: str,
            model_id: str,
            owner_id: UUID,
            parameters: Optional[Dict[str, Any]] = None,
            system_prompt: Optional[str] = None,
            redis_client: Optional[Redis] = None
    ):
        self.id = uuid4()
        self.name = name
        self.model_id = model_id
        self.owner_id = owner_id
        self.parameters = parameters or {
            "temperature": settings.TEMPERATURE,
            "top_p": settings.TOP_P,
            "max_tokens": settings.MAX_INPUT_LENGTH
        }
        self.system_prompt = system_prompt or "You are a helpful AI assistant."
        self.created_at = datetime.utcnow()
        self.last_used = None
        self.redis = redis_client
        self._model = None
        self._conversation_cache_key = f"conv:{self.id}"

    async def generate_response(
            self,
            user_input: str,
            conversation_id: Optional[str] = None
    ) -> str:
        try:
            self.last_used = datetime.utcnow()

            if not self._model:
                self._model = ModelManager.get_model(self.model_id)

            context = await self._build_context(conversation_id)

            response = await self._model.generate(
                prompt=user_input,
                system_prompt=self.system_prompt,
                context=context,
                **self.parameters
            )

            await self._save_interaction(
                conversation_id,
                user_input,
                response
            )

            return response

        except Exception as e:
            logger.error(f"Error generating response: {str(e)}")
            raise

    async def _build_context(self, conversation_id: Optional[str]) -> str:
        if not conversation_id:
            return ""

        try:
            # Try getting from cache first
            if self.redis:
                cached = await self.redis.get(
                    f"{self._conversation_cache_key}:{conversation_id}"
                )
                if cached:
                    return json.loads(cached)

            # If not in cache, get from database
            history = await get_conversation_history(
                conversation_id,
                limit=10
            )

            context = []
            for msg in history:
                context.append(f"{msg.role}: {msg.content}")

            context_str = "\n".join(context)

            # Cache the context
            if self.redis:
                await self.redis.setex(
                    f"{self._conversation_cache_key}:{conversation_id}",
                    300,  # 5 minutes
                    json.dumps(context_str)
                )

            return context_str

        except Exception as e:
            logger.error(f"Error building context: {str(e)}")
            return ""

    async def _save_interaction(
            self,
            conversation_id: str,
            user_input: str,
            response: str
    ):
        try:
            await save_message(
                conversation_id,
                "user",
                user_input
            )

            await save_message(
                conversation_id,
                "assistant",
                response
            )

            # Update cache if using Redis
            if self.redis:
                await self._update_context_cache(
                    conversation_id,
                    user_input,
                    response
                )

        except Exception as e:
            logger.error(f"Error saving interaction: {str(e)}")

    async def _update_context_cache(
            self,
            conversation_id: str,
            user_input: str,
            response: str
    ):
        key = f"{self._conversation_cache_key}:{conversation_id}"
        try:
            current = await self.redis.get(key)
            if current:
                context = json.loads(current)
                updates = f"\nuser: {user_input}\nassistant: {response}"
                new_context = context + updates
                await self.redis.setex(key, 300, json.dumps(new_context))
        except Exception as e:
            logger.error(f"Error updating context cache: {str(e)}")

    def update_parameters(self, new_parameters: Dict[str, Any]) -> None:
        self.parameters.update(new_parameters)

    def clear_history(self, conversation_id: str) -> None:
        if self.redis:
            self.redis.delete(f"{self._conversation_cache_key}:{conversation_id}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "model_id": self.model_id,
            "owner_id": str(self.owner_id),
            "parameters": self.parameters,
            "system_prompt": self.system_prompt,
            "created_at": self.created_at.isoformat(),
            "last_used": self.last_used.isoformat() if self.last_used else None
        }
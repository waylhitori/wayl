from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from typing import List, Dict, Optional
from .schemas import (
    AgentCreate, AgentResponse, TokenBalance,
    AgentUpdate, ChatRequest, ChatResponse
)
from ..services.agent_service import AgentService
from ..services.payment_service import PaymentService
from ..services.model_service import ModelService
from ..blockchain.token import WAYLToken
from .dependencies import get_current_user, get_redis, validate_token_balance
from prometheus_client import Counter, Histogram
import time
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# Metrics
request_counter = Counter('api_requests_total', 'Total API requests', ['endpoint'])
latency_histogram = Histogram('api_latency_seconds', 'API latency')


@router.post("/agents", response_model=AgentResponse)
async def create_agent(
        agent_data: AgentCreate,
        background_tasks: BackgroundTasks,
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends(),
        payment_service: PaymentService = Depends(),
        model_service: ModelService = Depends()
):
    request_counter.labels(endpoint="/agents").inc()
    start_time = time.time()

    try:
        # Validate token balance and benefits
        await validate_token_balance(current_user.id)

        # Check if model is available for user's level
        token_info = await payment_service.get_token_info(current_user.id)
        if agent_data.model_id not in token_info["benefits"]["model_access"]:
            raise HTTPException(
                status_code=403,
                detail="Model not available for your token level"
            )

        # Create agent
        agent = await agent_service.create_agent(agent_data, current_user.id)

        # Initialize model in background
        background_tasks.add_task(
            model_service.initialize_model,
            agent.model_id
        )

        latency_histogram.observe(time.time() - start_time)
        return agent

    except Exception as e:
        logger.error(f"Error creating agent: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/agents", response_model=List[AgentResponse])
async def list_agents(
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends()
):
    request_counter.labels(endpoint="/agents").inc()
    agents = await agent_service.list_agents(current_user.id)
    return agents


@router.get("/agents/{agent_id}", response_model=AgentResponse)
async def get_agent(
        agent_id: str,
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends()
):
    agent = await agent_service.get_agent(agent_id, current_user.id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.post("/agents/{agent_id}/chat", response_model=ChatResponse)
async def chat_with_agent(
        agent_id: str,
        request: ChatRequest,
        background_tasks: BackgroundTasks,
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends(),
        payment_service: PaymentService = Depends(),
        redis=Depends(get_redis)
):
    request_counter.labels(endpoint="/agents/chat").inc()
    start_time = time.time()

    try:
        # Check rate limits and token balance
        await payment_service.check_user_limits(current_user.id)

        # Generate response
        response = await agent_service.generate_response(
            agent_id,
            request.message,
            current_user.id
        )

        # Update usage metrics in background
        background_tasks.add_task(
            payment_service.update_usage_metrics,
            current_user.id,
            len(request.message),
            len(response)
        )

        latency_histogram.observe(time.time() - start_time)
        return {"response": response}

    except Exception as e:
        logger.error(f"Error in chat: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/agents/{agent_id}", response_model=AgentResponse)
async def update_agent(
        agent_id: str,
        agent_data: AgentUpdate,
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends()
):
    updated_agent = await agent_service.update_agent(
        agent_id,
        agent_data,
        current_user.id
    )
    if not updated_agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return updated_agent


@router.delete("/agents/{agent_id}")
async def delete_agent(
        agent_id: str,
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends()
):
    success = await agent_service.delete_agent(agent_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "success"}


@router.get("/token/balance", response_model=TokenBalance)
async def get_token_balance(
        current_user=Depends(get_current_user),
        payment_service: PaymentService = Depends()
):
    return await payment_service.get_token_info(current_user.id)


@router.get("/models")
async def list_available_models(
        current_user=Depends(get_current_user),
        model_service: ModelService = Depends(),
        payment_service: PaymentService = Depends()
):
    token_info = await payment_service.get_token_info(current_user.id)
    available_models = model_service.list_models()

    return {
        "available_models": [
            model for model in available_models
            if model in token_info["benefits"]["model_access"]
        ]
    }
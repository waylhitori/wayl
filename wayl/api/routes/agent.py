from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query
from typing import List, Optional
from ...services.agent_service import AgentService
from ...services.payment_service import PaymentService
from ...core.security import SecurityManager
from ..dependencies import get_current_user
from ..schemas.agent import (
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    ChatRequest,
    ChatResponse,
    AgentListResponse
)
from sqlalchemy.orm import Session
from ...db.database import get_db

router = APIRouter(prefix="/agents", tags=["Agents"])


@router.post("", response_model=AgentResponse)
async def create_agent(
        agent_data: AgentCreate,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends(),
        payment_service: PaymentService = Depends()
):
    await payment_service.check_user_limits(current_user.id)
    token_info = await payment_service.get_token_info(current_user.id)

    if agent_data.model_id not in token_info["benefits"]["model_access"]:
        raise HTTPException(
            status_code=403,
            detail="Model not available for your token level"
        )

    agent = await agent_service.create_agent(agent_data, current_user.id)
    background_tasks.add_task(agent_service._preload_model, agent.model_id)
    return agent


@router.get("", response_model=AgentListResponse)
async def list_agents(
        offset: int = Query(0, ge=0),
        limit: int = Query(10, ge=1, le=100),
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends()
):
    agents = await agent_service.list_agents(
        user_id=current_user.id,
        limit=limit,
        offset=offset
    )
    total = await agent_service.get_total_agents(current_user.id)

    return {
        "items": agents,
        "total": total,
        "offset": offset,
        "limit": limit
    }


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(
        agent_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends()
):
    agent = await agent_service._get_agent(agent_id, current_user.id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
        agent_id: str,
        agent_data: AgentUpdate,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends()
):
    updated_agent = await agent_service.update_agent(
        agent_id,
        agent_data,
        current_user.id
    )
    return updated_agent


@router.delete("/{agent_id}")
async def delete_agent(
        agent_id: str,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends()
):
    success = await agent_service.delete_agent(agent_id, current_user.id)
    if not success:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {"status": "success"}


@router.post("/{agent_id}/chat", response_model=ChatResponse)
async def chat_with_agent(
        agent_id: str,
        request: ChatRequest,
        background_tasks: BackgroundTasks,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends(),
        payment_service: PaymentService = Depends()
):
    await payment_service.check_user_limits(current_user.id)

    response = await agent_service.generate_response(
        agent_id,
        request.message,
        current_user.id
    )

    background_tasks.add_task(
        payment_service.update_usage_metrics,
        current_user.id,
        len(request.message),
        len(response)
    )

    return {
        "response": response,
        "usage": {
            "prompt_tokens": len(request.message),
            "completion_tokens": len(response),
            "total_tokens": len(request.message) + len(response)
        }
    }


@router.post("/{agent_id}/stream-chat")
async def stream_chat_with_agent(
        agent_id: str,
        request: ChatRequest,
        db: Session = Depends(get_db),
        current_user=Depends(get_current_user),
        agent_service: AgentService = Depends(),
        payment_service: PaymentService = Depends()
):
    await payment_service.check_user_limits(current_user.id)

    return await agent_service.generate_stream_response(
        agent_id,
        request.message,
        current_user.id
    )
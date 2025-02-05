
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from datetime import datetime, date
from .models import User, Agent, Conversation, Message, UsageRecord
from uuid import UUID


async def get_user(user_id: UUID, db: Session) -> Optional[User]:
    return db.query(User).filter(User.id == str(user_id)).first()


async def create_agent(agent_data: dict, db: Session) -> Agent:
    agent = Agent(**agent_data)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


async def get_agent(agent_id: str, db: Session) -> Optional[Agent]:
    return db.query(Agent).filter(Agent.id == agent_id).first()


async def list_user_agents(user_id: UUID, db: Session) -> List[Agent]:
    return db.query(Agent).filter(Agent.owner_id == str(user_id)).all()


async def get_or_create_conversation(agent_id: str, db: Session) -> Conversation:
    conversation = db.query(Conversation).filter(
        Conversation.agent_id == agent_id
    ).order_by(
        Conversation.created_at.desc()
    ).first()

    if not conversation:
        conversation = Conversation(agent_id=agent_id)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)

    return conversation


async def save_message(
        conversation_id: str,
        role: str,
        content: str,
        db: Session
) -> Message:
    message = Message(
        conversation_id=conversation_id,
        role=role,
        content=content
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


async def get_today_usage(user_id: UUID, db: Session) -> UsageRecord:
    today = date.today()
    record = db.query(UsageRecord).filter(
        and_(
            UsageRecord.user_id == str(user_id),
            func.date(UsageRecord.date) == today
        )
    ).first()

    if not record:
        record = UsageRecord(user_id=str(user_id))
        db.add(record)
        db.commit()
        db.refresh(record)

    return record


async def update_usage_record(
        user_id: UUID,
        tokens_used: int,
        db: Session
) -> UsageRecord:
    record = await get_today_usage(user_id, db)
    record.request_count += 1
    record.tokens_used += tokens_used
    db.commit()
    db.refresh(record)
    return record


async def get_conversation_history(
        conversation_id: str,
        db: Session,
        limit: int = 50
) -> List[Message]:
    return db.query(Message).filter(
        Message.conversation_id == conversation_id
    ).order_by(
        Message.created_at.desc()
    ).limit(limit).all()
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from sqlalchemy import and_, func
from datetime import datetime, date
from .models import User, Agent, Conversation, Message, UsageRecord, PaymentRecord
from uuid import UUID

async def get_user(user_id: UUID, db: Session) -> Optional[User]:
    return db.query(User).filter(User.id == str(user_id)).first()

async def get_user_by_username(username: str, db: Session) -> Optional[User]:
    return db.query(User).filter(User.username == username).first()

async def create_agent(agent_data: Dict, db: Session) -> Agent:
    agent = Agent(**agent_data)
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent

async def get_agent(agent_id: str, db: Session) -> Optional[Agent]:
    return db.query(Agent).filter(Agent.id == agent_id).first()

async def list_user_agents(user_id: UUID, db: Session) -> List[Agent]:
    return db.query(Agent).filter(Agent.owner_id == str(user_id)).all()

async def count_user_agents(user_id: UUID, db: Session) -> int:
    return db.query(Agent).filter(Agent.owner_id == str(user_id)).count()

async def create_payment_record(
    user_id: UUID,
    amount: float,
    tx_hash: str,
    description: str,
    db: Session
) -> PaymentRecord:
    record = PaymentRecord(
        user_id=str(user_id),
        amount=amount,
        tx_hash=tx_hash,
        description=description
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record

async def get_user_payment_records(
    user_id: UUID,
    db: Session,
    limit: int = 50,
    offset: int = 0
) -> List[PaymentRecord]:
    return db.query(PaymentRecord)\
        .filter(PaymentRecord.user_id == str(user_id))\
        .order_by(PaymentRecord.created_at.desc())\
        .offset(offset)\
        .limit(limit)\
        .all()

async def get_or_create_conversation(
    agent_id: str,
    db: Session
) -> Conversation:
    conversation = db.query(Conversation)\
        .filter(Conversation.agent_id == agent_id)\
        .order_by(Conversation.created_at.desc())\
        .first()

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
    return db.query(Message)\
        .filter(Message.conversation_id == conversation_id)\
        .order_by(Message.created_at.desc())\
        .limit(limit)\
        .all()


async def update_agent(agent_id: str, update_data: Dict, db: Session) -> Optional[Agent]:
    agent = db.query(Agent).filter(Agent.id == agent_id)
    if not agent.first():
        return None

    agent.update(update_data)
    db.commit()
    return agent.first()


async def delete_agent(agent_id: str, db: Session) -> bool:
    agent = db.query(Agent).filter(Agent.id == agent_id).first()
    if not agent:
        return False

    db.delete(agent)
    db.commit()
    return True


async def get_user_by_email(email: str, db: Session) -> Optional[User]:
    return db.query(User).filter(User.email == email).first()


async def update_user(user_id: UUID, update_data: Dict, db: Session) -> Optional[User]:
    user = db.query(User).filter(User.id == str(user_id))
    if not user.first():
        return None

    user.update(update_data)
    db.commit()
    return user.first()


async def get_user_by_token(token: str, db: Session) -> Optional[User]:
    try:
        from ..core.security import SecurityManager
        security = SecurityManager()
        payload = await security.verify_token(token)
        if not payload:
            return None

        user_id = payload.get("sub")
        if not user_id:
            return None

        return await get_user(UUID(user_id), db)
    except Exception:
        return None
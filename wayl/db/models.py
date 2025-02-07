from sqlalchemy import Column, Integer, String, ForeignKey, DateTime, JSON, Float
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

Base = declarative_base()

class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    username = Column(String, unique=True, index=True)
    email = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    wallet_address = Column(String, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    agents = relationship("Agent", back_populates="owner")
    usage_records = relationship("UsageRecord", back_populates="user")
    payments = relationship("PaymentRecord", back_populates="user")
    audit_logs = relationship("AuditLog", back_populates="user")

class PaymentRecord(Base):
    __tablename__ = "payment_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    amount = Column(Float)
    tx_hash = Column(String, unique=True)
    description = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String, default="completed")  # pending, completed, failed

    user = relationship("User", back_populates="payments")

class Agent(Base):
    __tablename__ = "agents"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String)
    model_id = Column(String)
    owner_id = Column(String, ForeignKey("users.id"))
    system_prompt = Column(String)
    parameters = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used = Column(DateTime)

    owner = relationship("User", back_populates="agents")
    conversations = relationship("Conversation", back_populates="agent")

class Conversation(Base):
    __tablename__ = "conversations"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id = Column(String, ForeignKey("agents.id"))
    created_at = Column(DateTime, default=datetime.utcnow)

    agent = relationship("Agent", back_populates="conversations")
    messages = relationship("Message", back_populates="conversation")

class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, ForeignKey("conversations.id"))
    role = Column(String)  # "user" or "assistant"
    content = Column(String)
    created_at = Column(DateTime, default=datetime.utcnow)

    conversation = relationship("Conversation", back_populates="messages")

class UsageRecord(Base):
    __tablename__ = "usage_records"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id"))
    date = Column(DateTime, default=datetime.utcnow)
    request_count = Column(Integer, default=0)
    tokens_used = Column(Integer, default=0)

    user = relationship("User", back_populates="usage_records")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    timestamp = Column(DateTime, default=datetime.utcnow)
    event_type = Column(String, index=True)
    user_id = Column(String, ForeignKey("users.id"), index=True)
    resource_type = Column(String, index=True)
    resource_id = Column(String, index=True)
    action = Column(String)
    status = Column(String)
    details = Column(JSON)
    ip_address = Column(String)
    user_agent = Column(String)

    user = relationship("User", back_populates="audit_logs")
from pydantic import BaseModel, Field, validator
from typing import Dict, Optional, List, Any
from datetime import datetime
from uuid import UUID

class AgentCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    model_id: str
    system_prompt: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None

    @validator('parameters')
    def validate_parameters(cls, v):
        if v is None:
            return {}
        allowed_keys = {'temperature', 'top_p', 'max_tokens', 'frequency_penalty', 'presence_penalty'}
        invalid_keys = set(v.keys()) - allowed_keys
        if invalid_keys:
            raise ValueError(f"Invalid parameters: {invalid_keys}")
        return v

class AgentUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    system_prompt: Optional[str] = None
    parameters: Optional[Dict[str, Any]] = None

class AgentResponse(BaseModel):
    id: UUID
    name: str
    model_id: str
    owner_id: UUID
    system_prompt: Optional[str]
    parameters: Dict[str, Any]
    created_at: datetime
    last_used: Optional[datetime]

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4096)
    context_id: Optional[str] = None
    stream: bool = False

class ChatResponse(BaseModel):
    response: str
    usage: Dict[str, int]
    finish_reason: str

class TokenBalance(BaseModel):
    address: str
    balance: float
    level: int
    benefits: Dict[str, Any]
    daily_usage: Dict[str, int]

class PaymentRequest(BaseModel):
    amount: float = Field(..., gt=0)
    description: str = Field(..., min_length=1, max_length=200)

class PaymentResponse(BaseModel):
    transaction_hash: str
    status: str
    timestamp: datetime

class ModelInfo(BaseModel):
    id: str
    name: str
    parameters: Dict[str, Any]
    supported_features: List[str]
    max_tokens: int
    token_cost: float

class ErrorResponse(BaseModel):
    detail: str
    code: str
    params: Optional[Dict[str, Any]] = None
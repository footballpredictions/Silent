import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class HiveCellCreateManual(BaseModel):
    """Ручное добавление соты (без cell-agent)."""
    name: str = Field(..., min_length=1, max_length=128)
    public_ip: str = Field(..., min_length=3, max_length=255)
    wg_public_key: str = Field(..., min_length=40, max_length=512)
    wdtt_port: int = Field(default=56000, ge=1, le=65535)
    wg_port: int = Field(default=56001, ge=1, le=65535)
    max_clients: int = Field(default=100, ge=1, le=10000)
    priority: int = Field(default=100, ge=0, le=1000)
    tunnel_api_url: Optional[str] = Field(default=None, max_length=512)


class HiveCellAutoConnect(BaseModel):
    """Автоподключение соты: SSH root — всё настраивается само."""
    host: str = Field(..., min_length=3, max_length=255, description="Публичный IP нового VPS")
    password: str = Field(..., min_length=4, max_length=256, description="SSH-пароль root")
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)


class HiveCellCreateAgent(BaseModel):
    """Подключение соты через cell-agent (API + пароль)."""
    name: str = Field(..., min_length=1, max_length=128)
    api_url: str = Field(..., min_length=8, max_length=512)
    password: str = Field(..., min_length=8, max_length=256)
    max_clients: int = Field(default=100, ge=1, le=10000)
    priority: int = Field(default=100, ge=0, le=1000)

    @field_validator("api_url")
    @classmethod
    def normalize_api_url(cls, v: str) -> str:
        return v.strip().rstrip("/")


class HiveCellSshRepair(BaseModel):
    password: str = Field(..., min_length=4, max_length=256, description="SSH-пароль root соты")


class HiveCellUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    max_clients: Optional[int] = Field(default=None, ge=1, le=10000)
    priority: Optional[int] = Field(default=None, ge=0, le=1000)
    status: Optional[str] = Field(default=None, pattern="^(active|draining|offline)$")
    wg_public_key: Optional[str] = Field(default=None, min_length=40, max_length=512)
    public_ip: Optional[str] = Field(default=None, min_length=3, max_length=255)


class HiveCellResponse(BaseModel):
    id: uuid.UUID
    name: str
    is_queen: bool
    public_ip: str
    wdtt_port: int
    wg_port: int
    wg_public_key: str
    api_url: Optional[str]
    has_agent: bool
    tunnel_api_url: Optional[str]
    max_clients: int
    online_count: int
    assigned_devices: int
    status: str
    priority: int
    last_seen_at: Optional[datetime]
    last_error: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}

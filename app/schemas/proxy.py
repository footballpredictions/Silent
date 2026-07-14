"""Схемы админки прокси-флота."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class ProxyNodeConnect(BaseModel):
    host: str = Field(..., min_length=3, max_length=255)
    password: str = Field(..., min_length=4, max_length=256)
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    ssh_port: int = Field(default=22, ge=1, le=65535)
    # dedicated | attached (на сервере уже есть сервисы — только safe remove proxy)
    role: str = Field(default="attached", max_length=32)
    # Если задан — стараемся сохранить этот SOCKS-порт (cutover для сайта)
    prefer_socks_port: Optional[int] = Field(default=None, ge=1, le=65535)


class ProxyNodePatch(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    status: Optional[str] = Field(default=None, max_length=32)
    is_primary: Optional[bool] = None
    priority: Optional[int] = Field(default=None, ge=0, le=10000)

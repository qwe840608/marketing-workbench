from typing import Literal

from pydantic import BaseModel, Field


class ClientRegistration(BaseModel):
    client_name: str = Field(default="Agent", max_length=300)
    redirect_uris: list[str] = Field(min_length=1, max_length=10)
    token_endpoint_auth_method: str = "none"
    grant_types: list[str] = Field(default_factory=lambda: ["authorization_code", "refresh_token"])
    response_types: list[str] = Field(default_factory=lambda: ["code"])


class AuthorizationParams(BaseModel):
    client_id: str = Field(max_length=80)
    response_type: str = Field(max_length=30)
    redirect_uri: str = Field(max_length=2048)
    code_challenge: str = Field(max_length=128)
    code_challenge_method: str = Field(max_length=30)
    state: str = Field(min_length=1, max_length=2048)
    resource: str | None = Field(default=None, max_length=2048)
    scope: str | None = Field(default=None, max_length=100)


class ApprovalDecision(BaseModel):
    request_id: str = Field(min_length=43, max_length=43)
    approve: bool


class ConnectionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class ConnectionView(BaseModel):
    id: int
    name: str
    kind: Literal["oauth", "token"]

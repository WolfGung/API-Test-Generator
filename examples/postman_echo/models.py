"""Models for postman-echo.postman_collection.json: one class per named schema, used to validate response bodies."""

from __future__ import annotations

from pydantic import BaseModel


class DigestAuthSuccessResponse(BaseModel):
    """DigestAuthSuccessResponse"""

    authenticated: bool


class BasicAuthResponse(BaseModel):
    """BasicAuthResponse"""

    authenticated: bool


class SetCookiesResponse(BaseModel):
    """SetCookiesResponse"""

    cookies: SetCookiesResponseCookies


class GetCookiesResponse(BaseModel):
    """GetCookiesResponse"""

    cookies: GetCookiesResponseCookies


class DeleteCookiesResponse(BaseModel):
    """DeleteCookiesResponse"""

    cookies: DeleteCookiesResponseCookies


class Oauth20GetAccessTokenResponse(BaseModel):
    """Oauth20GetAccessTokenResponse"""

    access_token: str
    token_type: str


class Oauth20GetResourceResponse(BaseModel):
    """Oauth20GetResourceResponse"""

    user_id: int
    name: str


class SetCookiesResponseCookies(BaseModel):
    """SetCookiesResponseCookies"""

    foo1: str
    foo2: str


class GetCookiesResponseCookies(BaseModel):
    """GetCookiesResponseCookies"""

    foo2: str


class DeleteCookiesResponseCookies(BaseModel):
    """DeleteCookiesResponseCookies"""

    foo2: str


for _model in (
    DigestAuthSuccessResponse,
    BasicAuthResponse,
    SetCookiesResponse,
    GetCookiesResponse,
    DeleteCookiesResponse,
    Oauth20GetAccessTokenResponse,
    Oauth20GetResourceResponse,
    SetCookiesResponseCookies,
    GetCookiesResponseCookies,
    DeleteCookiesResponseCookies,
):
    _model.model_rebuild()

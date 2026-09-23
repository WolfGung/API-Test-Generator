"""Models for petstore-openapi3.json: one class per named schema, used to validate response bodies."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Order(BaseModel):
    """Order"""

    model_config = ConfigDict(populate_by_name=True)

    id: int | None = None
    pet_id: int | None = Field(default=None, alias="petId")
    quantity: int | None = None
    ship_date: str | None = Field(default=None, alias="shipDate")
    status: Literal["placed", "approved", "delivered"] | None = None
    complete: bool | None = None


class Category(BaseModel):
    """Category"""

    id: int | None = None
    name: str | None = None


class User(BaseModel):
    """User"""

    model_config = ConfigDict(populate_by_name=True)

    id: int | None = None
    username: str | None = None
    first_name: str | None = Field(default=None, alias="firstName")
    last_name: str | None = Field(default=None, alias="lastName")
    email: str | None = None
    password: str | None = None
    phone: str | None = None
    user_status: int | None = Field(default=None, alias="userStatus")


class Tag(BaseModel):
    """Tag"""

    id: int | None = None
    name: str | None = None


class Pet(BaseModel):
    """Pet"""

    model_config = ConfigDict(populate_by_name=True)

    id: int | None = None
    name: str
    category: Category | None = None
    photo_urls: list[str] = Field(alias="photoUrls")
    tags: list[Tag] | None = None
    status: Literal["available", "pending", "sold"] | None = None


class ApiResponse(BaseModel):
    """ApiResponse"""

    code: int | None = None
    type: str | None = None
    message: str | None = None


FindPetsByStatusResponse = list[Pet]


FindPetsByTagsResponse = list[Pet]


GetInventoryResponse = dict[str, int]


CreateUsersWithListInputRequest = list[User]


LoginUserResponse = str


for _model in (Order, Category, User, Tag, Pet, ApiResponse,):
    _model.model_rebuild()

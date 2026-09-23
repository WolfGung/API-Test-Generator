"""Models for openapi.json: one class per named schema, used to validate response bodies."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


class Author(BaseModel):
    """Author"""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str
    born: int | None = None


class Book(BaseModel):
    """Book"""

    model_config = ConfigDict(extra="forbid")

    title: str
    author_id: int
    year: int
    tags: list[str] | None = None
    id: int


class BookIn(BaseModel):
    """BookIn"""

    title: str
    author_id: int
    year: int
    tags: list[str] | None = None


class HTTPValidationError(BaseModel):
    """HTTPValidationError"""

    detail: list[ValidationError] | None = None


class Health(BaseModel):
    """Health"""

    status: str
    books: int


class Loan(BaseModel):
    """Loan"""

    model_config = ConfigDict(extra="forbid")

    id: int
    book_id: int
    reader: str


class LoanIn(BaseModel):
    """LoanIn"""

    book_id: int


class ValidationError(BaseModel):
    """ValidationError"""

    loc: list[str | int]
    msg: str
    type: str
    input: Any | None = None
    ctx: dict[str, Any] | None = None


ListAuthorsResponse = list[Author]


ListBooksResponse = list[Book]


SearchBooksResponse = list[Book]


for _model in (Author, Book, BookIn, HTTPValidationError, Health, Loan, LoanIn, ValidationError,):
    _model.model_rebuild()

"""Models for bookshelf.postman_collection.json: one class per named schema, used to validate response bodies."""

from __future__ import annotations

from pydantic import BaseModel


class LivenessAndHowManyBooksAreOnTheShelfResponse(BaseModel):
    """LivenessAndHowManyBooksAreOnTheShelfResponse"""

    status: str
    books: int


class OneAuthorResponse(BaseModel):
    """OneAuthorResponse"""

    id: int
    name: str
    born: int


class AddABookRequest(BaseModel):
    """AddABookRequest"""

    title: str | None = None
    author_id: int | None = None
    year: int | None = None
    tags: list[str] | None = None


class AddABookResponse(BaseModel):
    """AddABookResponse"""

    title: str
    author_id: int
    year: int
    tags: list[str]
    id: int


class OneBookResponse(BaseModel):
    """OneBookResponse"""

    title: str
    author_id: int
    year: int
    tags: list[str]
    id: int


class ReplaceABookRequest(BaseModel):
    """ReplaceABookRequest"""

    title: str | None = None
    author_id: int | None = None
    year: int | None = None
    tags: list[str] | None = None


class ReplaceABookResponse(BaseModel):
    """ReplaceABookResponse"""

    title: str
    author_id: int
    year: int
    tags: list[str]
    id: int


class LendABookToTheReaderInXReaderRequest(BaseModel):
    """LendABookToTheReaderInXReaderRequest"""

    book_id: int | None = None


class LendABookToTheReaderInXReaderResponse(BaseModel):
    """LendABookToTheReaderInXReaderResponse"""

    id: int
    book_id: int
    reader: str


class AllAuthorsResponseItem(BaseModel):
    """AllAuthorsResponseItem"""

    id: int
    name: str
    born: int


class BooksOptionallyThoseOfOneAuthorResponseItem(BaseModel):
    """BooksOptionallyThoseOfOneAuthorResponseItem"""

    title: str
    author_id: int
    year: int
    tags: list[str]
    id: int


class BooksWhoseTitleContainsAPhraseResponseItem(BaseModel):
    """BooksWhoseTitleContainsAPhraseResponseItem"""

    title: str
    author_id: int
    year: int
    tags: list[str]
    id: int


AllAuthorsResponse = list[AllAuthorsResponseItem]


BooksOptionallyThoseOfOneAuthorResponse = list[BooksOptionallyThoseOfOneAuthorResponseItem]


BooksWhoseTitleContainsAPhraseResponse = list[BooksWhoseTitleContainsAPhraseResponseItem]


for _model in (
    LivenessAndHowManyBooksAreOnTheShelfResponse,
    OneAuthorResponse,
    AddABookRequest,
    AddABookResponse,
    OneBookResponse,
    ReplaceABookRequest,
    ReplaceABookResponse,
    LendABookToTheReaderInXReaderRequest,
    LendABookToTheReaderInXReaderResponse,
    AllAuthorsResponseItem,
    BooksOptionallyThoseOfOneAuthorResponseItem,
    BooksWhoseTitleContainsAPhraseResponseItem,
):
    _model.model_rebuild()

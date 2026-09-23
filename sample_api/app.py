"""Bookshelf: a small library API the generated suites are proven against.

Three authors and five books are seeded when the process starts. Books can be
listed, searched, read, added, replaced and removed; a loan lends a book to the
reader named in the X-Reader header. Everything that changes the shelf needs
the bearer token SAMPLE_API_TOKEN (default "sample-token").

Two choices keep a generated suite green in any order and on a second run
against the same process: DELETE is idempotent (removing a book that is not
there is still 204), and the examples the document carries never point at a
book another operation removes.
"""

from __future__ import annotations

import os
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Path, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field

TOKEN = os.environ.get("SAMPLE_API_TOKEN", "sample-token")


class Author(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(examples=[1])
    name: str = Field(examples=["Ursula K. Le Guin"])
    born: int | None = Field(default=None, examples=[1929])


class BookIn(BaseModel):
    title: str = Field(min_length=1, examples=["The Dispossessed"])
    author_id: int = Field(examples=[1])
    year: int = Field(ge=1450, le=2100, examples=[1974])
    tags: list[str] = Field(default_factory=list, examples=[["novel", "utopia"]])


class Book(BookIn):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(examples=[1])


class LoanIn(BaseModel):
    book_id: int = Field(examples=[1])


class Loan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int = Field(examples=[1])
    book_id: int = Field(examples=[1])
    reader: str = Field(examples=["reader-42"])


class Health(BaseModel):
    status: str = Field(examples=["ok"])
    books: int = Field(examples=[5])


SEED_AUTHORS = (
    Author(id=1, name="Ursula K. Le Guin", born=1929),
    Author(id=2, name="Stanisław Lem", born=1921),
    Author(id=3, name="Octavia E. Butler", born=1947),
)
SEED_BOOKS = (
    Book(id=1, title="The Dispossessed", author_id=1, year=1974, tags=["novel", "utopia"]),
    Book(id=2, title="The Left Hand of Darkness", author_id=1, year=1969, tags=["novel"]),
    Book(id=3, title="Solaris", author_id=2, year=1961, tags=["novel"]),
    Book(id=4, title="The Cyberiad", author_id=2, year=1965, tags=["stories"]),
    Book(id=5, title="Kindred", author_id=3, year=1979, tags=["novel"]),
)


class Store:
    def __init__(self) -> None:
        self.authors = {author.id: author for author in SEED_AUTHORS}
        self.books = {book.id: book.model_copy() for book in SEED_BOOKS}
        self.loans: dict[int, Loan] = {}
        self.next_book = max(self.books) + 1
        self.next_loan = 1


store = Store()
bearer = HTTPBearer(auto_error=False)


def require_token(credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> None:
    if credentials is None or credentials.credentials != TOKEN:
        raise HTTPException(
            status_code=401, detail="a bearer token is required", headers={"WWW-Authenticate": "Bearer"}
        )


app = FastAPI(
    title="Bookshelf",
    version="1.0.0",
    description="A small library API: authors, books and loans.",
    # operationId is the function name (list_books), not FastAPI's default (list_books_books_get), so the
    # generated tests are called test_list_books.
    generate_unique_id_function=lambda route: route.name,
)
NOT_FOUND = {404: {"description": "Not found"}}
UNAUTHORIZED = {401: {"description": "The bearer token is missing or wrong"}}


@app.get("/health", response_model=Health, tags=["health"], summary="Liveness, and how many books are on the shelf")
def health() -> Health:
    return Health(status="ok", books=len(store.books))


@app.get("/authors", response_model=list[Author], tags=["authors"], summary="All authors")
def list_authors() -> list[Author]:
    return list(store.authors.values())


@app.get("/authors/{author_id}", response_model=Author, tags=["authors"], summary="One author", responses=NOT_FOUND)
def get_author(author_id: Annotated[int, Path(examples=[1])]) -> Author:
    if author_id not in store.authors:
        raise HTTPException(status_code=404, detail="no such author")
    return store.authors[author_id]


@app.get("/books", response_model=list[Book], tags=["books"], summary="Books, optionally those of one author")
def list_books(
    author_id: Annotated[int | None, Query(examples=[1])] = None,
    limit: Annotated[int, Query(ge=1, le=100, examples=[10])] = 20,
) -> list[Book]:
    books = [book for book in store.books.values() if author_id is None or book.author_id == author_id]
    return books[:limit]


@app.get("/books/search", response_model=list[Book], tags=["books"], summary="Books whose title contains a phrase")
def search_books(q: Annotated[str, Query(min_length=1, examples=["dispossessed"])]) -> list[Book]:
    return [book for book in store.books.values() if q.lower() in book.title.lower()]


@app.get("/books/{book_id}", response_model=Book, tags=["books"], summary="One book", responses=NOT_FOUND)
def get_book(book_id: Annotated[int, Path(examples=[1])]) -> Book:
    if book_id not in store.books:
        raise HTTPException(status_code=404, detail="no such book")
    return store.books[book_id]


@app.post(
    "/books", response_model=Book, status_code=201, tags=["books"], summary="Add a book",
    dependencies=[Depends(require_token)], responses={**UNAUTHORIZED, **NOT_FOUND},
)
def create_book(book: BookIn) -> Book:
    if book.author_id not in store.authors:
        raise HTTPException(status_code=404, detail="no such author")
    created = Book(id=store.next_book, **book.model_dump())
    store.books[created.id] = created
    store.next_book += 1
    return created


@app.put(
    "/books/{book_id}", response_model=Book, tags=["books"], summary="Replace a book",
    dependencies=[Depends(require_token)], responses={**UNAUTHORIZED, **NOT_FOUND},
)
def replace_book(book_id: Annotated[int, Path(examples=[1])], book: BookIn) -> Book:
    if book_id not in store.books:
        raise HTTPException(status_code=404, detail="no such book")
    if book.author_id not in store.authors:
        raise HTTPException(status_code=404, detail="no such author")
    replaced = Book(id=book_id, **book.model_dump())
    store.books[book_id] = replaced
    return replaced


@app.delete(
    "/books/{book_id}", status_code=204, tags=["books"],
    summary="Remove a book; removing one that is gone is still 204",
    dependencies=[Depends(require_token)], responses=UNAUTHORIZED,
)
def delete_book(book_id: Annotated[int, Path(examples=[5])]) -> None:
    store.books.pop(book_id, None)


@app.post(
    "/loans", response_model=Loan, status_code=201, tags=["loans"], summary="Lend a book to the reader in X-Reader",
    dependencies=[Depends(require_token)], responses={**UNAUTHORIZED, **NOT_FOUND},
)
def create_loan(loan: LoanIn, x_reader: Annotated[str, Header(examples=["reader-42"])]) -> Loan:
    if loan.book_id not in store.books:
        raise HTTPException(status_code=404, detail="no such book")
    created = Loan(id=store.next_loan, book_id=loan.book_id, reader=x_reader)
    store.loans[created.id] = created
    store.next_loan += 1
    return created

"""Names for generated code: identifiers, class names, and uniqueness."""

from __future__ import annotations

import keyword
import re

_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_NOT_WORD = re.compile(r"[^0-9a-zA-Z]+")


def to_identifier(text: str) -> str:
    """A valid, readable snake_case identifier for any label a document may carry."""
    spaced = _CAMEL_BOUNDARY.sub("_", text)
    name = _NOT_WORD.sub("_", spaced).strip("_").lower()
    name = re.sub(r"_+", "_", name)
    if not name:
        return "value"
    if name[0].isdigit():
        # A leading underscore would make a Pydantic field private, so prefix a word instead.
        name = f"field_{name}"
    if keyword.iskeyword(name):
        name += "_"
    return name


def to_class_name(text: str) -> str:
    """A PascalCase class name: 'find_pets_by_status' -> 'FindPetsByStatus', 'ApiResponse' stays."""
    parts = _NOT_WORD.split(_CAMEL_BOUNDARY.sub(" ", text))
    name = "".join(part[:1].upper() + part[1:] for part in parts if part)
    if not name:
        return "Model"
    if name[0].isdigit():
        name = f"Model{name}"
    return name


def unique(name: str, taken: set[str]) -> str:
    """`name`, or `name_2`, `name_3`... — whichever is not yet in `taken`; the result is added to it."""
    candidate = name
    counter = 2
    while candidate in taken:
        candidate = f"{name}_{counter}"
        counter += 1
    taken.add(candidate)
    return candidate


def plural(count: int, word: str) -> str:
    """'1 test', '2 tests'."""
    return f"{count} {word}" if count == 1 else f"{count} {word}s"

from pathlib import Path

import pytest
from pydantic import TypeAdapter, ValidationError

from api_test_gen.ir import ApiModel
from api_test_gen.models import generate_models
from api_test_gen.openapi import load_openapi
from tests.helpers import load_module, ruff_check

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

SCHEMAS = {
    "Pet": {
        "type": "object",
        "description": "A pet for sale in the pet store\nSecond line is dropped.",
        "required": ["name", "photoUrls"],
        "additionalProperties": False,
        "properties": {
            "id": {"type": "integer", "format": "int64"},
            "name": {"type": "string"},
            "photoUrls": {"type": "array", "items": {"type": "string"}},
            "owner": {"type": "object", "properties": {"name": {"type": "string"}}},
            "tags": {"type": "array", "items": {"$ref": "#/components/schemas/Tag"}},
            "status": {"type": "string", "enum": ["available", "pending", "sold"]},
            "meta": {"type": "object"},
            "input": {},
        },
    },
    "Tag": {"type": "object", "properties": {"id": {"type": "integer"}, "name": {"type": "string"}}},
    "Odd": {
        "type": "object",
        "required": ["class", "2nd"],
        "properties": {
            "class": {"type": "string"},
            "2nd": {"type": "integer"},
            "old": {"type": "string", "nullable": True},
            "new": {"type": ["integer", "null"]},
            "either": {"anyOf": [{"type": "string"}, {"type": "null"}, {"type": "integer"}]},
            "both": {"allOf": [{"$ref": "#/components/schemas/Tag"}]},
        },
    },
    "Pets": {"type": "array", "items": {"$ref": "#/components/schemas/Pet"}},
    "PetsByStatus": {"type": "array", "items": {"$ref": "#/components/schemas/Pets"}},
    "Status": {"type": "string", "enum": ["on", "off"]},
    "Combined": {
        "allOf": [
            {"$ref": "#/components/schemas/Tag"},
            {"type": "object", "required": ["extra"], "properties": {"extra": {"type": "boolean"}}},
        ]
    },
}
API = ApiModel(title="t", version="1", base_url="", operations=(), schemas=SCHEMAS)


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    path = tmp_path_factory.mktemp("models") / "models.py"
    path.write_text(generate_models(API, "small.yaml"))
    return path


def test_the_source_is_lint_clean_and_imports_only_what_it_uses(generated):
    assert ruff_check(generated) == ""
    source = generated.read_text()
    assert "from typing import Any, Literal" in source
    assert "from pydantic import BaseModel, ConfigDict, Field" in source
    assert source.index("class Pet(") < source.index("class Tag(") < source.index("class PetOwner(")
    assert (
        source.index("class Combined(") < source.index("Pets = list[Pet]") < source.index("PetsByStatus = list[Pets]")
    )
    assert 'Status = Literal["on", "off"]' in source
    assert source.rstrip().endswith("_model.model_rebuild()")


def test_classes_validate_and_reject_what_the_schema_says(generated):
    models = load_module(generated)
    pet = models.Pet.model_validate({
        "id": 1, "name": "Rex", "photoUrls": ["a"], "owner": {"name": "Ann"}, "tags": [{"id": 1}], "status": "sold",
        "meta": {"k": [1]}, "input": None,
    })
    assert pet.photo_urls == ["a"]
    assert isinstance(pet.owner, models.PetOwner)
    assert isinstance(pet.tags[0], models.Tag)
    with pytest.raises(ValidationError):
        models.Pet.model_validate({"name": "Rex", "photoUrls": [], "colour": "red"})  # extra="forbid"
    with pytest.raises(ValidationError):
        models.Pet.model_validate({"name": "Rex", "photoUrls": [], "status": "lost"})  # Literal
    with pytest.raises(ValidationError):
        models.Pet.model_validate({"photoUrls": []})  # required
    models.Tag.model_validate({"id": 1, "anything": "goes"})  # open schema: extras ignored


def test_aliases_nullables_and_keywords(generated):
    models = load_module(generated)
    odd = models.Odd.model_validate(
        {"class": "a", "2nd": 2, "old": None, "new": None, "either": None, "both": {"id": 1}}
    )
    assert (odd.class_, odd.field_2nd, odd.old, odd.new, odd.either) == ("a", 2, None, None, None)
    assert isinstance(odd.both, models.Tag)
    assert models.Odd.model_validate({"class": "a", "2nd": 2, "either": 3}).either == 3
    assert TypeAdapter(models.Pets).validate_python([{"name": "a", "photoUrls": []}])[0].name == "a"
    assert TypeAdapter(models.PetsByStatus).validate_python([[{"name": "a", "photoUrls": []}]])
    assert TypeAdapter(models.Status).validate_python("on") == "on"
    combined = models.Combined.model_validate({"id": 1, "extra": True})
    assert (combined.id, combined.extra) == (1, True)


def test_only_aliases_means_no_base_model_import(tmp_path):
    names_schema = {"Names": {"type": "array", "items": {"type": "string"}}}
    api = ApiModel(title="t", version="1", base_url="", operations=(), schemas=names_schema)
    source = generate_models(api, "x.json")
    assert "pydantic" not in source
    assert "Names = list[str]" in source
    assert "model_rebuild" not in source
    path = tmp_path / "models.py"
    path.write_text(source)
    assert ruff_check(path) == ""


def test_petstore_models(tmp_path):
    api = load_openapi(FIXTURES / "petstore-openapi3.json")
    path = tmp_path / "models.py"
    path.write_text(generate_models(api, "petstore-openapi3.json"))
    assert ruff_check(path) == ""
    models = load_module(path)
    pet = models.Pet.model_validate({
        "id": 10, "name": "doggie", "category": {"id": 1, "name": "Dogs"}, "photoUrls": ["string"],
        "tags": [{"id": 0, "name": "string"}], "status": "available",
    })
    assert pet.category.name == "Dogs"
    assert TypeAdapter(models.FindPetsByStatusResponse).validate_python([{"name": "a", "photoUrls": []}])
    assert models.ApiResponse.model_validate({"code": 1, "type": "t", "message": "m"}).code == 1
    # additionalProperties: int32
    assert TypeAdapter(models.GetInventoryResponse).validate_python({"sold": 3}) == {"sold": 3}

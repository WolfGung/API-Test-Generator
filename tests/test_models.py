import warnings
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


# --- Fix round 1: five defects found in review, each reproduced and then fixed. --------------------------------


def test_nullable_hoisted_objects_and_nullable_ref_targets_accept_null(tmp_path):
    """A hoisted inline object that was `nullable`/`type: [..., "null"]` must stay nullable at its use site, and
    a required `$ref` to a named schema that is itself nullable must accept null too (3.0 `nullable` and the
    3.1 `type` list spelling, both for a class reached by hoisting and for one referenced directly)."""
    api = ApiModel(
        title="t", version="1", base_url="", operations=(),
        schemas={
            "Owner": {"type": "object", "nullable": True, "properties": {"name": {"type": "string"}}},
            "Order": {
                "type": "object",
                "required": ["address", "billing", "owner"],
                "properties": {
                    "address": {"type": "object", "nullable": True, "properties": {"city": {"type": "string"}}},
                    "billing": {"type": ["object", "null"], "properties": {"iban": {"type": "string"}}},
                    "owner": {"$ref": "#/components/schemas/Owner"},
                },
            },
        },
    )
    path = tmp_path / "models.py"
    path.write_text(generate_models(api, "order.yaml"))
    assert ruff_check(path) == ""
    models = load_module(path)
    order = models.Order.model_validate({"address": None, "billing": None, "owner": None})
    assert (order.address, order.billing, order.owner) == (None, None, None)
    filled = models.Order.model_validate(
        {"address": {"city": "x"}, "billing": {"iban": "y"}, "owner": {"name": "a"}}
    )
    assert (filled.address.city, filled.billing.iban, filled.owner.name) == ("x", "y", "a")


def test_write_only_required_properties_are_optional_in_response_models(tmp_path):
    """`writeOnly` only binds the request; a response model (what this module generates) must treat such a
    property as optional even when the schema lists it as required, while an ordinary (e.g. `readOnly`)
    required property is unaffected."""
    api = ApiModel(
        title="t", version="1", base_url="", operations=(),
        schemas={"User": {
            "type": "object",
            "required": ["id", "password"],
            "properties": {
                "id": {"type": "integer", "readOnly": True},
                "password": {"type": "string", "writeOnly": True},
            },
        }},
    )
    path = tmp_path / "models.py"
    path.write_text(generate_models(api, "user.yaml"))
    assert ruff_check(path) == ""
    models = load_module(path)
    assert models.User.model_validate({"id": 1}).id == 1
    with pytest.raises(ValidationError):
        models.User.model_validate({"password": "x"})  # id is a normal required property


def test_field_names_cannot_shadow_annotation_builtins_or_basemodel_attributes(tmp_path):
    """A property named like an annotation builtin (list/dict/str/int/float/bool), a `model_*` name, or a fixed
    BaseModel attribute must not become a class attribute of that name: binding it to a value shadows the name
    Pydantic's own machinery needs when it evaluates the annotations. Import with warnings promoted to errors,
    since the crash this guards against is a shadowing `UserWarning` that Pydantic would otherwise only warn
    about, not raise - pristine output means neither a crash nor that warning."""
    api = ApiModel(
        title="t", version="1", base_url="", operations=(),
        schemas={
            "Item": {"type": "object", "properties": {"id": {"type": "integer"}}},
            "Page": {
                "type": "object",
                "required": ["list"],
                "properties": {
                    "list": {"type": "array", "items": {"$ref": "#/components/schemas/Item"}},
                    "dict": {"type": "string"},
                    "str": {"type": "string"},
                    "schema": {"type": "string"},
                    "model_dump": {"type": "string"},
                    "modelConfig": {"type": "string"},
                },
            },
        },
    )
    path = tmp_path / "models.py"
    path.write_text(generate_models(api, "page.yaml"))
    assert ruff_check(path) == ""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        models = load_module(path)
    page = models.Page.model_validate({
        "list": [{"id": 1}], "dict": "d", "str": "s", "schema": "sc", "model_dump": "md", "modelConfig": "mc",
    })
    assert page.list_[0].id == 1
    assert (page.dict_, page.str_, page.schema_) == ("d", "s", "sc")
    assert (page.model_dump_, page.model_config_) == ("md", "mc")


def test_self_and_mutually_referencing_aliases_become_pep_695_type_statements(tmp_path):
    """An alias that refers to itself (JsonValue) or to another alias that refers back (Node/NodeList) must be
    written as a PEP 695 `type Name = ...` statement, which tolerates the forward reference a plain assignment
    cannot. An enum whose values happen to spell another alias's name (Unit's own enum contains the string
    "Unit") must not be mistaken for a cycle: the dependency scan ignores identifier-shaped text inside string
    literals, so Unit/Units keep their plain `Name = ...` form and import in the correct order."""
    api = ApiModel(
        title="t", version="1", base_url="", operations=(),
        schemas={
            "JsonValue": {"oneOf": [
                {"type": "string"},
                {"type": "number"},
                {"type": "boolean"},
                {"type": "array", "items": {"$ref": "#/components/schemas/JsonValue"}},
                {"type": "object", "additionalProperties": {"$ref": "#/components/schemas/JsonValue"}},
            ]},
            "Node": {"type": "object", "additionalProperties": {"$ref": "#/components/schemas/NodeList"}},
            "NodeList": {"type": "array", "items": {"$ref": "#/components/schemas/Node"}},
            "Units": {"type": "array", "items": {"$ref": "#/components/schemas/Unit"}},
            "Unit": {"type": "string", "enum": ["Unit", "Pack"]},
        },
    )
    source = generate_models(api, "recursive.yaml")
    path = tmp_path / "models.py"
    path.write_text(source)
    assert ruff_check(path) == ""
    assert "type JsonValue =" in source
    assert "type Node =" in source
    assert "type NodeList =" in source
    assert "type Unit =" not in source  # no genuine cycle: plain assignments, in dependency order
    assert "Unit = Literal[" in source
    assert "Units = list[Unit]" in source
    models = load_module(path)
    assert TypeAdapter(models.JsonValue).validate_python({"a": [1, "x", {"b": True}]}) == {"a": [1, "x", {"b": True}]}
    assert TypeAdapter(models.NodeList).validate_python([{"a": [{}]}])
    assert TypeAdapter(models.Units).validate_python(["Pack"]) == ["Pack"]


def test_allof_of_non_object_parts_is_an_alias_of_its_first_typed_part(tmp_path):
    """An `allOf` whose parts never resolve to an object schema must not generate an (empty) class: it is an
    alias of its first part that actually carries a type - a `$ref` part contributing the referenced name - both
    for a named schema (PetStatus/PetNames) and for an inline allOf in property position (Item.code, where a
    bare constraint like `minLength` must be skipped in favour of the sibling that has a `type`)."""
    api = ApiModel(
        title="t", version="1", base_url="", operations=(),
        schemas={
            "Status": {"type": "string", "enum": ["on", "off"]},
            "PetStatus": {"allOf": [{"$ref": "#/components/schemas/Status"}]},
            "Names": {"type": "array", "items": {"type": "string"}},
            "PetNames": {"allOf": [{"$ref": "#/components/schemas/Names"}]},
            "Item": {
                "type": "object",
                "required": ["code"],
                "properties": {"code": {"allOf": [{"type": "string"}, {"minLength": 2}]}},
            },
        },
    )
    source = generate_models(api, "allof.yaml")
    path = tmp_path / "models.py"
    path.write_text(source)
    assert ruff_check(path) == ""
    assert "class PetStatus" not in source
    assert "class PetNames" not in source
    assert "PetStatus = Status" in source
    assert "PetNames = Names" in source
    models = load_module(path)
    assert TypeAdapter(models.PetStatus).validate_python("on") == "on"
    assert TypeAdapter(models.PetNames).validate_python(["a"]) == ["a"]
    assert models.Item.model_validate({"code": "ab"}).code == "ab"

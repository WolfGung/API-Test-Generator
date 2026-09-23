from api_test_gen.ir import ApiModel
from api_test_gen.samples import sample_for

API = ApiModel(
    title="t", version="1", base_url="", operations=(),
    schemas={
        "Tag": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string", "example": "fluffy"}},
        },
        "Pet": {
            "type": "object",
            "required": ["name", "photoUrls"],
            "properties": {
                "id": {"type": "integer", "format": "int64", "example": 10},
                "name": {"type": "string", "example": "doggie"},
                "photoUrls": {"type": "array", "items": {"type": "string"}},
                "tags": {"type": "array", "items": {"$ref": "#/components/schemas/Tag"}},
                "status": {"type": "string", "enum": ["available", "pending", "sold"]},
                "weight": {"type": "number", "minimum": 0.5},
            },
        },
    },
)


def sample(schema):
    return sample_for(schema, API)


def test_document_values_win_in_order_example_default_enum():
    assert sample({"type": "string", "example": "e", "default": "d", "enum": ["x"]}) == "e"
    assert sample({"type": "string", "default": "d", "enum": ["x"]}) == "d"
    assert sample({"type": "string", "enum": ["x", "y"]}) == "x"
    assert sample({"type": "integer", "examples": [4, 5]}) == 4
    assert sample({"type": "integer", "examples": {"one": {"value": 6}}}) == 6
    assert sample({"const": "fixed"}) == "fixed"


def test_type_based_values_and_formats():
    assert sample({"type": "string"}) == "string"
    assert sample({"type": "string", "format": "email"}) == "user@example.com"
    assert sample({"type": "string", "format": "date-time"}) == "2024-01-31T12:00:00Z"
    assert sample({"type": "string", "minLength": 8}) == "xxxxxxxx"
    assert sample({"type": "string", "maxLength": 3}) == "str"
    assert sample({"type": "integer"}) == 1
    assert sample({"type": "integer", "minimum": 10}) == 10
    assert sample({"type": "integer", "minimum": 10, "exclusiveMinimum": True}) == 11
    assert sample({"type": "integer", "exclusiveMinimum": 10}) == 11
    assert sample({"type": "integer", "maximum": 0}) == 0
    assert sample({"type": "number"}) == 1.0
    assert sample({"type": "boolean"}) is True
    assert sample({"type": "array", "items": {"type": "integer"}}) == [1]
    assert sample({"type": "array", "items": {"type": "string"}, "minItems": 2}) == ["string", "string"]
    assert sample({"type": "array"}) == ["string"]
    assert sample({}) is None
    assert sample({"type": "object"}) == {}


def test_objects_carry_required_fields_and_optional_fields_with_examples():
    assert sample({"$ref": "#/components/schemas/Pet"}) == {
        "name": "doggie",
        "photoUrls": ["string"],
        "id": 10,
    }
    assert sample({"$ref": "#/components/schemas/Tag"}) == {"name": "fluffy"}


def test_null_options_are_skipped_and_all_of_is_merged():
    assert sample({"anyOf": [{"type": "null"}, {"type": "integer"}]}) == 1
    assert sample({"type": ["null", "string"]}) == "string"
    assert sample({"oneOf": [{"$ref": "#/components/schemas/Tag"}, {"type": "string"}]}) == {"name": "fluffy"}
    all_of = {
        "allOf": [
            {"$ref": "#/components/schemas/Tag"},
            {"type": "object", "required": ["extra"], "properties": {"extra": {"type": "boolean"}}},
        ]
    }
    assert sample(all_of) == {"name": "fluffy", "extra": True}

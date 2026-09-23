from api_test_gen.ir import ApiModel
from api_test_gen.samples import required_fields, sample_for

API = ApiModel(
    title="t", version="1", base_url="", operations=(),
    schemas={
        "Tag": {
            "type": "object",
            "properties": {"id": {"type": "integer"}, "name": {"type": "string", "example": "fluffy"}},
        },
        "Status": {"type": "string", "enum": ["available", "pending", "sold"]},
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


def test_allof_falls_back_to_a_scalar_when_no_part_is_an_object():
    # An `allOf` combining a non-object `$ref` with a sibling like `description` never gives the merge loop
    # a dict to merge; the fallback offers the first part's own sample instead of the empty `{}` it used to.
    assert sample({"allOf": [{"$ref": "#/components/schemas/Status"}], "description": "irrelevant"}) == "available"
    assert sample({"allOf": [{"type": "integer", "minimum": 5}]}) == 5


def test_a_cyclic_reference_stops_recursion_instead_of_bottoming_out_at_max_depth():
    api = ApiModel(
        title="t", version="1", base_url="", operations=(),
        schemas={
            "Node": {
                "type": "object",
                "required": ["name", "children"],
                "properties": {
                    "name": {"type": "string"},
                    "children": {"type": "array", "items": {"$ref": "#/components/schemas/Node"}},
                },
            },
            "Chain": {
                "type": "object",
                "required": ["child"],
                "properties": {"child": {"$ref": "#/components/schemas/Chain"}},
            },
        },
    )
    assert sample_for({"$ref": "#/components/schemas/Node"}, api) == {"name": "string", "children": []}
    # `child` is required and not nullable, yet its only schema is `Chain` itself: there is no finite value
    # that satisfies it, so the best a sampler can offer for that one field is None.
    assert sample_for({"$ref": "#/components/schemas/Chain"}, api) == {"child": None}


def test_required_fields_flattens_allof_through_refs_in_document_order_without_duplicates():
    api = ApiModel(
        title="t", version="1", base_url="", operations=(),
        schemas={
            "Named": {"type": "object", "required": ["name"], "properties": {"name": {"type": "string"}}},
            "Aged": {"type": "object", "required": ["name", "age"], "properties": {"age": {"type": "integer"}}},
            "Person": {
                "allOf": [{"$ref": "#/components/schemas/Named"}, {"$ref": "#/components/schemas/Aged"}],
            },
        },
    )
    assert required_fields({"$ref": "#/components/schemas/Person"}, api) == ["name", "age"]
    assert required_fields({"type": "object", "required": ["x"]}, api) == ["x"]
    assert required_fields({}, api) == []

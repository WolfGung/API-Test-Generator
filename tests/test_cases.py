from pathlib import Path

from api_test_gen.cases import cases_for
from api_test_gen.ir import ApiModel, Body, Operation, Parameter, Response, Security
from api_test_gen.openapi import load_openapi
from tests.documents import PARAMETERS

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

SCHEMAS = {
    "Thing": {
        "type": "object",
        "required": ["name", "size"],
        "properties": {
            "name": {"type": "string", "example": "x"},
            "size": {"type": "integer"},
            "note": {"type": "string"},
        },
    },
}
API = ApiModel(
    title="t", version="1", base_url="", operations=(), schemas=SCHEMAS, security=Security(kind="bearer", name="b")
)

CREATE = Operation(
    operation_id="create_thing", method="POST", path="/owners/{owner}/things", tag="things", summary="Create a thing",
    parameters=(
        Parameter(name="owner", location="path", required=True, schema={"type": "integer"}, examples=(7,)),
        Parameter(name="dry", location="query", required=True, schema={"type": "boolean"}),
        Parameter(name="verbose", location="query", required=False, schema={"type": "boolean"}, examples=(True,)),
        Parameter(name="quiet", location="query", required=False, schema={"type": "boolean"}),
        Parameter(name="X-Trace", location="header", required=True, schema={"type": "string"}, examples=("abc",)),
    ),
    body=Body(content_type="application/json", schema={"$ref": "#/components/schemas/Thing"}, required=True),
    responses=(Response(status="201", schema={"$ref": "#/components/schemas/Thing"}, content_type="application/json"),),
    secured=True,
)


def test_the_positive_case_carries_every_documented_value():
    positive = cases_for(CREATE, API)[0]
    assert positive.name == "test_create_thing"
    assert positive.kind == "positive"
    assert (positive.method, positive.path) == ("POST", "/owners/{owner}/things")
    assert positive.path_params == {"owner": 7}
    assert positive.query == {"dry": True, "verbose": True}  # optional without an example is left out
    assert positive.headers == {"X-Trace": "abc"}
    assert positive.body == {"name": "x", "size": 1}
    assert positive.body_kind == "json"
    assert positive.expected_status == 201
    assert positive.validate == "Thing"
    assert positive.uses_auth is True
    assert positive.skip_reason is None
    assert positive.doc == "POST /owners/{owner}/things: Create a thing"


def test_one_negative_per_required_parameter_and_field_plus_no_credentials():
    cases = cases_for(CREATE, API)
    assert [c.name for c in cases] == [
        "test_create_thing",
        "test_create_thing_without_dry",
        "test_create_thing_without_x_trace",
        "test_create_thing_without_name",
        "test_create_thing_without_size",
        "test_create_thing_without_credentials",
    ]
    without_dry = cases[1]
    assert without_dry.kind == "missing_parameter"
    assert without_dry.query == {"verbose": True}
    assert without_dry.expect == "client_error"
    assert without_dry.uses_auth is True
    assert without_dry.validate is None
    assert cases[2].headers == {}
    assert cases[3].kind == "missing_field"
    assert cases[3].body == {"size": 1}
    assert cases[5].kind == "no_credentials"
    assert cases[5].uses_auth is False
    assert cases[5].expect == "unauthorized"
    assert cases[5].body == {"name": "x", "size": 1}


def test_names_stay_unique_when_a_parameter_and_a_field_share_a_name():
    op = Operation(
        operation_id="thing", method="POST", path="/things", tag="t", summary="",
        parameters=(Parameter(name="name", location="query", required=True, schema={"type": "string"}),),
        body=Body(content_type="application/json", schema={"$ref": "#/components/schemas/Thing"}, required=True),
    )
    assert [c.name for c in cases_for(op, API)] == [
        "test_thing",
        "test_thing_without_name",
        "test_thing_without_name_2",
        "test_thing_without_size",
    ]


def test_a_text_body_is_sent_as_content_and_a_form_body_skips_the_operation():
    text = Operation(
        operation_id="echo", method="POST", path="/post", tag="t", summary="",
        body=Body(content_type="text/plain", schema={"type": "string"}, required=True, examples=("hello",)),
    )
    [positive] = cases_for(text, API)
    fields = (positive.body, positive.body_kind, positive.expected_status, positive.expect)
    assert fields == ("hello", "text", None, "success")
    form = Operation(
        operation_id="upload", method="POST", path="/upload", tag="t", summary="",
        parameters=(Parameter(name="kind", location="query", required=True, schema={"type": "string"}),),
        body=Body(content_type="multipart/form-data", schema={"type": "object"}, required=True),
        secured=True,
    )
    [only] = cases_for(form, API)
    assert only.skip_reason == "request body is multipart/form-data, which the generator does not produce"
    assert only.body is None


def test_an_optional_empty_body_is_not_sent():
    op = Operation(
        operation_id="touch", method="POST", path="/touch", tag="t", summary="",
        body=Body(content_type="application/json", schema={}, required=False),
    )
    [positive] = cases_for(op, API)
    assert (positive.body, positive.body_kind) == (None, None)


def test_a_required_empty_body_is_sent_as_an_empty_object():
    op = Operation(
        operation_id="touch", method="POST", path="/touch", tag="t", summary="",
        body=Body(content_type="application/json", schema={}, required=True),
    )
    [positive] = cases_for(op, API)
    assert (positive.body, positive.body_kind) == ({}, "json")
    assert positive.expect == "success"


def test_allof_body_gets_one_missing_field_case_per_flattened_required_field():
    op = Operation(
        operation_id="thing", method="POST", path="/things", tag="t", summary="",
        body=Body(
            content_type="application/json",
            schema={
                "allOf": [
                    {"type": "object", "required": ["a"], "properties": {"a": {"type": "string"}}},
                    {"type": "object", "required": ["b"], "properties": {"b": {"type": "string"}}},
                ],
            },
            required=True,
        ),
    )
    cases = cases_for(op, API)
    assert [c.name for c in cases] == ["test_thing", "test_thing_without_a", "test_thing_without_b"]
    assert cases[0].body == {"a": "string", "b": "string"}
    assert cases[1].body == {"b": "string"}
    assert cases[2].body == {"a": "string"}


def test_petstore_cases():
    api = load_openapi(FIXTURES / "petstore-openapi3.json")
    by_id = {op.operation_id: op for op in api.operations}
    find = cases_for(by_id["find_pets_by_status"], api)
    assert [c.name for c in find] == [
        "test_find_pets_by_status",
        "test_find_pets_by_status_without_status",
        "test_find_pets_by_status_without_credentials",
    ]
    assert find[0].query == {"status": "available"}
    assert find[0].validate == "FindPetsByStatusResponse"
    add = cases_for(by_id["add_pet"], api)
    assert [c.name for c in add] == [
        "test_add_pet",
        "test_add_pet_without_name",
        "test_add_pet_without_photo_urls",
        "test_add_pet_without_credentials",
    ]
    assert add[0].body["name"] == "doggie"
    assert add[0].body["photoUrls"] == ["string"]
    upload = cases_for(by_id["upload_file"], api)
    assert len(upload) == 1 and upload[0].skip_reason.startswith("request body is application/octet-stream")
    total = sum(len(cases_for(op, api)) for op in api.operations)
    assert total == 33


def test_an_optional_parameter_is_sent_when_the_document_gives_it_a_value(tmp_path):
    """An example inside the schema (where OpenAPI 3.1 documents keep it), a default or a const is a value the
    document gives; a parameter-level example outranks the schema's; a parameter with none of them is left out."""
    path = tmp_path / "parameters.yaml"
    path.write_text(PARAMETERS)
    api = load_openapi(path)
    [positive] = cases_for(api.operations[0], api)  # every parameter is optional, so there are no negatives
    assert positive.query == {"author": 1, "limit": 10, "page": 3, "q": "given"}
    assert positive.headers == {"X-Mode": "fast"}


def test_header_values_are_written_json_style_not_as_python_reprs():
    """A boolean header example must go out as `true`, a number as its digits: `str(True)` is `True`, which no
    server reads as a boolean."""
    op = Operation(
        operation_id="flags", method="GET", path="/flags", tag="t", summary="",
        parameters=(
            Parameter(name="X-Dry", location="header", required=True, schema={"type": "boolean"}, examples=(True,)),
            Parameter(name="X-Off", location="header", required=False, schema={"type": "boolean"}, examples=(False,)),
            Parameter(name="X-Count", location="header", required=True, schema={"type": "integer"}, examples=(5,)),
            Parameter(name="X-Ratio", location="header", required=True, schema={"type": "number"}, examples=(1.5,)),
            Parameter(name="X-Name", location="header", required=True, schema={"type": "string"}, examples=("x",)),
            Parameter(name="X-Sampled", location="header", required=True, schema={"type": "boolean"}),
        ),
    )
    positive = cases_for(op, API)[0]
    assert positive.headers == {
        "X-Dry": "true", "X-Off": "false", "X-Count": "5", "X-Ratio": "1.5", "X-Name": "x", "X-Sampled": "true",
    }

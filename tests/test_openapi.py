from pathlib import Path

import pytest
import yaml

from api_test_gen.ir import SpecError
from api_test_gen.openapi import load_document, load_openapi
from tests.documents import PARAMETERS

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

SMALL = """
openapi: 3.0.3
info: {title: Small, version: "2.0"}
servers:
  - url: https://{host}/v{major}
    variables:
      host: {default: api.example.com}
      major: {default: "1"}
security:
  - bearer: []
components:
  securitySchemes:
    oauth: {type: oauth2, flows: {}}
    bearer: {type: http, scheme: bearer}
  parameters:
    Verbose: {name: verbose, in: query, required: false, schema: {type: boolean}, example: true}
  requestBodies:
    NewThing:
      required: true
      content:
        application/xml: {schema: {type: string}}
        application/json: {schema: {$ref: "#/components/schemas/Thing"}, example: {name: x}}
  responses:
    Listing:
      description: things
      content:
        application/json: {schema: {type: array, items: {$ref: "#/components/schemas/Thing"}}}
  schemas:
    Thing:
      type: object
      required: [name]
      properties: {name: {type: string}}
paths:
  /things/{id}:
    parameters:
      - {name: id, in: path, required: true, schema: {type: integer}, example: 7}
      - {name: session, in: cookie, required: true, schema: {type: string}}
    get:
      operationId: getThing
      tags: [things]
      summary: One thing
      parameters:
        - $ref: "#/components/parameters/Verbose"
        - {name: id, in: path, required: true, schema: {type: string}, examples: {seven: {value: "7"}}}
      security: []
      responses:
        "200": {description: ok, content: {application/json: {schema: {$ref: "#/components/schemas/Thing"}}}}
        "404": {description: gone}
    delete:
      operationId: getThing
      tags: [things]
      responses:
        "204": {description: gone}
  /things:
    post:
      requestBody: {$ref: "#/components/requestBodies/NewThing"}
      responses:
        "201":
          description: made
          content:
            application/json:
              schema: {type: object, required: [id], properties: {id: {type: integer}}}
        default: {description: any}
    get:
      operationId: listThings
      security: [{oauth: [read]}]
      responses:
        "200": {$ref: "#/components/responses/Listing"}
"""


@pytest.fixture
def small(tmp_path):
    path = tmp_path / "small.yaml"
    path.write_text(SMALL)
    return load_openapi(path)


def test_title_version_and_server_variables(small):
    assert (small.title, small.version) == ("Small", "2.0")
    assert small.base_url == "https://api.example.com/v1"


def test_operations_in_document_order_with_derived_and_deduplicated_ids(small):
    assert [op.operation_id for op in small.operations] == ["get_thing", "get_thing_2", "post_things", "list_things"]
    assert [op.method for op in small.operations] == ["GET", "DELETE", "POST", "GET"]
    assert small.operations[2].tag == "default"
    assert small.tags == ("things", "default")


def test_path_level_parameters_are_merged_and_overridden_and_cookies_dropped(small):
    get_thing = small.operations[0]
    by_name = {(p.name, p.location): p for p in get_thing.parameters}
    assert set(by_name) == {("id", "path"), ("verbose", "query")}
    assert by_name[("id", "path")].schema == {"type": "string"}  # the operation's own wins
    assert by_name[("id", "path")].examples == ("7",)
    assert by_name[("verbose", "query")].examples == (True,)
    assert by_name[("verbose", "query")].required is False


def test_security_is_the_first_supported_scheme_and_operations_can_opt_out(small):
    assert small.security.kind == "bearer"
    assert small.security.name == "bearer"
    assert [op.secured for op in small.operations] == [False, True, True, True]


def test_request_body_prefers_json_and_keeps_the_media_example(small):
    body = small.operations[2].body
    assert body.content_type == "application/json"
    assert body.required is True
    assert body.schema == {"$ref": "#/components/schemas/Thing"}
    assert body.examples == ({"name": "x"},)


def test_inline_response_schemas_get_a_name(small):
    post_things = small.operations[2]
    assert post_things.success_status == 201
    assert post_things.success.schema == {"$ref": "#/components/schemas/PostThingsResponse"}
    assert small.schemas["PostThingsResponse"]["required"] == ["id"]
    listing = small.operations[3].success
    assert listing.schema == {"$ref": "#/components/schemas/ListThingsResponse"}
    assert small.schemas["ListThingsResponse"]["type"] == "array"


def test_success_picks_the_lowest_2xx_and_resolve_follows_refs(small):
    get_thing = small.operations[0]
    assert get_thing.success_status == 200
    assert small.resolve(get_thing.success.schema)["required"] == ["name"]
    assert small.operations[1].success_status == 204
    assert small.operations[1].success.schema is None


def test_a_swagger_2_document_is_refused(tmp_path):
    path = tmp_path / "old.json"
    path.write_text('{"swagger": "2.0", "info": {"title": "x"}, "paths": {}}')
    with pytest.raises(SpecError, match="OpenAPI 3"):
        load_openapi(path)


def test_an_unparseable_file_is_refused(tmp_path):
    path = tmp_path / "broken.yaml"
    path.write_text("openapi: [3\n")
    with pytest.raises(SpecError, match="cannot parse"):
        load_openapi(path)


def test_petstore_facts():
    api = load_openapi(FIXTURES / "petstore-openapi3.json")
    assert api.title.startswith("Swagger Petstore")
    assert api.base_url == "/api/v3"
    assert len(api.operations) == 19
    assert api.tags == ("pet", "store", "user")
    assert api.security.kind == "apiKey"
    assert (api.security.name, api.security.header, api.security.location) == ("api_key", "api_key", "header")
    by_id = {op.operation_id: op for op in api.operations}
    pet = by_id["get_pet_by_id"]
    assert pet.path == "/pet/{petId}"
    assert pet.parameters_in("path")[0].schema["type"] == "integer"
    assert pet.secured is True
    assert by_id["add_pet"].body.schema == {"$ref": "#/components/schemas/Pet"}
    assert by_id["find_pets_by_status"].success.schema == {"$ref": "#/components/schemas/FindPetsByStatusResponse"}
    assert api.schemas["FindPetsByStatusResponse"]["items"] == {"$ref": "#/components/schemas/Pet"}
    assert by_id["place_order"].secured is False
    assert yaml.safe_load(SMALL)["openapi"] == "3.0.3"  # the inline document above is what the other tests parse


def test_parameter_examples_fall_back_to_the_schema_with_a_reference_followed(tmp_path):
    path = tmp_path / "parameters.yaml"
    path.write_text(PARAMETERS)
    by_name = {p.name: p for p in load_openapi(path).operations[0].parameters}
    assert by_name["author"].examples == (1,)  # the schema's, where OpenAPI 3.1 documents carry them
    assert by_name["limit"].examples == (10,)  # found through the reference
    assert by_name["limit"].schema == {"$ref": "#/components/schemas/Limit"}  # which the schema itself keeps
    assert by_name["page"].examples == ()  # a default is not an example; the case builder still sends it
    assert by_name["q"].examples == ("given",)  # the parameter's own, when it has one
    assert by_name["sort"].examples == ()


def test_a_file_that_is_not_utf8_is_refused(tmp_path):
    path = tmp_path / "latin1.yaml"
    path.write_bytes("openapi: 3.0.3\ninfo: {title: Café, version: '1'}\npaths: {}\n".encode("latin-1"))
    with pytest.raises(SpecError, match="not UTF-8 text"):
        load_openapi(path)


def test_yaml_scalars_are_read_as_the_document_wrote_them(tmp_path):
    """PyYAML's implicit typing would send an unquoted timestamp example as `2024-01-31 12:00:00+00:00`, put a
    `datetime.date` into a Literal and turn `on`/`off`/`yes`/`no` into booleans. Those scalars stay strings,
    as in YAML 1.2; `true`/`false` (in any case), integers, floats and null keep their types."""
    path = tmp_path / "scalars.yaml"
    path.write_text(
        "stamp: 2024-01-31T12:00:00Z\nday: 2024-01-31\nswitch: [on, off, yes, no, true, false, True, FALSE]\n"
        "count: 3\nratio: 1.5\nnothing: null\nempty:\n"
    )
    assert load_document(path) == {
        "stamp": "2024-01-31T12:00:00Z",
        "day": "2024-01-31",
        "switch": ["on", "off", "yes", "no", True, False, True, False],
        "count": 3,
        "ratio": 1.5,
        "nothing": None,
        "empty": None,
    }

import json
from pathlib import Path

import pytest

from api_test_gen.cases import cases_for
from api_test_gen.ir import SpecError
from api_test_gen.postman import infer_schema, load_postman

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures"

SMALL = {
    "info": {"name": "Small", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
    "variable": [{"key": "baseUrl", "value": "https://api.example.com"}],
    "auth": {"type": "apikey", "apikey": [{"key": "key", "value": "X-Api-Key"}, {"key": "in", "value": "header"}]},
    "item": [
        {
            "name": "Things",
            "auth": {"type": "bearer", "bearer": [{"key": "token", "value": "{{token}}"}]},
            "item": [
                {
                    "name": "Get Thing",
                    "request": {
                        "method": "GET",
                        "header": [
                            {"key": "X-Trace", "value": "abc"},
                            {"key": "Authorization", "value": "Bearer nope"},
                            {"key": "X-Off", "value": "1", "disabled": True},
                        ],
                        "url": {
                            "raw": "{{baseUrl}}/things/:id?verbose=true",
                            "host": ["{{baseUrl}}"],
                            "path": ["things", ":id"],
                            "query": [{"key": "verbose", "value": "true"}],
                            "variable": [{"key": "id", "value": "7"}],
                        },
                    },
                    "response": [
                        {"code": 404, "body": "gone"},
                        {"code": 200, "header": [{"key": "Content-Type", "value": "application/json"}],
                         "body": "{\"id\": 7, \"name\": \"thing\", \"tags\": [\"a\"], \"owner\": null}"},
                    ],
                },
                {
                    "name": "Make Thing",
                    "request": {
                        "method": "POST",
                        "url": "{{baseUrl}}/things",
                        "body": {"mode": "raw", "raw": "{\"name\": \"new\", \"size\": 2}"},
                    },
                },
            ],
        },
        {
            "name": "Ping",
            "request": {"method": "GET", "url": "https://api.example.com/ping?x&y=1", "auth": {"type": "noauth"}},
        },
        {
            "name": "Old Style",
            "request": {"method": "PUT", "url": "https://api.example.com/{{unknown}}/old",
                        "auth": {"type": "digest", "digest": []},
                        "body": {"mode": "urlencoded", "urlencoded": [{"key": "a", "value": "1"}]}},
        },
        {
            "name": "Get With Form",
            "request": {"method": "GET", "url": "https://api.example.com/form",
                        "body": {"mode": "formdata", "formdata": [{"key": "a", "value": "1"}]}},
        },
    ],
}


@pytest.fixture
def small(tmp_path):
    path = tmp_path / "small.postman_collection.json"
    path.write_text(json.dumps(SMALL))
    return load_postman(path)


def test_title_base_url_and_operations(small):
    assert small.title == "Small"
    assert small.base_url == "https://api.example.com"
    assert [op.operation_id for op in small.operations] == [
        "get_thing", "make_thing", "ping", "old_style", "get_with_form",
    ]
    assert [op.tag for op in small.operations] == ["Things", "Things", "default", "default", "default"]
    assert small.tags == ("Things", "default")


def test_url_object_gives_path_parameters_query_and_headers(small):
    get_thing = small.operations[0]
    assert get_thing.method == "GET"
    assert get_thing.path == "/things/{id}"
    path = get_thing.parameters_in("path")
    assert [(p.name, p.required, p.examples) for p in path] == [("id", True, ("7",))]
    query = get_thing.parameters_in("query")
    assert [(p.name, p.required, p.examples) for p in query] == [("verbose", False, ("true",))]
    assert [(p.name, p.examples) for p in get_thing.parameters_in("header")] == [("X-Trace", ("abc",))]


def test_unknown_variables_and_blank_query_values(small):
    old = small.operations[3]
    assert old.path == "/{unknown}/old"
    assert old.parameters_in("path")[0].examples == ()
    ping = small.operations[2]
    assert [(p.name, p.examples) for p in ping.parameters_in("query")] == [("x", ("",)), ("y", ("1",))]


def _load_url(tmp_path, url):
    path = tmp_path / "urls.postman_collection.json"
    path.write_text(json.dumps({
        "info": {"name": "Urls", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "item": [{"name": "op", "request": {"method": "GET", "url": url}}],
    }))
    return load_postman(path)


def test_object_url_without_raw_uses_protocol_host_and_path(tmp_path):
    api = _load_url(tmp_path, {"protocol": "https", "host": ["api", "example", "com"], "path": ["things"]})
    assert api.base_url == "https://api.example.com"
    assert api.operations[0].path == "/things"


def test_object_url_without_raw_or_protocol_defaults_to_http(tmp_path):
    api = _load_url(tmp_path, {"host": ["api", "example", "com"], "path": ["things"]})
    assert api.base_url == "http://api.example.com"
    assert api.operations[0].path == "/things"


def test_scheme_less_string_url_defaults_to_http(tmp_path):
    api = _load_url(tmp_path, "postman-echo.com/get?x=1")
    op = api.operations[0]
    assert api.base_url == "http://postman-echo.com"
    assert op.path == "/get"
    assert [(p.name, p.examples) for p in op.parameters_in("query")] == [("x", ("1",))]


def test_unresolved_leading_variable_leaves_the_origin_for_the_suite_to_supply(tmp_path):
    api = _load_url(tmp_path, "{{baseUrl}}/things/:id")
    op = api.operations[0]
    assert api.base_url == ""
    assert op.path == "/things/{id}"
    assert op.parameters_in("path")[0].examples == ()


def test_auth_is_inherited_overridden_and_unsupported_kinds_do_not_secure(small):
    assert small.security.kind == "bearer"  # the first supported auth met, walking depth first: the Things folder
    assert [op.secured for op in small.operations] == [True, True, False, False, True]


def test_an_api_key_in_a_header_is_supported_and_one_in_the_query_is_not(tmp_path):
    def load(fields):
        path = tmp_path / f"{len(fields)}-{fields[-1]['value']}.json"
        path.write_text(json.dumps({
            "info": {"name": "Keyed", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
            "auth": {"type": "apikey", "apikey": fields},
            "item": [{"name": "Ping", "request": {"method": "GET", "url": "https://api.example.com/ping"}}],
        }))
        return load_postman(path)

    header = load([{"key": "key", "value": "X-Api-Key"}, {"key": "in", "value": "header"}])
    assert (header.security.kind, header.security.header) == ("apiKey", "X-Api-Key")
    assert header.operations[0].secured is True
    query = load([{"key": "key", "value": "api_key"}, {"key": "in", "value": "query"}])
    assert query.security.kind == "none"
    assert query.operations[0].secured is False


def test_bodies_by_mode_and_method(small):
    make = small.operations[1]
    assert make.body.content_type == "application/json"
    assert make.body.examples == ({"name": "new", "size": 2},)
    assert make.body.schema == {"$ref": "#/components/schemas/MakeThingRequest"}
    # A collection says nothing about which body fields are required, so the request schema lists none.
    assert small.schemas["MakeThingRequest"] == {
        "type": "object",
        "properties": {"name": {"type": "string"}, "size": {"type": "integer"}},
    }
    assert small.operations[3].body.content_type == "application/x-www-form-urlencoded"
    assert "required" not in small.operations[3].body.schema
    assert small.operations[4].body is None  # a GET carries no body, whatever the collection says


def test_a_json_body_from_a_collection_yields_no_missing_field_case(small):
    make_thing = small.operations[1]
    cases = cases_for(make_thing, small)
    assert [case.kind for case in cases] == ["positive", "no_credentials"]
    assert cases[0].body == {"name": "new", "size": 2}


def test_saved_responses_give_the_success_and_its_schema(small):
    get_thing = small.operations[0]
    assert get_thing.success_status == 200
    assert get_thing.success.content_type == "application/json"
    assert get_thing.success.schema == {"$ref": "#/components/schemas/GetThingResponse"}
    assert small.schemas["GetThingResponse"]["properties"]["tags"] == {"type": "array", "items": {"type": "string"}}
    assert small.schemas["GetThingResponse"]["properties"]["owner"] == {}
    assert small.operations[1].success.status == "2XX"
    assert small.operations[1].success.schema is None


def test_infer_schema():
    assert infer_schema({"a": 1, "b": 2.5, "c": True, "d": "x", "e": None, "f": [], "g": {}}) == {
        "type": "object",
        "properties": {
            "a": {"type": "integer"}, "b": {"type": "number"}, "c": {"type": "boolean"}, "d": {"type": "string"},
            "e": {}, "f": {"type": "array"}, "g": {"type": "object"},
        },
        "required": ["a", "b", "c", "d", "e", "f", "g"],
    }
    assert infer_schema([{"x": 1}]) == {
        "type": "array",
        "items": {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]},
    }


def test_infer_schema_without_required_lists_none_at_any_level():
    assert infer_schema({"a": 1, "b": [{"c": {"d": True}}]}, required=False) == {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"c": {"type": "object", "properties": {"d": {"type": "boolean"}}}},
                },
            },
        },
    }


def test_other_schemas_are_refused(tmp_path):
    path = tmp_path / "v1.json"
    v1_schema = "https://schema.getpostman.com/json/collection/v1.0.0/"
    path.write_text(json.dumps({"info": {"schema": v1_schema}, "item": []}))
    with pytest.raises(SpecError, match="v2.0 or v2.1"):
        load_postman(path)


def test_postman_echo_facts():
    api = load_postman(FIXTURES / "postman-echo.postman_collection.json")
    assert api.title == "Postman Echo (V2)"
    assert api.base_url == "https://postman-echo.com"
    assert len(api.operations) == 22
    assert api.tags == (
        "Auth: Digest", "Auth: Others", "Cookies", "Headers", "Request Methods", "Utilities", "[draft] Auth: OAuth2.0",
    )
    assert api.security.kind == "basic"
    by_id = {op.operation_id: op for op in api.operations}
    assert by_id["basic_auth"].secured is True
    assert by_id["digest_auth_success"].secured is False  # digest is not a scheme the suite can send
    assert by_id["basic_auth"].success_status == 200
    assert by_id["basic_auth"].success.is_json is True
    assert api.schemas["BasicAuthResponse"] == {
        "type": "object", "properties": {"authenticated": {"type": "boolean"}}, "required": ["authenticated"],
    }
    cookie_query = by_id["set_cookies"].parameters_in("query")
    assert [(p.name, p.examples) for p in cookie_query] == [("foo1", ("bar1",)), ("foo2", ("bar2",))]
    assert by_id["post_request"].body.content_type == "text/plain"
    assert by_id["post_request"].body.examples[0].startswith("Duis")
    assert by_id["get_request"].body is None
    assert by_id["get_request"].success.status == "2XX"

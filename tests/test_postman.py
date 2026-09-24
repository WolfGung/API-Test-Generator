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


def test_an_item_that_is_not_a_list_is_refused_naming_the_folder(tmp_path):
    v2_1 = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
    path = tmp_path / "folder.postman_collection.json"
    path.write_text(json.dumps({"info": {"name": "F", "schema": v2_1}, "item": [{"name": "Things", "item": None}]}))
    with pytest.raises(SpecError, match="folder 'Things': 'item' is not a list"):
        load_postman(path)
    path.write_text(json.dumps({"info": {"name": "F", "schema": v2_1}, "item": None}))
    with pytest.raises(SpecError, match="the collection's 'item' is not a list"):
        load_postman(path)


def query_of(api):
    return [(p.name, p.examples[0]) for p in api.operations[0].parameters_in("query")]


def test_a_query_entry_marked_disabled_is_not_sent_even_when_the_raw_url_carries_it(tmp_path):
    """Postman keeps a switched-off query entry in `url.query` with `disabled: true` and leaves it in `raw` as
    well; the request Postman sends does not carry it, and neither must the generated one."""
    api = _load_url(tmp_path, {
        "raw": "https://api.example.com/things?verbose=true&debug=1",
        "host": ["api", "example", "com"],
        "path": ["things"],
        "query": [{"key": "verbose", "value": "true"}, {"key": "debug", "value": "1", "disabled": True}],
    })
    assert query_of(api) == [("verbose", "true")]
    assert api.operations[0].path == "/things"


def test_when_raw_and_query_disagree_the_query_entries_decide_what_is_sent(tmp_path):
    api = _load_url(tmp_path, {
        "raw": "https://api.example.com/things?a=1",
        "query": [{"key": "a", "value": "2"}, {"key": "b", "value": None}, {"key": "", "value": "ignored"}],
    })
    assert query_of(api) == [("a", "2"), ("b", "")]
    only_disabled = _load_url(tmp_path, {
        "raw": "https://api.example.com/things?debug=1",
        "query": [{"key": "debug", "value": "1", "disabled": True}],
    })
    assert query_of(only_disabled) == []
    from_raw = _load_url(tmp_path, {"raw": "https://api.example.com/things?a=1&b", "query": []})
    assert query_of(from_raw) == [("a", "1"), ("b", "")]


@pytest.mark.parametrize(
    "url, path, query",
    [
        ("{{env}}.api.example.com/things/:id", "/things/{id}", []),
        ("{{host}}:8080/things?x=1", "/things", [("x", "1")]),
        ("{{scheme}}://{{host}}/things", "/things", []),
        ("{{baseUrl}}?x=1", "/", [("x", "1")]),
        ("{{env}}.api.example.com", "/", []),
    ],
)
def test_an_unresolved_variable_leading_the_host_takes_the_whole_label_with_it(tmp_path, url, path, query):
    """`{{env}}.api.example.com/things` names an origin the collection cannot resolve, not a path: the whole
    label up to the path is left for the suite's base URL to supply, so no request goes to
    `/.api.example.com/things`."""
    api = _load_url(tmp_path, url)
    assert api.base_url == ""
    assert api.operations[0].path == path
    assert query_of(api) == query


def _load_items(tmp_path, items, auth=None, name="notes"):
    path = tmp_path / f"{name}.postman_collection.json"
    document = {
        "info": {"name": "Notes", "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"},
        "variable": [{"key": "known", "value": "resolved"}, {"key": "empty", "value": ""}],
        "item": items,
    }
    if auth is not None:
        document["auth"] = auth
    path.write_text(json.dumps(document))
    return load_postman(path)


def test_a_header_whose_value_holds_an_unresolved_variable_is_dropped_with_a_note(tmp_path):
    api = _load_items(tmp_path, [{
        "name": "Get Thing",
        "request": {
            "method": "GET", "url": "https://api.example.com/things",
            "header": [
                {"key": "X-Trace", "value": "{{trace}}"},
                {"key": "X-Mixed", "value": "id-{{trace}}-{{other}}"},
                {"key": "X-Known", "value": "{{known}}"},
                {"key": "X-Plain", "value": "abc"},
            ],
        },
    }])
    headers = [(p.name, p.examples[0]) for p in api.operations[0].parameters_in("header")]
    assert headers == [("X-Known", "resolved"), ("X-Plain", "abc")]
    assert api.notes == (
        "get_thing: header 'X-Trace' is not sent; {{trace}} is not a collection variable",
        "get_thing: header 'X-Mixed' is not sent; {{trace}} is not a collection variable",
    )


def test_an_unsupported_auth_with_no_supported_one_leaves_a_note(tmp_path):
    ping = {"name": "Ping", "request": {"method": "GET", "url": "https://api.example.com/ping"}}
    digest = _load_items(tmp_path, [ping], auth={"type": "digest", "digest": []}, name="digest")
    assert digest.security.kind == "none" and digest.operations[0].secured is False
    assert digest.notes == ("digest auth is not supported; the suite sends no credentials",)
    fields = [{"key": "key", "value": "api_key"}, {"key": "in", "value": "query"}]
    keyed = _load_items(tmp_path, [ping], auth={"type": "apikey", "apikey": fields}, name="keyed")
    assert keyed.notes == ("apikey in query auth is not supported; the suite sends no credentials",)
    mixed = _load_items(
        tmp_path,
        [ping, {**ping, "name": "Pong", "request": {**ping["request"], "auth": {"type": "bearer", "bearer": []}}}],
        auth={"type": "oauth2", "oauth2": []}, name="mixed",
    )
    assert mixed.security.kind == "bearer" and mixed.notes == ()


def test_a_body_mode_the_loader_does_not_know_is_written_skipped(tmp_path):
    api = _load_items(tmp_path, [{
        "name": "Query",
        "request": {
            "method": "POST", "url": "https://api.example.com/graphql",
            "body": {"mode": "graphql", "graphql": {"query": "{ things { id } }", "variables": ""}},
        },
    }])
    body = api.operations[0].body
    assert body.content_type == "graphql (a Postman body mode)" and body.is_json is False
    [only] = cases_for(api.operations[0], api)
    assert only.skip_reason == "request body is graphql (a Postman body mode), which the generator does not produce"
    assert only.body is None


@pytest.mark.parametrize(
    "url, path, query, notes",
    [
        ("{{baseUrl}}/things", "/things", [], ()),
        ("{{baseUrl}}api/things?x=1", "/api/things", [("x", "1")], ()),
        (
            "{{env}}.api.example.com/things", "/things", [],
            ("op: '{{env}}.api.example.com' is not part of the path; it is the origin, which API_BASE_URL supplies",),
        ),
        (
            "{{host}}:8080/things", "/things", [],
            ("op: '{{host}}:8080' is not part of the path; it is the origin, which API_BASE_URL supplies",),
        ),
        (
            "{{scheme}}://{{host}}/things", "/things", [],
            ("op: '{{scheme}}://{{host}}' is not part of the path; it is the origin, which API_BASE_URL supplies",),
        ),
    ],
)
def test_text_after_a_leading_variable_is_the_origin_only_when_it_looks_like_a_host_label(
    tmp_path, url, path, query, notes
):
    """`{{baseUrl}}api/things` with `baseUrl = https://x.example/` is the path `/api/things`: `api` holds no `.`
    or `:`, so it is the first path segment, not a host label. A label that does look like one is folded into
    the origin, and a note names what was folded; the plain `{{baseUrl}}/things` folds nothing and says nothing."""
    api = _load_url(tmp_path, url)
    assert api.base_url == ""
    assert api.operations[0].path == path
    assert query_of(api) == query
    assert api.notes == notes


def test_a_query_value_holding_an_unresolved_variable_is_dropped_with_a_note(tmp_path):
    """The header rule, for the query: `{{trace}}` is never a query value, whether the entry comes from `url.query`
    or from the raw URL alone."""
    trace_note = "get_thing: query parameter 'trace' is not sent; {{trace}} is not a collection variable"
    structured = _load_items(tmp_path, [{
        "name": "Get Thing",
        "request": {
            "method": "GET",
            "url": {
                "raw": "https://api.example.com/things?trace={{trace}}&x=1&k={{known}}",
                "query": [
                    {"key": "trace", "value": "{{trace}}"},
                    {"key": "x", "value": "1"},
                    {"key": "k", "value": "{{known}}"},
                ],
            },
        },
    }], name="structured")
    assert query_of(structured) == [("x", "1"), ("k", "resolved")]
    assert structured.notes == (trace_note,)
    raw = _load_items(tmp_path, [{
        "name": "Get Thing",
        "request": {"method": "GET", "url": "https://api.example.com/things?trace={{trace}}&x=1&k={{known}}"},
    }], name="raw")
    assert query_of(raw) == [("x", "1"), ("k", "resolved")]
    assert raw.notes == (trace_note,)


def test_a_request_on_another_host_is_folded_onto_the_first_origin_with_a_note(tmp_path):
    """A suite has one base URL, the first origin the collection names; a request on another host still goes
    there, and the note says which request and which host."""
    api = _load_items(tmp_path, [
        {"name": "Ping", "request": {"method": "GET", "url": "https://api.example.com/ping"}},
        {"name": "Pong", "request": {"method": "GET", "url": "https://other.example.com:8443/pong"}},
        {"name": "Relative", "request": {"method": "GET", "url": "{{baseUrl}}/relative"}},
        {"name": "Same", "request": {"method": "GET", "url": "https://api.example.com/same"}},
    ])
    assert api.base_url == "https://api.example.com"
    assert [op.path for op in api.operations] == ["/ping", "/pong", "/relative", "/same"]
    assert api.notes == (
        "pong: sent to https://api.example.com, not to https://other.example.com:8443: "
        "a suite has one base URL, the first the collection names",
    )


@pytest.mark.parametrize(
    "url, path, query, notes",
    [
        (
            "https://{{host}}/things", "/things", [],
            ("op: 'https://{{host}}' is not the origin; {{host}} is not a collection variable, "
             "so API_BASE_URL supplies the origin",),
        ),
        (
            "api.{{env}}.example.com/things?x=1", "/things", [("x", "1")],
            ("op: 'http://api.{{env}}.example.com' is not the origin; {{env}} is not a collection variable, "
             "so API_BASE_URL supplies the origin",),
        ),
        (
            "https://{{host}}:{{port}}/things/:id", "/things/{id}", [],
            ("op: 'https://{{host}}:{{port}}' is not the origin; {{host}} is not a collection variable, "
             "so API_BASE_URL supplies the origin",),
        ),
    ],
)
def test_a_host_still_holding_an_unresolved_variable_after_the_scheme_is_not_the_origin(
    tmp_path, url, path, query, notes
):
    """`https://{{host}}/things` used to give the suite `https://{{host}}` as its base URL, silently. The leading-
    variable rule applies to a variable anywhere in the host: the origin is left for API_BASE_URL to supply, and
    a note names the request and the variable."""
    api = _load_url(tmp_path, url)
    assert api.base_url == ""
    assert api.operations[0].path == path
    assert query_of(api) == query
    assert api.notes == notes


def test_a_query_key_holding_an_unresolved_variable_is_dropped_with_a_note(tmp_path):
    """The value rule, for the key: a pair keyed `{{k}}` is not sent under that literal name, whether it comes from
    `url.query` or from the raw URL alone; a key that is a collection variable is sent under its resolved name."""
    key_note = "get_thing: query parameter '{{k}}' is not sent; {{k}} is not a collection variable"
    structured = _load_items(tmp_path, [{
        "name": "Get Thing",
        "request": {
            "method": "GET",
            "url": {
                "raw": "https://api.example.com/things?{{k}}=1&x=1&{{known}}=2",
                "query": [
                    {"key": "{{k}}", "value": "1"},
                    {"key": "x", "value": "1"},
                    {"key": "{{known}}", "value": "2"},
                ],
            },
        },
    }], name="structured")
    assert query_of(structured) == [("x", "1"), ("resolved", "2")]
    assert structured.notes == (key_note,)
    raw = _load_items(tmp_path, [{
        "name": "Get Thing",
        "request": {"method": "GET", "url": "https://api.example.com/things?{{k}}=1&x=1&{{known}}=2"},
    }], name="raw")
    assert query_of(raw) == [("x", "1"), ("resolved", "2")]
    assert raw.notes == (key_note,)


def test_a_header_key_holding_an_unresolved_variable_is_dropped_with_a_note(tmp_path):
    """The value rule, for the key: a header keyed `{{hk}}` is not sent under that literal name, and a note names
    the request and the variable; a key that is a collection variable is sent under its resolved name."""
    api = _load_items(tmp_path, [{
        "name": "Get Thing",
        "request": {
            "method": "GET",
            "url": "https://api.example.com/things",
            "header": [
                {"key": "{{hk}}", "value": "1"},
                {"key": "X-{{hk}}-{{other}}", "value": "2"},
                {"key": "{{known}}", "value": "3"},
                {"key": "X-Plain", "value": "4"},
            ],
        },
    }])
    headers = [(p.name, p.examples[0]) for p in api.operations[0].parameters_in("header")]
    assert headers == [("resolved", "3"), ("X-Plain", "4")]
    assert api.notes == (
        "get_thing: header '{{hk}}' is not sent; {{hk}} is not a collection variable",
        "get_thing: header 'X-{{hk}}-{{other}}' is not sent; {{hk}} is not a collection variable",
    )


def test_a_query_key_that_resolves_to_an_empty_name_is_dropped_with_a_note(tmp_path):
    """A key that is a collection variable set to "" (`{{empty}}`), or an empty literal key (`=2`), names no
    parameter: the pair is not sent and a note names the request and the key as the collection spelt it,
    whether the pair comes from `url.query` or from the raw URL alone."""
    empty_notes = (
        "get_thing: query parameter '{{empty}}' is not sent; it resolves to an empty name",
        "get_thing: query parameter '' is not sent; it resolves to an empty name",
    )
    structured = _load_items(tmp_path, [{
        "name": "Get Thing",
        "request": {
            "method": "GET",
            "url": {
                "raw": "https://api.example.com/things?{{empty}}=1&=2&x=3",
                "query": [
                    {"key": "{{empty}}", "value": "1"},
                    {"key": "", "value": "2"},
                    {"key": "x", "value": "3"},
                ],
            },
        },
    }], name="structured")
    assert query_of(structured) == [("x", "3")]
    assert structured.notes == empty_notes
    raw = _load_items(tmp_path, [{
        "name": "Get Thing",
        "request": {"method": "GET", "url": "https://api.example.com/things?{{empty}}=1&=2&x=3"},
    }], name="raw")
    assert query_of(raw) == [("x", "3")]
    assert raw.notes == empty_notes


def test_a_header_key_that_resolves_to_an_empty_name_is_dropped_with_a_note(tmp_path):
    """The query rule, for a header: `{{empty}}: 1` and `: 2` name no header, so neither is sent and a note names
    the request and the key as the collection spelt it - from the list form and from the string form alike."""
    empty_notes = (
        "get_thing: header '{{empty}}' is not sent; it resolves to an empty name",
        "get_thing: header '' is not sent; it resolves to an empty name",
    )
    listed = _load_items(tmp_path, [{
        "name": "Get Thing",
        "request": {
            "method": "GET",
            "url": "https://api.example.com/things",
            "header": [{"key": "{{empty}}", "value": "1"}, {"key": "", "value": "2"}, {"key": "X-Plain", "value": "3"}],
        },
    }], name="listed")
    assert [(p.name, p.examples[0]) for p in listed.operations[0].parameters_in("header")] == [("X-Plain", "3")]
    assert listed.notes == empty_notes
    spelt = _load_items(tmp_path, [{
        "name": "Get Thing",
        "request": {
            "method": "GET",
            "url": "https://api.example.com/things",
            "header": "{{empty}}: 1\n: 2\n\nX-Plain: 3\n",
        },
    }], name="spelt")
    assert [(p.name, p.examples[0]) for p in spelt.operations[0].parameters_in("header")] == [("X-Plain", "3")]
    assert spelt.notes == empty_notes

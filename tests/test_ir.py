from api_test_gen.ir import Body, Response, is_json_media


def test_is_json_media_ignores_parameters_case_and_suffix():
    assert is_json_media("application/json; charset=utf-8") is True
    assert is_json_media("APPLICATION/JSON") is True
    assert is_json_media("application/vnd.api+json") is True
    assert is_json_media("text/plain") is False
    assert is_json_media(None) is False


def test_body_and_response_is_json_delegate_to_is_json_media():
    assert Body(content_type="application/json; charset=utf-8", schema={}, required=True).is_json is True
    assert Response(status="200", schema=None, content_type="application/json; charset=utf-8").is_json is True
    assert Response(status="200", schema=None, content_type=None).is_json is False

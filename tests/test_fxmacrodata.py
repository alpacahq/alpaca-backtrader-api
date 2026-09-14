from unittest import mock

from alpaca_backtrader_api.fxmacrodata import FXMacroDataClient


def _fake_response(payload=b"{}"):
    resp = mock.MagicMock()
    resp.read.return_value = payload
    resp.__enter__.return_value = resp
    return resp


def test_request_forwards_zero_timeout():
    client = FXMacroDataClient(api_key="", base_url="https://example.test/v1")
    with mock.patch(
        "urllib.request.urlopen", return_value=_fake_response()
    ) as urlopen:
        client.request("calendar/usd", timeout=0)
    assert urlopen.call_args.kwargs["timeout"] == 0


def test_request_uses_client_timeout_when_not_overridden():
    client = FXMacroDataClient(
        api_key="", base_url="https://example.test/v1", timeout=7
    )
    with mock.patch(
        "urllib.request.urlopen", return_value=_fake_response()
    ) as urlopen:
        client.request("calendar/usd")
    assert urlopen.call_args.kwargs["timeout"] == 7


def test_request_builds_url_with_query_and_api_key():
    client = FXMacroDataClient(
        api_key="test-key", base_url="https://example.test/v1"
    )
    with mock.patch(
        "urllib.request.urlopen", return_value=_fake_response(b'{"a": 1}')
    ) as urlopen:
        result = client.request("/calendar/usd", {"limit": 5})
    req = urlopen.call_args.args[0]
    assert req.full_url == (
        "https://example.test/v1/calendar/usd?limit=5&api_key=test-key"
    )
    assert result == {"a": 1}

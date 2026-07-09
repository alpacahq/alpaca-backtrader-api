import json
import os
import urllib.error
import urllib.parse
import urllib.request


class FXMacroDataClient:
    """Client for adding macro, calendar, COT, and FX context to strategies."""

    DEFAULT_BASE_URL = "https://fxmacrodata.com/api/v1/"

    def __init__(self, api_key=None, base_url=None, timeout=30):
        self.api_key = (
            api_key
            or os.getenv("FXMACRODATA_API_KEY")
            or os.getenv("FXMD_API_KEY")
            or ""
        )
        self.base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/") + "/"
        self.timeout = timeout

    def request(self, path, params=None, timeout=None):
        query = dict(params or {})
        if self.api_key:
            query["api_key"] = self.api_key
        url = urllib.parse.urljoin(self.base_url, path.lstrip("/"))
        if query:
            url = url + "?" + urllib.parse.urlencode(query)

        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                payload = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(
                "FXMacroData request failed with HTTP {}: {}".format(
                    exc.code, body
                )
            )
        return json.loads(payload)

    def data_catalogue(self, currency):
        return self.request("data_catalogue/" + currency.lower())

    def announcements(self, currency, indicator, **params):
        path = "announcements/{}/{}".format(currency.lower(), indicator)
        return self.request(path, params)

    def latest_announcements(self, currency, **params):
        path = "announcements/{}/latest".format(currency.lower())
        return self.request(path, params)

    def calendar(self, currency, **params):
        return self.request("calendar/" + currency.lower(), params)

    def predictions(self, currency, indicator, **params):
        path = "predictions/{}/{}".format(currency.lower(), indicator)
        return self.request(path, params)

    def forex(self, base, quote="usd", **params):
        path = "forex/{}/{}".format(base.lower(), quote.lower())
        return self.request(path, params)

    def cot(self, currency, **params):
        return self.request("cot/" + currency.lower(), params)

    def commodity(self, indicator, **params):
        return self.request("commodities/" + indicator, params)

    def commodities_latest(self, **params):
        return self.request("commodities/latest", params)

    def rate_differentials(self, base, quote="usd", **params):
        path = "rate_differentials/{}/{}".format(base.lower(), quote.lower())
        return self.request(path, params)

    def market_sessions(self, **params):
        return self.request("market_sessions", params)

    def risk_sentiment(self, **params):
        return self.request("risk_sentiment", params)

    def macro_context(self, base, quote="usd", indicator="policy_rate", limit=10):
        return {
            "base_catalogue": self.data_catalogue(base),
            "quote_catalogue": self.data_catalogue(quote),
            "base_calendar": self.calendar(base, limit=limit),
            "quote_calendar": self.calendar(quote, limit=limit),
            "base_announcements": self.announcements(
                base, indicator, limit=limit
            ),
            "quote_announcements": self.announcements(
                quote, indicator, limit=limit
            ),
            "forex": self.forex(base, quote, limit=limit),
        }

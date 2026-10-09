"""Hermetic MediaWiki client tests for provenance and HTML cleanup."""

from __future__ import annotations

import time

import httpx
import pytest

from app.rag.wiki import MediaWikiClient, WikiError, WikiPageReference, WikiUnavailableError


def _client(handler) -> MediaWikiClient:
    return _client_config(handler, max_retries=0)


def _client_config(
    handler,
    *,
    max_retries: int = 2,
    failure_threshold: int = 0,
    cooldown_seconds: float = 0.0,
) -> MediaWikiClient:
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport)
    return MediaWikiClient(
        client=http_client,
        timeout_seconds=2,
        max_retries=max_retries,
        failure_threshold=failure_threshold,
        cooldown_seconds=cooldown_seconds,
    )


def test_search_uses_focused_terms_and_preserves_page_ids():
    searches: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        assert request.headers["User-Agent"].startswith("Termina-Companion/")
        if params["action"] == "query" and params.get("list") == "search":
            searches.append(params["srsearch"])
            return httpx.Response(
                200,
                json={
                    "query": {
                        "search": [
                            {
                                "pageid": 4819,
                                "title": "Anju's Anguish",
                                "snippet": "Kafei and Anju",
                                "timestamp": "2026-01-01T00:00:00Z",
                                "wordcount": 100,
                            }
                        ]
                    }
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = _client(handler)
    try:
        result = client.search(
            "Reunite Anju and Kafei before dawn",
            limit=1,
            terms=["Anju", "Kafei"],
        )
    finally:
        client.close()

    assert result == [
        WikiPageReference(
            page_id=4819,
            title="Anju's Anguish",
            snippet="Kafei and Anju",
            timestamp="2026-01-01T00:00:00Z",
            wordcount=100,
        )
    ]
    assert searches == ["Anju", "Kafei"]


def test_search_decomposes_long_query_without_structured_terms():
    searches: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        searches.append(request.url.params["srsearch"])
        return httpx.Response(
            200,
            json={
                "query": {"search": [{"pageid": 4819, "title": "Anju's Anguish", "wordcount": 100}]}
            },
        )

    client = _client(handler)
    try:
        client.search("Find Anju and Kafei before dawn", limit=1)
    finally:
        client.close()

    assert searches == ["Anju", "Kafei", "dawn"]


def test_fetch_pages_resolves_redirect_and_preserves_revision_license():
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params["action"] == "query" and params.get("meta") == "siteinfo":
            return httpx.Response(
                200,
                json={
                    "query": {
                        "general": {"lang": "en"},
                        "rightsinfo": {
                            "text": "GNU Free Documentation License 1.3",
                            "url": "https://zeldawiki.wiki/wiki/Zelda_Wiki:GNU_Free_Documentation_License",
                        },
                    }
                },
            )
        if params["action"] == "query" and params.get("pageids"):
            assert params["redirects"] == "1"
            return httpx.Response(
                200,
                json={
                    "query": {
                        "redirects": [
                            {
                                "from": "Redirect to Anju's Anguish",
                                "to": "Anju's Anguish",
                            }
                        ],
                        "pages": [
                            {
                                "pageid": 200,
                                "title": "Anju's Anguish",
                                "revisions": [
                                    {
                                        "revid": 777,
                                        "timestamp": "2026-02-03T04:05:06Z",
                                    }
                                ],
                                "categories": [{"title": "Category:Quests"}],
                            }
                        ],
                    }
                },
            )
        if params["action"] == "parse":
            assert params["pageid"] == "200"
            return httpx.Response(
                200,
                json={
                    "parse": {
                        "title": "Anju's Anguish",
                        "revid": 777,
                        "text": """
                        <div class=\"mw-parser-output\">
                          <style>.noise { color: red; }</style>
                          <h2>Plot</h2>
                          <p>Kafei and Anju reunite.</p>
                          <div class=\"references\"><sup>1</sup> noise</div>
                          <div class=\"mbox\">This article may be deleted.</div>
                        </div>
                        """,
                    }
                },
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = _client(handler)
    try:
        documents = client.fetch_pages(
            [WikiPageReference(page_id=100, title="Redirect to Anju's Anguish")]
        )
    finally:
        client.close()

    assert len(documents) == 1
    document = documents[0]
    assert document.id == "wiki:200"
    assert document.metadata.source_page_id == 200
    assert document.metadata.source_revision_id == 777
    assert document.metadata.source_revision_timestamp == "2026-02-03T04:05:06Z"
    assert document.metadata.source_url.endswith("oldid=777")
    assert document.metadata.source_urls == [document.metadata.source_url]
    assert document.metadata.canonical_url.endswith("/wiki/Anju's_Anguish")
    assert document.metadata.license_note == "GNU Free Documentation License 1.3"
    assert document.metadata.license_url
    assert document.metadata.language == "en"
    assert document.metadata.retrieved_at
    assert "## Plot" in document.content
    assert "Kafei and Anju reunite." in document.content
    assert "noise" not in document.content
    assert "deleted" not in document.content


def test_fetch_pages_reports_api_error_as_wiki_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"error": {"code": "badrequest", "info": "invalid page"}},
        )

    client = _client(handler)
    try:
        with pytest.raises(WikiError, match="invalid page"):
            client.fetch_pages([WikiPageReference(page_id=1, title="Missing")])
    finally:
        client.close()


def test_fetch_pages_handles_empty_redirect_page_as_no_document():
    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("meta") == "siteinfo":
            return httpx.Response(
                200,
                json={
                    "query": {
                        "general": {"lang": "en"},
                        "rightsinfo": {"text": "GFDL"},
                    }
                },
            )
        if params.get("pageids"):
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {
                                "pageid": 1,
                                "title": "Empty",
                                "revisions": [{"revid": 2, "timestamp": "2026-01-01T00:00:00Z"}],
                            }
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={"parse": {"title": "Empty", "revid": 2, "text": "<div></div>"}},
        )

    client = _client(handler)
    try:
        assert client.fetch_pages([WikiPageReference(page_id=1, title="Empty")]) == []
    finally:
        client.close()


def test_fetch_pages_keeps_page_when_siteinfo_unavailable():
    """License attribution is best-effort and must not block page text."""

    def handler(request: httpx.Request) -> httpx.Response:
        params = request.url.params
        if params.get("meta") == "siteinfo":
            return httpx.Response(
                200,
                json={"error": {"code": "readapidenied", "info": "no siteinfo"}},
            )
        if params.get("pageids"):
            return httpx.Response(
                200,
                json={
                    "query": {
                        "pages": [
                            {
                                "pageid": 1,
                                "title": "Anju",
                                "revisions": [{"revid": 5, "timestamp": "2026-01-01T00:00:00Z"}],
                            }
                        ]
                    }
                },
            )
        return httpx.Response(
            200,
            json={"parse": {"title": "Anju", "revid": 5, "text": "<div><p>Text.</p></div>"}},
        )

    client = _client(handler)
    try:
        documents = client.fetch_pages([WikiPageReference(page_id=1, title="Anju")])
    finally:
        client.close()

    assert len(documents) == 1
    assert documents[0].metadata.license_note == ""
    assert documents[0].metadata.source_revision_id == 5


def test_search_budget_exhausted_without_network():
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may leave after the deadline")

    client = _client(handler)
    try:
        with pytest.raises(WikiError, match="budget"):
            client.search("Anju Kafei", terms=["Anju"], deadline=time.monotonic() - 1)
    finally:
        client.close()


def test_current_revisions_maps_page_ids():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["prop"] == "revisions"
        return httpx.Response(
            200,
            json={
                "query": {
                    "pages": [
                        {"pageid": 1, "revisions": [{"revid": 42}]},
                        {"pageid": 2, "revisions": [{"revid": 43}]},
                    ]
                }
            },
        )

    client = _client(handler)
    try:
        assert client.current_revisions([1, 2, 2]) == {1: 42, 2: 43}
    finally:
        client.close()


def test_read_timeout_fails_fast_without_retries():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("slow", request=request)

    client = _client_config(handler, max_retries=2)
    try:
        with pytest.raises(WikiUnavailableError):
            client.search("Anju", terms=["Anju"])
    finally:
        client.close()

    assert calls == 1


def test_connect_timeout_keeps_bounded_retries():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectTimeout("connect", request=request)

    client = _client_config(handler, max_retries=2)
    try:
        with pytest.raises(WikiUnavailableError):
            client.search("Anju", terms=["Anju"])
    finally:
        client.close()

    assert calls == 3


def test_server_error_is_unreachable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="maintenance")

    client = _client_config(handler, max_retries=0)
    try:
        with pytest.raises(WikiUnavailableError):
            client.search("Anju", terms=["Anju"])
    finally:
        client.close()


def test_not_found_is_a_reachable_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    client = _client_config(handler, max_retries=0)
    try:
        with pytest.raises(WikiError) as excinfo:
            client.search("Anju", terms=["Anju"])
    finally:
        client.close()

    assert not isinstance(excinfo.value, WikiUnavailableError)


def test_circuit_breaker_opens_and_skips_network():
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        raise httpx.ConnectError("down", request=request)

    client = _client_config(handler, max_retries=0, failure_threshold=1, cooldown_seconds=60)
    try:
        with pytest.raises(WikiUnavailableError):
            client.search("Anju", terms=["Anju"])
        assert calls == 1

        with pytest.raises(WikiUnavailableError, match="circuit"):
            client.search("Anju", terms=["Anju"])
        assert calls == 1
    finally:
        client.close()


def test_circuit_breaker_half_open_recovers_after_cooldown():
    calls = 0
    failing = True

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failing:
            raise httpx.ConnectError("down", request=request)
        return httpx.Response(
            200,
            json={"query": {"search": [{"pageid": 1, "title": "Anju", "wordcount": 10}]}},
        )

    client = _client_config(handler, max_retries=0, failure_threshold=1, cooldown_seconds=60)
    try:
        with pytest.raises(WikiUnavailableError):
            client.search("Anju", terms=["Anju"])

        failing = False
        client._open_until = time.monotonic() - 1  # cooldown elapsed → half-open
        references = client.search("Anju", terms=["Anju"])
        assert [reference.page_id for reference in references] == [1]

        # The successful probe closes the breaker again.
        client.search("Anju", terms=["Anju"])
        assert calls == 3
    finally:
        client.close()

"""MediaWiki client for on-demand Zelda Wiki ingestion."""

from __future__ import annotations

import html as html_lib
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup, Comment
from markdownify import markdownify
from pydantic import BaseModel

from app.rag.models import Document, SourceMetadata

logger = logging.getLogger(__name__)

DEFAULT_WIKI_API_URL = "https://zeldawiki.wiki/w/api.php"
DEFAULT_WIKI_USER_AGENT = "Termina-Companion/0.1 (https://github.com/termina-companion)"

_UNWANTED_SELECTORS = (
    "script",
    "style",
    "noscript",
    "link",
    "meta",
    "form",
    "button",
    ".mw-editsection",
    ".mw-jump",
    ".navbox",
    ".vertical-navbox",
    ".mw-references-wrap",
    ".references",
    ".reflist",
    ".gallery",
    ".thumb",
    ".mbox",
    ".dablink",
    ".shortdescription",
    ".mw-indicators",
    ".noprint",
)
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)
_SEARCH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "at",
    "before",
    "bring",
    "find",
    "from",
    "get",
    "give",
    "i",
    "in",
    "learn",
    "need",
    "obtain",
    "of",
    "reunite",
    "take",
    "the",
    "to",
    "want",
    "where",
    "with",
}


class WikiError(RuntimeError):
    """Raised when the wiki cannot be searched or fetched."""


class WikiPageReference(BaseModel):
    """Search result used to identify a wiki page without fetching its text."""

    page_id: int
    title: str
    snippet: str = ""
    timestamp: str = ""
    wordcount: int = 0


class WikiRights(BaseModel):
    """License and language metadata returned by MediaWiki siteinfo."""

    text: str
    url: str = ""
    language: str = ""


class MediaWikiClient:
    """Small, polite MediaWiki API client with HTML cleanup and provenance."""

    def __init__(
        self,
        api_url: str = DEFAULT_WIKI_API_URL,
        user_agent: str = DEFAULT_WIKI_USER_AGENT,
        timeout_seconds: float = 20,
        client: httpx.Client | None = None,
        max_retries: int = 2,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_retries < 0:
            raise ValueError("max_retries must be non-negative")
        self.api_url = api_url
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self._owns_client = client is None
        self._client = (
            client
            if client is not None
            else httpx.Client(
                timeout=timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": user_agent},
            )
        )
        self._rights: WikiRights | None = None
        self._article_base = _article_base(api_url)

    def search(
        self,
        query: str,
        limit: int = 3,
        terms: list[str] | tuple[str, ...] | None = None,
    ) -> list[WikiPageReference]:
        """Search page references using focused MediaWiki queries.

        MediaWiki's default search requires too many terms to match when given
        a complete player goal. The Knowledge Agent supplies salient entity
        phrases separately; this method also derives a small fallback set.
        """
        if limit <= 0:
            return []
        queries = _search_queries(query, terms)
        if not queries:
            return []
        found: dict[int, WikiPageReference] = {}
        errors: list[Exception] = []
        for search_query in queries:
            try:
                payload = self._request(
                    {
                        "action": "query",
                        "list": "search",
                        "srsearch": search_query,
                        "srnamespace": 0,
                        # Gather a wider candidate set, then rank it locally
                        # before applying the bounded page-ingestion limit.
                        "srlimit": 10,
                        "srprop": "snippet|timestamp|wordcount",
                    }
                )
            except WikiError as exc:
                errors.append(exc)
                logger.warning("Wiki search failed for %r: %s", search_query, exc)
                continue
            for item in payload.get("query", {}).get("search", []):
                try:
                    reference = WikiPageReference.model_validate(
                        {
                            "page_id": item["pageid"],
                            "title": item["title"],
                            "snippet": item.get("snippet", ""),
                            "timestamp": item.get("timestamp", ""),
                            "wordcount": item.get("wordcount", 0),
                        }
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    logger.warning("Ignoring malformed wiki search result: %s", exc)
                    continue
                previous = found.get(reference.page_id)
                if previous is None or reference.wordcount > previous.wordcount:
                    found[reference.page_id] = reference
        if not found and errors:
            raise errors[0]
        return _rank_references(list(found.values()), queries, limit)

    def fetch_pages(self, references: list[WikiPageReference]) -> list[Document]:
        """Fetch, clean and provenance-stamp pages for later vector indexing."""
        if not references:
            return []
        rights = self._get_rights()
        details, redirect_map = self._page_details(references)
        target_ids: list[int] = []
        for reference in references:
            target = _follow_redirect(reference.page_id, redirect_map)
            if target not in target_ids:
                target_ids.append(target)

        documents: list[Document] = []
        errors: list[Exception] = []
        retrieved_at = datetime.now(UTC).isoformat()
        for page_id in target_ids:
            page = details.get(page_id, {})
            try:
                document = self._fetch_one_page(page_id, page, rights, retrieved_at)
            except WikiError as exc:
                errors.append(exc)
                logger.warning("Ignoring wiki page %s: %s", page_id, exc)
                continue
            if document:
                documents.append(document)
        if not documents and errors:
            raise errors[0]
        return documents

    def _fetch_one_page(
        self,
        page_id: int,
        detail: dict[str, Any],
        rights: WikiRights,
        retrieved_at: str,
    ) -> Document | None:
        payload = self._request(
            {
                "action": "parse",
                "pageid": page_id,
                "prop": "text|revid|displaytitle",
                "disabletoc": 1,
                "disableeditsection": 1,
            }
        )
        parsed = payload.get("parse")
        if not isinstance(parsed, dict):
            raise WikiError(f"Wiki returned no parsed content for page {page_id}")
        raw_html = parsed.get("text")
        if not isinstance(raw_html, str) or not raw_html.strip():
            return None
        title = str(parsed.get("title") or detail.get("title") or f"Page {page_id}")
        content = _html_to_markdown(raw_html)
        if not content.strip():
            return None
        revision = _first_revision(detail)
        revision_id = parsed.get("revid") or revision.get("revid")
        try:
            revision_number = int(revision_id) if revision_id else None
        except (TypeError, ValueError) as exc:
            raise WikiError(f"Wiki returned an invalid revision ID for page {page_id}") from exc
        revision_timestamp = revision.get("timestamp", "")
        source_url = self._oldid_url(revision_number) if revision_number else self._page_url(title)
        metadata = SourceMetadata(
            id=f"wiki:{page_id}",
            title=title,
            source_type="wiki",
            source_url=source_url,
            source_urls=[source_url],
            canonical_url=self._page_url(title),
            source_page_id=page_id,
            source_revision_id=revision_number,
            source_revision_timestamp=revision_timestamp,
            retrieved_at=retrieved_at,
            language=rights.language,
            license_note=rights.text,
            license_url=rights.url,
            categories=[
                str(item.get("title", ""))
                for item in (detail.get("categories") or [])
                if isinstance(item, dict)
            ],
        )
        return Document(id=metadata.id, title=title, content=content, metadata=metadata)

    def _page_details(
        self, references: list[WikiPageReference]
    ) -> tuple[dict[int, dict[str, Any]], dict[int, int]]:
        page_ids = [reference.page_id for reference in references]
        payload = self._request(
            {
                "action": "query",
                "pageids": "|".join(str(page_id) for page_id in page_ids),
                "prop": "info|revisions|categories",
                "rvprop": "ids|timestamp",
                "cllimit": "max",
                "redirects": 1,
            }
        )
        pages = _pages_by_id(payload)
        source_titles = {reference.page_id: reference.title for reference in references}
        return pages, _redirect_map(payload, source_titles)

    def _get_rights(self) -> WikiRights:
        if self._rights is not None:
            return self._rights
        payload = self._request(
            {
                "action": "query",
                "meta": "siteinfo",
                "siprop": "general|rightsinfo",
            }
        )
        query = payload.get("query", {})
        rights = query.get("rightsinfo", {})
        general = query.get("general", {})
        text = str(rights.get("text", "")).strip()
        if not text:
            raise WikiError("Wiki siteinfo did not provide license information")
        self._rights = WikiRights(
            text=text,
            url=str(rights.get("url", "")).strip(),
            language=str(general.get("lang", "")).strip(),
        )
        return self._rights

    def _request(self, params: dict[str, Any]) -> dict[str, Any]:
        request_params = {"format": "json", "formatversion": 2, **params}
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._client.get(
                    self.api_url,
                    params=request_params,
                    headers={"User-Agent": self.user_agent},
                    timeout=self.timeout_seconds,
                )
                if response.status_code == 429 or response.status_code >= 500:
                    raise httpx.HTTPStatusError(
                        f"wiki HTTP {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                payload = response.json()
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                last_error = exc
                if attempt < self.max_retries:
                    time.sleep(min(0.25 * (2**attempt), 2.0))
                    continue
                break
            if not isinstance(payload, dict):
                last_error = WikiError("Wiki returned a non-object JSON response")
                break
            error = payload.get("error")
            if error:
                last_error = WikiError(_api_error_message(error))
                break
            return payload
        raise WikiError(f"Wiki request failed: {last_error}") from last_error

    def _page_url(self, title: str) -> str:
        page_title = title.replace(" ", "_")
        safe_characters = "()_'-!*"
        return f"{self._article_base}/{quote(page_title, safe=safe_characters)}"

    def _oldid_url(self, revision_id: int) -> str:
        index_url = f"{self._article_base[:-5]}/w/index.php"
        return f"{index_url}?oldid={revision_id}"

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> MediaWikiClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


def _search_queries(query: str, terms: list[str] | tuple[str, ...] | None) -> list[str]:
    """Build a bounded list of focused MediaWiki search queries."""
    candidates: list[str] = []
    query_tokens = _TOKEN_RE.findall(query)
    query_inputs = list(terms or []) + ([] if terms else [query])
    for term in query_inputs:
        normalized = " ".join(str(term).split()).strip()
        if not terms and len(query_tokens) > 4 and term == query:
            continue
        if not normalized or len(normalized) > 120 or not _is_meaningful_term(normalized):
            continue
        if normalized.casefold() not in {item.casefold() for item in candidates}:
            candidates.append(normalized)
        if len(candidates) >= 6:
            return candidates

    # A direct caller without structured terms can still search a short query.
    if not terms and len(query_tokens) <= 4 and _is_meaningful_term(query):
        if query.casefold() not in {item.casefold() for item in candidates}:
            candidates.append(" ".join(query.split()))
    if not candidates:
        candidates = [
            token
            for token in query_tokens
            if len(token) > 2 and token.casefold() not in _SEARCH_STOP_WORDS
        ][:6]
    return candidates


def _is_meaningful_term(value: str) -> bool:
    tokens = [token.casefold() for token in _TOKEN_RE.findall(value)]
    return bool(tokens) and any(token not in _SEARCH_STOP_WORDS for token in tokens)


def _rank_references(
    references: list[WikiPageReference], terms: list[str] | tuple[str, ...], limit: int
) -> list[WikiPageReference]:
    """Rank search hits by term coverage and useful page substance."""
    normalized_terms = [
        normalized for term in terms if (normalized := _normalized_phrase(str(term)))
    ]
    if not normalized_terms:
        normalized_terms = [_normalized_phrase(term) for term in references[:1]]

    ranked: list[tuple[float, int, WikiPageReference]] = []
    for reference in references:
        title = _normalized_phrase(reference.title)
        searchable = _normalized_phrase(f"{reference.title} {reference.snippet}")
        term_hits = sum(_contains_phrase(searchable, term) for term in normalized_terms)
        title_hits = sum(_contains_phrase(title, term) for term in normalized_terms)
        score = term_hits * 10.0 + title_hits * 6.0
        if term_hits == len(normalized_terms):
            score += 25.0
        # Prefer substantive pages over redirect stubs, while retaining a
        # redirect when its target title matches a focused search term.
        score += min(reference.wordcount, 5000) / 1000.0
        if "#redirect" in reference.snippet.casefold():
            score += 1.0
        ranked.append((score, reference.page_id, reference))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[:limit]]


def _normalized_phrase(value: str) -> str:
    return " ".join(_TOKEN_RE.findall(value.casefold()))


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def _pages_by_id(payload: dict[str, Any]) -> dict[int, dict[str, Any]]:
    result: dict[int, dict[str, Any]] = {}
    for page in payload.get("query", {}).get("pages", []):
        try:
            page_id = int(page["pageid"])
        except (KeyError, TypeError, ValueError):
            continue
        if page_id >= 0:
            result[page_id] = page
    return result


def _redirect_map(
    payload: dict[str, Any], source_titles: dict[int, str] | None = None
) -> dict[int, int]:
    """Map input page IDs to resolved IDs across MediaWiki API formats.

    With ``formatversion=2`` MediaWiki reports redirect ``from``/``to`` values
    as titles, while older responses may use numeric page IDs. Resolve both
    forms through the returned page list.
    """
    query = payload.get("query", {})
    pages = _pages_by_id(payload)
    title_to_id = {
        str(page.get("title")).casefold(): page_id
        for page_id, page in pages.items()
        if page.get("title")
    }
    source_title_to_id = {
        title.casefold(): page_id for page_id, title in (source_titles or {}).items()
    }
    result: dict[int, int] = {}
    for key in ("normalized", "redirects"):
        for item in query.get(key, []):
            if not isinstance(item, dict):
                continue
            from_value = item.get("fromid", item.get("from"))
            to_value = item.get("toid", item.get("to"))
            try:
                from_id = int(from_value)
            except (TypeError, ValueError):
                from_key = str(from_value).casefold()
                from_id = source_title_to_id.get(from_key, title_to_id.get(from_key, -1))
            try:
                to_id = int(to_value)
            except (TypeError, ValueError):
                to_id = title_to_id.get(str(to_value).casefold(), -1)
            if from_id >= 0 and to_id >= 0:
                result[from_id] = to_id
    return result


def _follow_redirect(page_id: int, redirects: dict[int, int]) -> int:
    seen: set[int] = set()
    current = page_id
    while current in redirects and current not in seen:
        seen.add(current)
        current = redirects[current]
    return current


def _first_revision(page: dict[str, Any]) -> dict[str, Any]:
    revisions = page.get("revisions", [])
    return revisions[0] if revisions and isinstance(revisions[0], dict) else {}


def _api_error_message(error: Any) -> str:
    if isinstance(error, dict):
        return str(error.get("info") or error.get("code") or error)
    return str(error)


def _article_base(api_url: str) -> str:
    parsed = urlsplit(api_url)
    if not parsed.scheme or not parsed.netloc:
        return api_url.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, "/wiki", "", ""))


def _html_to_markdown(raw_html: str) -> str:
    """Remove wiki chrome and convert one parsed page to readable Markdown."""
    soup = BeautifulSoup(raw_html, "html.parser")
    for node in soup.find_all(string=lambda value: isinstance(value, Comment)):
        node.extract()
    for selector in _UNWANTED_SELECTORS:
        for node in soup.select(selector):
            node.decompose()
    for image in soup.find_all("img"):
        image.decompose()
    markdown = markdownify(str(soup), heading_style="ATX", bullets="-")
    lines: list[str] = []
    for line in html_lib.unescape(markdown).splitlines():
        normalized = re.sub(r"[ \t]+", " ", line).strip()
        if normalized:
            lines.append(normalized)
        elif lines and lines[-1] != "":
            lines.append("")
    return "\n".join(lines).strip()

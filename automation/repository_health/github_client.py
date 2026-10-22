"""Small, read-only GitHub REST client with explicit evidence completeness.

The assessment engine must not confuse an inaccessible API with a negative
answer.  This client therefore represents every HTTP or transport failure as
``Unknown`` and, when pagination fails after one or more pages, retains the
observed rows while marking the population incomplete.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


DEFAULT_API_VERSION = "2026-03-10"
DEFAULT_MAX_PAGES = 100
DEFAULT_MAX_ITEMS = 10_000
DEFAULT_MAX_BINARY_BYTES = 1024 * 1024
DEFAULT_MAX_REDIRECTS = 5
GITHUB_DOWNLOAD_HOSTS = frozenset(
    {
        "github-releases.githubusercontent.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)


class _NoRedirectHandler(HTTPRedirectHandler):
    """Expose redirects so callers can validate or reject every destination."""

    def redirect_request(
        self,
        req: Any,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def _no_redirect_urlopen(request: Request, *, timeout: int) -> Any:
    return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


def utc_now() -> str:
    """Return an evidence timestamp with stable second precision."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _effective_port(parts: Any) -> int | None:
    if parts.port is not None:
        return parts.port
    if parts.scheme.lower() == "https":
        return 443
    if parts.scheme.lower() == "http":
        return 80
    return None


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    return parts.scheme.lower(), (parts.hostname or "").lower(), _effective_port(parts)


def _headers_dict(headers: Any) -> dict[str, str]:
    if headers is None:
        return {}
    try:
        return {str(key): str(value) for key, value in headers.items()}
    except (AttributeError, TypeError, ValueError):
        return {}


def _header(headers: Mapping[str, str], name: str) -> str | None:
    expected = name.lower()
    for key, value in headers.items():
        if key.lower() == expected:
            return value
    return None


def _split_link_header(value: str) -> list[str]:
    """Split an RFC 8288 Link field without splitting quoted/URI commas."""

    entries: list[str] = []
    start = 0
    in_uri = False
    in_quote = False
    escaped = False
    for index, character in enumerate(value):
        if escaped:
            escaped = False
            continue
        if character == "\\" and in_quote:
            escaped = True
            continue
        if character == '"' and not in_uri:
            in_quote = not in_quote
            continue
        if character == "<" and not in_quote:
            in_uri = True
            continue
        if character == ">" and not in_quote:
            in_uri = False
            continue
        if character == "," and not in_uri and not in_quote:
            entries.append(value[start:index].strip())
            start = index + 1
    entries.append(value[start:].strip())
    return [entry for entry in entries if entry]


def parse_link_header(value: str | None) -> dict[str, str]:
    """Return the first target for each relation in an RFC Link field."""

    links: dict[str, str] = {}
    if not value:
        return links
    for entry in _split_link_header(value):
        if not entry.startswith("<") or ">" not in entry:
            continue
        target, remainder = entry[1:].split(">", 1)
        relations: list[str] = []
        for parameter in remainder.split(";"):
            name, separator, raw_value = parameter.strip().partition("=")
            if separator and name.lower() == "rel":
                relations.extend(raw_value.strip().strip('"').split())
        for relation in relations:
            links.setdefault(relation.lower(), target)
    return links


class GitHubRESTClient:
    """Failure-tolerant, same-origin GitHub REST reader.

    ``transport`` is injectable so collectors can be tested with byte fixtures
    and without network access.
    """

    def __init__(
        self,
        token: str | None = None,
        api_url: str | None = None,
        api_version: str | None = None,
        transport: Callable[..., Any] | None = None,
        timeout: int = 15,
        max_pages: int = DEFAULT_MAX_PAGES,
        max_items: int = DEFAULT_MAX_ITEMS,
    ) -> None:
        configured_url = (api_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
        parts = urlsplit(configured_url)
        if parts.scheme.lower() not in {"http", "https"} or not parts.hostname:
            raise ValueError("GitHub API URL must be an absolute HTTP(S) URL")
        if parts.username or parts.password:
            raise ValueError("GitHub API URL must not contain credentials")
        if max_pages < 1 or max_items < 1:
            raise ValueError("Pagination caps must be positive")

        self.token = token or ""
        if self.token and parts.scheme.lower() != "https":
            raise ValueError("Authenticated GitHub API requests require HTTPS")
        self.api_url = configured_url
        self.api_version = api_version or os.environ.get("GITHUB_API_VERSION") or DEFAULT_API_VERSION
        self.transport = transport or _no_redirect_urlopen
        self.binary_transport = transport or _no_redirect_urlopen
        self.timeout = timeout
        self.max_pages = max_pages
        self.max_items = max_items
        self._api_origin = _origin(configured_url)

    def _binary_redirect_url(self, reference: str, current_url: str) -> str:
        target = urljoin(current_url, reference)
        parts = urlsplit(target)
        if parts.username or parts.password:
            raise ValueError("GitHub asset redirect must not contain credentials")
        if parts.scheme.lower() != "https" or not parts.hostname:
            raise ValueError("GitHub asset redirects must use HTTPS")
        target_origin = _origin(target)
        if target_origin == self._api_origin:
            return target
        api_host = self._api_origin[1]
        target_host = target_origin[1]
        if (
            api_host == "api.github.com"
            and self._api_origin[0] == "https"
            and target_origin[2] == 443
            and target_host in GITHUB_DOWNLOAD_HOSTS
        ):
            return target
        raise ValueError("GitHub asset redirect target is not an approved download origin")

    @staticmethod
    def _binary_failure(
        *,
        url: str,
        observed_at: str,
        error: str,
        error_kind: str,
        status: int | None = None,
        headers: Mapping[str, str] | None = None,
        final_url: str | None = None,
        redirects: list[dict[str, Any]] | None = None,
        declared_size: int | None = None,
    ) -> dict[str, Any]:
        return {
            "state": "unknown",
            "ok": False,
            "status": status,
            "data": None,
            "size": None,
            "declared_size": declared_size,
            "error": error,
            "error_kind": error_kind,
            "headers": dict(headers or {}),
            "url": url,
            "final_url": final_url or url,
            "redirects": list(redirects or []),
            "observed_at": observed_at,
        }

    def _resolve_url(self, reference: str, relative_to: str | None = None) -> str:
        parts = urlsplit(reference)
        if parts.scheme or parts.netloc:
            target = reference
        elif relative_to is not None:
            target = urljoin(relative_to, reference)
        else:
            target = f"{self.api_url}/{reference.lstrip('/')}"
        target_parts = urlsplit(target)
        if target_parts.username or target_parts.password:
            raise ValueError("GitHub API target must not contain credentials")
        if _origin(target) != self._api_origin:
            raise ValueError("GitHub API pagination target is not same-origin")
        return target

    def _get_url(self, url: str, accept: str) -> dict[str, Any]:
        observed_at = utc_now()
        headers = {
            "Accept": accept,
            "X-GitHub-Api-Version": self.api_version,
            "User-Agent": "repository-health-assessment/0.1",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        request = Request(url, headers=headers, method="GET")
        try:
            with self.transport(request, timeout=self.timeout) as response:
                response_headers = _headers_dict(getattr(response, "headers", None))
                status = getattr(response, "status", 200)
                response_url = getattr(response, "geturl", lambda: url)()
                if isinstance(response_url, str) and response_url != url:
                    return {
                        "state": "unknown",
                        "ok": False,
                        "status": status,
                        "data": None,
                        "error": "JSON transport followed an unvalidated redirect",
                        "error_kind": "unvalidated_redirect",
                        "headers": response_headers,
                        "url": url,
                        "observed_at": observed_at,
                    }
                if status in {301, 302, 303, 307, 308}:
                    return {
                        "state": "unknown",
                        "ok": False,
                        "status": status,
                        "data": None,
                        "error": "GitHub JSON redirects are not followed",
                        "error_kind": "unsafe_redirect",
                        "headers": response_headers,
                        "url": url,
                        "observed_at": observed_at,
                    }
                if status < 200 or status >= 300:
                    return {
                        "state": "unknown",
                        "ok": False,
                        "status": status,
                        "data": None,
                        "error": f"HTTP {status}",
                        "error_kind": "permission_or_api_gap" if status in {403, 404} else "http_error",
                        "headers": response_headers,
                        "url": url,
                        "observed_at": observed_at,
                    }
                body = response.read()
                try:
                    data = json.loads(body.decode("utf-8")) if body else None
                except (UnicodeDecodeError, json.JSONDecodeError) as error:
                    return {
                        "state": "unknown",
                        "ok": False,
                        "status": getattr(response, "status", 200),
                        "data": None,
                        "error": f"Invalid JSON response ({type(error).__name__})",
                        "error_kind": "invalid_json",
                        "headers": response_headers,
                        "url": url,
                        "observed_at": observed_at,
                    }
                return {
                    "state": "observed",
                    "ok": True,
                    "status": getattr(response, "status", 200),
                    "data": data,
                    "error": None,
                    "error_kind": None,
                    "headers": response_headers,
                    "url": url,
                    "observed_at": observed_at,
                }
        except HTTPError as error:
            status = error.code
            response_headers = _headers_dict(getattr(error, "headers", None))
            error.close()
            return {
                "state": "unknown",
                "ok": False,
                "status": status,
                "data": None,
                "error": (
                    "GitHub JSON redirects are not followed"
                    if status in {301, 302, 303, 307, 308}
                    else f"HTTP {status}"
                ),
                "error_kind": (
                    "unsafe_redirect"
                    if status in {301, 302, 303, 307, 308}
                    else ("permission_or_api_gap" if status in {403, 404} else "http_error")
                ),
                "headers": response_headers,
                "url": url,
                "observed_at": observed_at,
            }
        except (URLError, TimeoutError, OSError) as error:
            return {
                "state": "unknown",
                "ok": False,
                "status": None,
                "data": None,
                "error": type(error).__name__,
                "error_kind": "network_error",
                "headers": {},
                "url": url,
                "observed_at": observed_at,
            }

    def get(self, path: str, accept: str = "application/vnd.github+json") -> dict[str, Any]:
        """Read one GitHub resource; unsafe targets become explicit Unknown."""

        try:
            url = self._resolve_url(path)
        except ValueError as error:
            return {
                "state": "unknown",
                "ok": False,
                "status": None,
                "data": None,
                "error": str(error),
                "error_kind": "unsafe_origin",
                "headers": {},
                "url": path,
                "observed_at": utc_now(),
            }
        return self._get_url(url, accept)

    def get_binary(
        self,
        path: str,
        *,
        declared_size: int | None = None,
        max_bytes: int = DEFAULT_MAX_BINARY_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
    ) -> dict[str, Any]:
        """Read a bounded release asset while validating every redirect.

        The first request must target the configured GitHub API origin.  A
        redirect is followed only over HTTPS and only to the same origin, or,
        for api.github.com, to a small explicit set of GitHub download hosts.
        Authorization is never forwarded across origins.
        """

        observed_at = utc_now()
        if max_bytes < 1 or max_redirects < 0:
            raise ValueError("Binary response and redirect caps must be valid")
        if declared_size is not None and (
            not isinstance(declared_size, int) or isinstance(declared_size, bool) or declared_size < 0
        ):
            return self._binary_failure(
                url=path,
                observed_at=observed_at,
                error="Declared asset size must be a nonnegative integer",
                error_kind="invalid_declared_size",
            )
        try:
            initial_url = self._resolve_url(path)
        except ValueError as error:
            return self._binary_failure(
                url=path,
                observed_at=observed_at,
                error=str(error),
                error_kind="unsafe_origin",
                declared_size=declared_size,
            )
        if declared_size is not None and declared_size > max_bytes:
            return self._binary_failure(
                url=initial_url,
                observed_at=observed_at,
                error=f"Declared asset size exceeds the {max_bytes}-byte cap",
                error_kind="response_too_large",
                declared_size=declared_size,
            )

        current_url = initial_url
        redirects: list[dict[str, Any]] = []
        visited = {current_url}
        while True:
            same_origin = _origin(current_url) == self._api_origin
            headers = {
                "Accept": "application/octet-stream",
                "User-Agent": "repository-health-assessment/0.1",
            }
            if same_origin:
                headers["X-GitHub-Api-Version"] = self.api_version
                if self.token:
                    headers["Authorization"] = f"Bearer {self.token}"
            request = Request(current_url, headers=headers, method="GET")
            response: Any | None = None
            response_headers: dict[str, str] = {}
            status: int | None = None
            try:
                response = self.binary_transport(request, timeout=self.timeout)
                status = getattr(response, "status", 200)
                response_headers = _headers_dict(getattr(response, "headers", None))
            except HTTPError as error:
                status = error.code
                response_headers = _headers_dict(getattr(error, "headers", None))
                if status not in {301, 302, 303, 307, 308}:
                    error.close()
                    return self._binary_failure(
                        url=initial_url,
                        observed_at=observed_at,
                        error=f"HTTP {status}",
                        error_kind="permission_or_api_gap" if status in {403, 404} else "http_error",
                        status=status,
                        headers=response_headers,
                        final_url=current_url,
                        redirects=redirects,
                        declared_size=declared_size,
                    )
                error.close()
            except (URLError, TimeoutError, OSError) as error:
                return self._binary_failure(
                    url=initial_url,
                    observed_at=observed_at,
                    error=type(error).__name__,
                    error_kind="network_error",
                    final_url=current_url,
                    redirects=redirects,
                    declared_size=declared_size,
                )

            if status in {301, 302, 303, 307, 308}:
                if response is not None:
                    response.close()
                location = _header(response_headers, "Location")
                if not location:
                    return self._binary_failure(
                        url=initial_url,
                        observed_at=observed_at,
                        error="GitHub asset redirect did not provide a Location header",
                        error_kind="invalid_redirect",
                        status=status,
                        headers=response_headers,
                        final_url=current_url,
                        redirects=redirects,
                        declared_size=declared_size,
                    )
                if len(redirects) >= max_redirects:
                    return self._binary_failure(
                        url=initial_url,
                        observed_at=observed_at,
                        error=f"GitHub asset redirect cap reached ({max_redirects})",
                        error_kind="redirect_cap",
                        status=status,
                        headers=response_headers,
                        final_url=current_url,
                        redirects=redirects,
                        declared_size=declared_size,
                    )
                try:
                    next_url = self._binary_redirect_url(location, current_url)
                except ValueError as error:
                    return self._binary_failure(
                        url=initial_url,
                        observed_at=observed_at,
                        error=str(error),
                        error_kind="unsafe_redirect",
                        status=status,
                        headers=response_headers,
                        final_url=current_url,
                        redirects=redirects,
                        declared_size=declared_size,
                    )
                if next_url in visited:
                    return self._binary_failure(
                        url=initial_url,
                        observed_at=observed_at,
                        error="GitHub asset redirect loop detected",
                        error_kind="redirect_loop",
                        status=status,
                        headers=response_headers,
                        final_url=current_url,
                        redirects=redirects,
                        declared_size=declared_size,
                    )
                redirects.append({"from": current_url, "to": next_url, "status": status})
                visited.add(next_url)
                current_url = next_url
                continue

            if response is None:
                return self._binary_failure(
                    url=initial_url,
                    observed_at=observed_at,
                    error="GitHub asset request returned no response",
                    error_kind="transport_error",
                    status=status,
                    final_url=current_url,
                    redirects=redirects,
                    declared_size=declared_size,
                )
            with response:
                response_url = getattr(response, "geturl", lambda: current_url)()
                if response_url != current_url:
                    return self._binary_failure(
                        url=initial_url,
                        observed_at=observed_at,
                        error="Binary transport followed an unvalidated redirect",
                        error_kind="unvalidated_redirect",
                        status=status,
                        headers=response_headers,
                        final_url=response_url,
                        redirects=redirects,
                        declared_size=declared_size,
                    )
                if status is None or status < 200 or status >= 300:
                    return self._binary_failure(
                        url=initial_url,
                        observed_at=observed_at,
                        error=f"HTTP {status}",
                        error_kind="http_error",
                        status=status,
                        headers=response_headers,
                        final_url=current_url,
                        redirects=redirects,
                        declared_size=declared_size,
                    )
                raw_length = _header(response_headers, "Content-Length")
                content_length: int | None = None
                if raw_length is not None:
                    try:
                        content_length = int(raw_length)
                    except ValueError:
                        content_length = None
                    if content_length is None or content_length < 0:
                        return self._binary_failure(
                            url=initial_url,
                            observed_at=observed_at,
                            error="GitHub asset Content-Length is invalid",
                            error_kind="invalid_content_length",
                            status=status,
                            headers=response_headers,
                            final_url=current_url,
                            redirects=redirects,
                            declared_size=declared_size,
                        )
                    if content_length > max_bytes:
                        return self._binary_failure(
                            url=initial_url,
                            observed_at=observed_at,
                            error=f"GitHub asset Content-Length exceeds the {max_bytes}-byte cap",
                            error_kind="response_too_large",
                            status=status,
                            headers=response_headers,
                            final_url=current_url,
                            redirects=redirects,
                            declared_size=declared_size,
                        )
                body = response.read(max_bytes + 1)
                if not isinstance(body, bytes):
                    return self._binary_failure(
                        url=initial_url,
                        observed_at=observed_at,
                        error="GitHub asset transport did not return bytes",
                        error_kind="invalid_binary_response",
                        status=status,
                        headers=response_headers,
                        final_url=current_url,
                        redirects=redirects,
                        declared_size=declared_size,
                    )
            actual_size = len(body)
            if actual_size > max_bytes:
                return self._binary_failure(
                    url=initial_url,
                    observed_at=observed_at,
                    error=f"GitHub asset response exceeds the {max_bytes}-byte cap",
                    error_kind="response_too_large",
                    status=status,
                    headers=response_headers,
                    final_url=current_url,
                    redirects=redirects,
                    declared_size=declared_size,
                )
            if content_length is not None and content_length != actual_size:
                return self._binary_failure(
                    url=initial_url,
                    observed_at=observed_at,
                    error=f"GitHub asset Content-Length {content_length} does not match {actual_size} bytes",
                    error_kind="size_mismatch",
                    status=status,
                    headers=response_headers,
                    final_url=current_url,
                    redirects=redirects,
                    declared_size=declared_size,
                )
            if declared_size is not None and declared_size != actual_size:
                return self._binary_failure(
                    url=initial_url,
                    observed_at=observed_at,
                    error=f"Declared asset size {declared_size} does not match {actual_size} bytes",
                    error_kind="size_mismatch",
                    status=status,
                    headers=response_headers,
                    final_url=current_url,
                    redirects=redirects,
                    declared_size=declared_size,
                )
            return {
                "state": "observed",
                "ok": True,
                "status": status,
                "data": body,
                "size": actual_size,
                "declared_size": declared_size,
                "error": None,
                "error_kind": None,
                "headers": response_headers,
                "url": initial_url,
                "final_url": current_url,
                "redirects": redirects,
                "observed_at": observed_at,
            }

    def paginate(
        self,
        path: str,
        collection_key: str | None = None,
        *,
        accept: str = "application/vnd.github+json",
        max_pages: int | None = None,
        max_items: int | None = None,
    ) -> dict[str, Any]:
        """Follow RFC Link pagination and describe population completeness."""

        page_cap = max_pages if max_pages is not None else self.max_pages
        item_cap = max_items if max_items is not None else self.max_items
        if page_cap < 1 or item_cap < 1:
            raise ValueError("Pagination caps must be positive")

        observed_at = utc_now()
        items: list[Any] = []
        pages: list[dict[str, Any]] = []
        visited: set[str] = set()
        total_count: int | None = None
        truncated = False
        error: str | None = None
        gap: str | None = None
        try:
            next_url: str | None = self._resolve_url(path)
        except ValueError as unsafe:
            next_url = None
            error = str(unsafe)
            gap = "unsafe_origin"

        while next_url is not None and error is None:
            if next_url in visited:
                error = "Pagination Link loop detected"
                gap = "pagination_loop"
                break
            if len(pages) >= page_cap:
                truncated = True
                error = f"Pagination page cap reached ({page_cap})"
                gap = "page_cap"
                break
            visited.add(next_url)
            result = self._get_url(next_url, accept)
            if not result["ok"]:
                error = result["error"]
                gap = result.get("error_kind") or "request_failed"
                pages.append(
                    {
                        "url": next_url,
                        "status": result["status"],
                        "item_count": 0,
                        "state": "unknown",
                    }
                )
                break

            payload = result["data"]
            if collection_key is None:
                page_items = payload if isinstance(payload, list) else None
            elif isinstance(payload, dict):
                candidate = payload.get(collection_key)
                page_items = candidate if isinstance(candidate, list) else None
                raw_total = payload.get("total_count")
                if (
                    not isinstance(raw_total, int)
                    or isinstance(raw_total, bool)
                    or raw_total < 0
                ):
                    error = (
                        f"Response collection {collection_key} requires a non-negative "
                        "integer total_count"
                    )
                    gap = "invalid_collection"
                elif total_count is None:
                    total_count = raw_total
                elif total_count != raw_total:
                    error = (
                        f"Response collection {collection_key} changed total_count "
                        f"from {total_count} to {raw_total} during pagination"
                    )
                    gap = "population_mismatch"
            else:
                page_items = None
            if page_items is None or error is not None:
                if page_items is None:
                    error = f"Response does not contain list collection {collection_key or '<root>'}"
                    gap = "invalid_collection"
                pages.append(
                    {
                        "url": next_url,
                        "status": result["status"],
                        "item_count": 0,
                        "state": "unknown",
                    }
                )
                break

            remaining = item_cap - len(items)
            accepted = page_items[:remaining]
            items.extend(accepted)
            pages.append(
                {
                    "url": next_url,
                    "status": result["status"],
                    "item_count": len(accepted),
                    "state": "observed",
                }
            )
            if len(accepted) != len(page_items):
                truncated = True
                error = f"Pagination item cap reached ({item_cap})"
                gap = "item_cap"
                break

            next_reference = parse_link_header(_header(result["headers"], "Link")).get("next")
            if not next_reference:
                next_url = None
                continue
            try:
                next_url = self._resolve_url(next_reference, relative_to=next_url)
            except ValueError as unsafe:
                error = str(unsafe)
                gap = "unsafe_origin"
                break

        population_complete = error is None and not truncated
        if population_complete and total_count is not None and len(items) != total_count:
            population_complete = False
            error = f"Observed {len(items)} items but the endpoint reported {total_count}"
            gap = "population_mismatch"
        complete = population_complete
        return {
            "state": "observed" if complete else "unknown",
            "completeness": "complete" if complete else ("partial" if items else "unknown"),
            "items": items,
            "pages": pages,
            "page_count": len(pages),
            "item_count": len(items),
            "reported_total_count": total_count,
            "complete": complete,
            "population_complete": population_complete,
            "truncated": truncated,
            "error": error,
            "gap": gap,
            "observed_at": observed_at,
        }

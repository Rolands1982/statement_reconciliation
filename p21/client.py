"""
P21 OData API client.

Authentication: POST /api/security/token/ → Bearer JWT (24-hour TTL).
Token is cached in .p21_token_cache.json and reused until 5 minutes before expiry.

OData queries use manual $top/$skip pagination — @odata.nextLink is not supported.
HTTP via stdlib urllib.request only (no extra dependencies).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path


class P21AuthError(Exception):
    """Raised when authentication fails (bad credentials, 401, etc.)."""


class P21ApiError(Exception):
    """Raised when an OData request returns a non-200 response."""


_CACHE_PATH = Path(".p21_token_cache.json")
_EXPIRY_BUFFER = timedelta(minutes=5)


class P21Client:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        cache_path: Path = _CACHE_PATH,
        page_size: int = 500,
    ):
        self.base_url  = base_url.rstrip("/")
        self.username  = username
        self.password  = password
        self.cache_path = Path(cache_path)
        self.page_size  = page_size
        self._token: str | None = None

    # ── Auth ──────────────────────────────────────────────────────────────────

    def _get_token(self) -> str:
        """Return a valid Bearer token, using the cache when possible."""
        if self._token:
            return self._token

        # Try reading from disk cache
        if self.cache_path.exists():
            try:
                cached = json.loads(self.cache_path.read_text(encoding="utf-8"))
                expires_at = datetime.fromisoformat(cached["expires_at"])
                if datetime.now(timezone.utc) < expires_at - _EXPIRY_BUFFER:
                    self._token = cached["token"]
                    return self._token
            except Exception:
                pass  # Cache corrupt or missing fields — re-fetch

        self._token = self._fetch_token()
        return self._token

    def _fetch_token(self) -> str:
        """POST to /api/security/token/ and cache the result."""
        url = f"{self.base_url}/api/security/token/"
        req = urllib.request.Request(
            url,
            data=b"",
            method="POST",
            headers={
                "username":       self.username,
                "password":       self.password,
                "Content-Length": "0",
                "Accept":         "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise P21AuthError(f"Auth failed ({e.code}): {e.read().decode()[:200]}") from e
        except Exception as e:
            raise P21AuthError(f"Auth request failed: {e}") from e

        token = body.get("AccessToken")
        if not token:
            raise P21AuthError(f"No AccessToken in response: {body}")

        expires_in = int(body.get("ExpiresIn", 86400))
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)

        self.cache_path.write_text(
            json.dumps({"token": token, "expires_at": expires_at.isoformat()}, indent=2),
            encoding="utf-8",
        )
        print(f"  [P21] Token fetched, expires in {expires_in // 3600}h")
        return token

    # ── OData ─────────────────────────────────────────────────────────────────

    def odata_get(
        self,
        path: str,
        filter_expr: str,
        select: list[str] | None = None,
    ) -> list[dict]:
        """
        Paginate through an OData table/view and return all matching records.

        Args:
            path:        e.g. "table/apinv_hdr"
            filter_expr: OData $filter expression (required — never query unfiltered)
            select:      column names for $select (recommended to limit payload)
        """
        token   = self._get_token()
        results = []
        skip    = 0

        while True:
            params: dict[str, str] = {
                "$filter": filter_expr,
                "$top":    str(self.page_size),
                "$skip":   str(skip),
            }
            if select:
                params["$select"] = ",".join(select)

            url = (
                f"{self.base_url}/odataservice/odata/{path}"
                f"?{urllib.parse.urlencode(params)}"
            )
            req = urllib.request.Request(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                err_text = e.read().decode()[:300]
                raise P21ApiError(f"OData {path} failed ({e.code}): {err_text}") from e
            except Exception as e:
                raise P21ApiError(f"OData {path} request error: {e}") from e

            page = body.get("value", [])
            results.extend(page)

            if len(page) < self.page_size:
                break  # Last page
            skip += self.page_size

        return results

    def probe_table(self, path: str) -> dict | None:
        """GET path?$top=1 with no filter. Returns first row or None on 404."""
        token = self._get_token()
        url   = f"{self.base_url}/odataservice/odata/{path}?$top=1"
        req   = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                rows = body.get("value", [])
                return rows[0] if rows else {}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise P21ApiError(f"probe {path} failed ({e.code})") from e

"""Minimal HydraDB HTTP client for the documented JSON query endpoint."""

from __future__ import annotations

import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HydraDBError(RuntimeError):
    """Raised when HydraDB cannot execute a request."""


class HydraDBClient:
    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8443",
        graph_id: str = "default",
        cell_id: str = "cell-0",
        token: str | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.url = f"{base_url.rstrip('/')}/v1/graphs/{graph_id}/query"
        self.cell_id = cell_id
        self.token = token
        self.timeout = timeout
        self.last_read_epoch: str | int | None = None
        self.query_count = 0

    def query(self, cypher: str, parameters: dict[str, object] | None = None) -> object:
        request = self._request(cypher, parameters)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode())
        except HTTPError as error:
            detail = error.read().decode(errors="replace").strip()
            suffix = f": {detail}" if detail else ""
            raise HydraDBError(
                f"HydraDB query failed: HTTP {error.code} {error.reason}{suffix}; "
                f"cypher={cypher}"
            ) from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise HydraDBError(
                f"HydraDB query failed: {error}; cypher={cypher}"
            ) from error
        if isinstance(payload, dict) and payload.get("error"):
            raise HydraDBError(str(payload["error"]))
        self.query_count += 1
        if isinstance(payload, dict):
            self.last_read_epoch = payload.get("read_epoch", payload.get("bookmark"))
        return payload

    def _request(
        self, cypher: str, parameters: dict[str, object] | None = None
    ) -> Request:
        headers = {"Content-Type": "application/json", "X-Graph-Namespace": "default"}
        if self.token:
            token = self.token.strip()
            headers["Authorization"] = (
                token if token.lower().startswith("bearer ") else "Bearer " + token
            )
        body: dict[str, object] = {"cell_id": self.cell_id, "query": cypher}
        if parameters is not None:
            body["parameters"] = parameters
        return Request(
            self.url,
            data=json.dumps(body).encode(),
            headers=headers,
            method="POST",
        )

    def ingest(self, statements: list[str]) -> list[object]:
        """Execute bounded fixture statements and retain each response."""
        return [self.query(statement) for statement in statements]

    def telemetry(self) -> dict[str, int | str | None]:
        return {
            "backend": "hydradb_http",
            "query_count": self.query_count,
            "read_epoch": self.last_read_epoch,
        }

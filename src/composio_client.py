import os
from typing import Any

import requests


class ComposioClient:
    """Composio v3.1 REST client for read/enrichment and future write actions."""

    def __init__(self) -> None:
        self.base_url = (os.getenv("COMPOSIO_BASE_URL") or "https://backend.composio.dev/api/v3.1").rstrip("/")
        self.api_key = os.getenv("COMPOSIO_API_KEY", "").strip()
        self.connected_account_id = os.getenv("COMPOSIO_CONNECTED_ACCOUNT_ID", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def execute_tool(
        self,
        tool_slug: str,
        *,
        arguments: dict[str, Any] | None = None,
        text: str | None = None,
        connected_account_id: str | None = None,
        version: str = "latest",
    ) -> dict[str, Any]:
        """Execute a Composio tool.

        If no connected account ID is supplied, Composio uses the project's
        default connected account as documented by the v3.1 API. This avoids a
        separate connected-account lookup request and prevents the prior 401
        failure from blocking every social read.
        """
        if not self.configured:
            return {"status": "not_configured", "tool": tool_slug}
        if (arguments is None) == (text is None):
            raise ValueError("Pass exactly one of arguments or text")

        payload: dict[str, Any] = {"version": version}
        account = connected_account_id or self.connected_account_id
        if account:
            payload["connected_account_id"] = account
        if arguments is not None:
            payload["arguments"] = arguments
        else:
            payload["text"] = text

        response = requests.post(
            f"{self.base_url}/tools/execute/{tool_slug}",
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
            json=payload,
            timeout=60,
        )
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        if not response.ok:
            return {
                "status": "error",
                "tool": tool_slug,
                "http_status": response.status_code,
                "error": data,
            }
        return {"status": "success", "tool": tool_slug, "data": data}

    def execute(self, action: str, payload: dict[str, Any], *, live_mode: bool) -> dict[str, Any]:
        """Backward-compatible local logging wrapper; new reads use execute_tool()."""
        if not live_mode:
            return {"status": "dry_run", "action": action, "payload": payload}
        return {"status": "unsupported_legacy_action", "action": action, "payload": payload}

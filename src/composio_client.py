import os
from typing import Any
from urllib.parse import urlencode

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

    def resolve_connected_account(self, toolkit_slug: str) -> str:
        """Pick the first ACTIVE connected account for a toolkit unless explicitly configured."""
        if self.connected_account_id or not self.configured:
            return self.connected_account_id
        params = urlencode({"toolkit_slugs": toolkit_slug, "statuses": "ACTIVE", "limit": 20})
        try:
            response = requests.get(
                f"{self.base_url}/connected_accounts?{params}",
                headers={"x-api-key": self.api_key},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()
            items = data.get("items", []) if isinstance(data, dict) else []
            if items:
                account_id = str(items[0].get("id", "")).strip()
                if account_id:
                    return account_id
        except Exception as exc:
            print(f"Composio connected account lookup failed for {toolkit_slug}: {exc}")
        return ""

    def execute_tool(
        self,
        tool_slug: str,
        *,
        arguments: dict[str, Any] | None = None,
        text: str | None = None,
        connected_account_id: str | None = None,
        version: str = "latest",
    ) -> dict[str, Any]:
        if not self.configured:
            return {"status": "not_configured", "tool": tool_slug}
        if (arguments is None) == (text is None):
            raise ValueError("Pass exactly one of arguments or text")

        payload: dict[str, Any] = {"version": version}
        account = connected_account_id or self.connected_account_id
        if not account:
            toolkit_slug = tool_slug.split("_", 1)[0].lower()
            account = self.resolve_connected_account(toolkit_slug)
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
            return {"status": "error", "tool": tool_slug, "http_status": response.status_code, "error": data}
        return {"status": "success", "tool": tool_slug, "data": data}

    def execute(self, action: str, payload: dict[str, Any], *, live_mode: bool) -> dict[str, Any]:
        """Backward-compatible local logging wrapper; new reads use execute_tool()."""
        if not live_mode:
            return {"status": "dry_run", "action": action, "payload": payload}
        return {"status": "unsupported_legacy_action", "action": action, "payload": payload}

import os
from typing import Any

import requests


class ComposioClient:
    """Composio v3.1 REST client for read/enrichment and future write actions."""

    OFFICIAL_BASE_URL = "https://backend.composio.dev/api/v3.1"

    def __init__(self) -> None:
        self.base_url = self.OFFICIAL_BASE_URL
        self.api_key = (os.getenv("COMPOSIO_PROJECT_API_KEY") or "").strip()
        self.connected_account_id = os.getenv("COMPOSIO_CONNECTED_ACCOUNT_ID", "").strip()

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def _platform_from_tool(tool_slug: str) -> str:
        slug = tool_slug.upper()
        if slug.startswith("FACEBOOK_"):
            return "facebook"
        if slug.startswith("LINKEDIN_"):
            return "linkedin"
        return ""

    def _resolve_account_from_env(self, tool_slug: str) -> str:
        platform = self._platform_from_tool(tool_slug)
        if platform == "facebook":
            return os.getenv("COMPOSIO_FACEBOOK_CONNECTED_ACCOUNT_ID", "").strip()
        if platform == "linkedin":
            return os.getenv("COMPOSIO_LINKEDIN_CONNECTED_ACCOUNT_ID", "").strip()
        return ""

    def _resolve_user_from_env(self, tool_slug: str) -> str:
        platform = self._platform_from_tool(tool_slug)
        if platform == "facebook":
            return os.getenv("COMPOSIO_FACEBOOK_USER_ID", "").strip()
        if platform == "linkedin":
            return os.getenv("COMPOSIO_LINKEDIN_USER_ID", "").strip()
        return ""

    def execute_tool(
        self,
        tool_slug: str,
        *,
        arguments: dict[str, Any] | None = None,
        text: str | None = None,
        connected_account_id: str | None = None,
        user_id: str | None = None,
        version: str = "latest",
    ) -> dict[str, Any]:
        """Execute a Composio tool with explicit platform account and user identity when configured."""
        if not self.configured:
            return {"status": "not_configured", "tool": tool_slug}
        if (arguments is None) == (text is None):
            raise ValueError("Pass exactly one of arguments or text")

        payload: dict[str, Any] = {"version": version}
        account = connected_account_id or self._resolve_account_from_env(tool_slug) or self.connected_account_id
        uid = user_id or self._resolve_user_from_env(tool_slug)
        if account:
            payload["connected_account_id"] = account
        if uid:
            payload["user_id"] = uid
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
        if not live_mode:
            return {"status": "dry_run", "action": action, "payload": payload}
        return {"status": "unsupported_legacy_action", "action": action, "payload": payload}

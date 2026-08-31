import os
from typing import Any

import requests


class ComposioClient:
    """Thin HTTP adapter for a Composio execution endpoint.

    The concrete action/tool names are intentionally configured via environment
    variables so platform-specific Composio mappings can be changed without
    modifying the engine.
    """

    def __init__(self) -> None:
        self.base_url = os.getenv("COMPOSIO_BASE_URL", "").rstrip("/")
        self.api_key = os.getenv("COMPOSIO_API_KEY", "")

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key)

    def execute(self, action: str, payload: dict[str, Any], *, live_mode: bool) -> dict[str, Any]:
        if not live_mode:
            return {"status": "dry_run", "action": action, "payload": payload}
        if not self.configured:
            return {"status": "not_configured", "action": action}

        response = requests.post(
            f"{self.base_url}/actions/execute",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"action": action, "input": payload},
            timeout=45,
        )
        response.raise_for_status()
        return response.json()

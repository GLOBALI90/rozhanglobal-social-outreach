# ROZHAN GLOBAL — Social Outreach Engine

Independent automation engine for LinkedIn and Facebook outreach.

## Architecture

- 5 hourly LinkedIn workflows
- 5 hourly Facebook workflows
- Shared Python core
- Separate platform adapters
- Composio-ready integration layer
- AI message planning hooks
- Persistent CSV state for initial MVP
- Dry-run by default

## Safety

`LIVE_MODE` defaults to `false`. In dry-run mode the engine plans and logs actions without performing social actions.

To enable real actions later, configure the required Composio connection/action settings and explicitly set `LIVE_MODE=true`.

## Run locally

```bash
pip install -r requirements.txt
python -m src.main --platform linkedin --slot 1
```

## GitHub Actions

The repository contains ten hourly workflows under `.github/workflows/`.

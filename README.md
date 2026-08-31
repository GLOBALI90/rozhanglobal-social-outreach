# ROZHAN GLOBAL — Social Outreach Engine

Independent automation engine for LinkedIn and Facebook outreach.

## Hourly contract

Every hourly batch produces exactly **10 records**:

- **5 Facebook records** — slots 1–5
- **5 LinkedIn records** — slots 1–5

The ten legacy slot workflows are kept as **manual-only** runners so account/slot identity remains available without causing concurrent hourly writes.

## Production hourly runner

`.github/workflows/hourly-social-batch.yml` runs once per hour and executes all 10 slots in one GitHub Actions job. This prevents ten concurrent CSV commits from racing with each other.

## Current mode

`LIVE_MODE` defaults to `false`. The current implementation is a safe dry-run/state pipeline. It records one action/record per slot. Real social actions are enabled only after the concrete Composio action mappings and connections are configured and `LIVE_MODE=true` is explicitly set.

## Data

`data/social_actions.csv` is the initial persistent state store.

## Local test

```bash
pip install -r requirements.txt
python -m src.run_hourly_batch
```

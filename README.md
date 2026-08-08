# TS-Local

Local-first Windows desktop trade copier and journal built for personal use and a small group of trusted friends.

## Current architecture

- Tradovate is the primary broker/platform.
- Multiple Tradovate logins and multiple accounts per login are supported by the domain model.
- One leader account can drive multiple follower accounts.
- Each follower has an independent quantity multiplier.
- Copying defaults to `DRY_RUN`; live execution must be explicitly enabled.
- Credentials are kept outside source control behind Windows user-scoped DPAPI storage.
- Trade journaling is part of the core domain rather than an external service.

## Desktop application

The first Windows desktop shell is implemented with PySide6. It currently exposes the account/copy-group workflow and visibly starts in DRY RUN mode.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,ui]"
python -m ts_local
# or
 ts-local
```

## Tradovate integration

The connector uses Tradovate's REST API for authentication/account discovery and its newline-delimited WebSocket protocol for real-time user synchronization. Production endpoints are selected by environment (`live` or `demo`).

Tradovate credentials and API secrets must never be committed to this repository. Store them through the application's secure-store boundary once the desktop UI is wired up.

## Development

Requires Python 3.12+ and Windows 11 for the secure credential store.

```powershell
pytest
ruff check .
```

The live broker connector is deliberately separate from the copier engine. Live order submission will remain disabled until the execution layer has explicit safety limits and passes dry-run/integration testing.

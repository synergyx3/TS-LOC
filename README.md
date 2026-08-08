# TS-Local

Local-first Windows desktop trade copier and journal built for personal use and a small group of trusted friends.

## Current architecture

- Tradovate is the primary broker/platform.
- Multiple Tradovate logins and multiple accounts per login are supported by the domain model.
- One leader account can drive multiple follower accounts.
- Each follower has an independent quantity multiplier.
- Copying defaults to `DRY_RUN`; live execution must be explicitly enabled.
- Credentials are kept outside source control behind an encrypted local secret-store boundary.
- Trade journaling is part of the core domain rather than an external service.

## Development

Requires Python 3.12+.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

The live Tradovate connector and Windows credential-protection implementation are intentionally separate from the copier engine so they can be tested without sending real orders.

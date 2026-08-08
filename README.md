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

The Windows desktop shell is implemented with PySide6. It exposes saved Tradovate connections, discovered accounts, leader/follower selection, follower multipliers and a visible DRY RUN status.

A configured copy group can now start a background DRY RUN leader listener from the desktop UI. The listener reads Tradovate leader order events, normalizes them, applies follower multipliers and safety limits, and records the simulated follower outcomes locally without submitting broker orders.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev,ui]"
python -m ts_local
# or
 ts-local
```

## Tradovate integration

The connector uses Tradovate REST for authentication, account discovery and contract lookup, plus `user/syncrequest` over WebSocket for real-time user events. The socket sends the required client heartbeat every 2.5 seconds and subscribes only to the entity types needed by the copier.

New leader `order` events are normalized into TS-Local `TradeEvent` objects. Duplicate Tradovate order IDs are ignored so later/repeated socket messages cannot fan the same leader order out twice. Contract IDs are resolved to tradeable symbols before copying.

Tradovate credentials and API secrets must never be committed to this repository. They are stored through the application's secure-store boundary.

## Supported local bridge path

NinjaTrader Desktop 8 exposes a documented Automated Trading Interface (ATI). Its File Interface accepts Order Instruction Files (OIF) in the local NinjaTrader `incoming` directory, so it is a legitimate non-public-API transport when the target account can be connected in NinjaTrader Desktop.

TS-Local now includes a `NinjaTraderOifExecutor` adapter and an account-ID-to-NinjaTrader-account-name boundary. The adapter:

- is disarmed by default and writes nothing until explicitly armed in code;
- validates mapped account names and instrument text before serialization;
- emits documented `PLACE` instructions using atomic same-directory renames;
- supports market, limit and stop-market instructions, while failing closed on stop-limit orders until distinct stop and limit prices are modeled;
- fails closed for missing mappings, directories and required prices.

This bridge is not wired into the desktop controls yet, and live execution remains disabled. It does not make an account compatible with NinjaTrader Desktop; that must be confirmed with the provider and a demo connection first.

## Local journal

Copy outcomes are stored in `%LOCALAPPDATA%\\TS-Local\\journal.sqlite3`. The desktop UI shows recent leader/follower activity, quantities, symbols, and whether each action was skipped because the application is in DRY RUN mode.

## Copier safety

Live execution is still disabled by default. The copier currently enforces these guards even before a broker executor is allowed to go live:

- leader account cannot also be a follower;
- duplicate follower definitions are skipped;
- disabled followers are skipped;
- zero-quantity results are skipped;
- each follower has a configurable hard maximum quantity cap (default: 20 contracts);
- repeated websocket order IDs are idempotent;
- DRY RUN never calls the broker order executor.

## Development

Requires Python 3.12+ and Windows 11 for the secure credential store.

```powershell
pytest
ruff check .
```

The next user checkpoint is two-part:

1. In NinjaTrader Desktop 8, confirm the MFFU-provided account can be connected and appears by its exact account name. Do not enable TS-Local live execution.
2. Run the existing Tradovate DRY RUN listener, place a small demo leader order, and verify the simulated follower action appears in the local activity journal.

After those checks, the next development milestone is a UI setup/diagnostics screen that verifies the NinjaTrader incoming directory and account mappings, then writes a harmless bridge probe rather than an order. Live order submission remains disabled until demo integration and explicit arming controls are implemented and tested.

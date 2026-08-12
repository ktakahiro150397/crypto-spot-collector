# Testing

Run the deterministic unit and mock-integration suite with:

```powershell
uv run --extra dev pytest -q
```

The default suite blocks non-loopback socket connections (loopback remains
available for the Windows asyncio self-pipe). Hyperliquid, Discord and all
other remote services must be represented by fakes or mocks. A test that
really requires an external service must be marked `external` and run only
after the user explicitly authorizes that service and environment, for example:

```powershell
uv run --extra dev pytest -m external
```

The default suite covers closed-candle gating, duplicate candle suppression,
strategy close/reverse transitions, persistent cloid order intents, partial
fills, timeout reconciliation, position and TP/SL recovery, protection-order
failure paths, WebSocket reconnect/snapshot deduplication, REST backoff/circuit
breaking and graceful shutdown.

# Binance setup

> **Status: the Binance connector is not implemented yet** (Tier 1 phase 5).
> This document describes the key configuration the platform will require, so
> keys can be prepared correctly in advance.

## Creating API keys

1. Sign in to Binance → **API Management** → create a key.
2. Enable **Reading** and **Spot & Margin Trading**.
3. **Do not enable withdrawals.** This platform has no withdrawal function
   anywhere, and never asks for that permission.
4. Do not enable futures or margin. This is a Spot-only system.
5. Restrict the key to your IP address wherever your connection allows it.

## Testnet first

Start on the Spot testnet: <https://testnet.binance.vision>. Testnet keys are
separate from production keys.

```env
BINANCE_API_KEY=your_testnet_key
BINANCE_API_SECRET=your_testnet_secret
BINANCE_TESTNET=true
```

## Security rules this project enforces

- `.env` is gitignored, along with `.env.*`, `secrets/`, `models/`, `data/`,
  `backups/` and `logs/`.
- Secrets are never baked into images and never sent to the frontend. The
  settings endpoint reports only whether credentials are *configured*.
- Log records are scrubbed of key-shaped fields before reaching any handler.
- Automated tests never use real credentials; a mock connector is used instead.

## Rate limits and time

Binance's published rate limits change. The connector will read the live limits
from `exchangeInfo` and keep them configurable rather than hard-coding a
remembered number, and it will use the exchange's server time rather than the
laptop clock (`recvWindow` errors are handled explicitly).

# Security Policy

## Scope & design (read this first)

Tickscope is **read-only and public-data only by design**. v1:

- does **not** execute orders, read balances, or move funds;
- does **not** require or accept exchange API secrets;
- connects only to public market-data endpoints.

This keeps the attack surface and your responsibility small. If you add
authenticated features in a fork, never log or echo secrets — read them from
environment variables only.

## Reporting a vulnerability

Please report security issues **privately**, not via public issues:

- Use [GitHub Security Advisories](https://github.com/seungdori/tickscope-mcp/security/advisories/new)
  (preferred), or
- email the maintainers with the details and reproduction steps.

We aim to acknowledge within a few days and to coordinate a fix and disclosure
timeline with you.

## Disclaimer

This tool is for **educational and research purposes only**. It is not financial,
investment, or trading advice. Market data may be delayed, incomplete, or
inaccurate; do not rely on it for real trading decisions. You are responsible for
complying with each exchange's terms of service and rate limits.

# Hosted backend integration

Maintained by Ruolan Chen. This directory contains the backend currently integrated with the AI Toll Gate frontend. The original server and main branch are preserved.

API: https://ai-toll-gate-ruolan-chen-api.vercel.app
API docs: https://ai-toll-gate-ruolan-chen-api.vercel.app/docs
Frontend: https://ai-toll-gate-ruolan-chen.vercel.app
Frontend source: https://github.com/OrchidRLan/AI-Toll-Gate/tree/ruolan-chen

Source snapshot: AI-Toll-Gate commit 16abc9b. Upstream base: 8a05527. This snapshot does not incorporate later upstream changes.

## Run and maintain

Requires Python 3.12 and uv. Run `uv sync --locked` in this directory. Copy `.env.example` to `.env` and configure server-only values. Never commit credentials. Deploy this directory as a Vercel FastAPI project, with Neon PostgreSQL and the existing stable encryption/signing keys.

Full deployment and acceptance instructions: https://github.com/OrchidRLan/AI-Toll-Gate/blob/ruolan-chen/DEPLOYMENT.md

Tests: `uv run python -m unittest discover -s tests -v`

Adds PostgreSQL storage, encrypted per-session testnet wallets, same-origin browser endpoints, private article libraries, signed receipts, durable purchase idempotency and payment recovery.

Testnet only: one sample article; no real-money billing, publisher onboarding, Ghost integration, autonomous purchasing agent or account recovery. Internal purchase testing is not customer validation.

This is a reviewable snapshot. Future backend changes must be synchronized with the frontend repository before deployment; pushing this branch does not redeploy either service.

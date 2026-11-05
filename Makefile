.PHONY: server server-test buyer buyer-test web wallets buy-test demo-reset demo-otp supabase-setup migrate-db agent topup payout stripe-listen

server:
	cd server && uv run uvicorn app.main:app --reload --port 8000

server-test:
	cd server && uv run pytest -q

buyer:
	cd buyer-mcp && uv run python -m buyer_mcp.server

buyer-test:
	cd buyer-mcp && uv run pytest -q

web:
	cd web && npm run dev

wallets:
	cd server && uv run python ../scripts/create_wallets.py $(ARGS)

buy-test:
	cd server && uv run python ../scripts/buy_test.py $(ARGS)

demo-reset:
	cd server && uv run python ../scripts/demo_reset.py

demo-otp:
	cd server && uv run python ../scripts/demo_otp.py $(EMAIL)

supabase-setup:
	cd server && uv run python ../scripts/supabase_setup.py

migrate-db:
	cd server && uv run python ../scripts/migrate_to_postgres.py

agent:
	cd server && uv run python ../scripts/agent_setup.py

topup:
	cd server && uv run python ../scripts/topup.py $(ARGS)

payout:
	cd server && uv run python ../scripts/payout.py

# Writes the webhook secret to .env, then forwards events. Restart `make server` if the secret was new.
stripe-listen:
	@set -a; . ./.env; set +a; \
	secret=$$(stripe listen --api-key "$$STRIPE_SECRET_KEY" --print-secret); \
	cd server && uv run python -c "import sys; sys.path.insert(0, '../scripts'); from pathlib import Path; from create_wallets import write_env; write_env(Path('../.env'), {'STRIPE_WEBHOOK_SECRET': '$$secret'})"; cd ..; \
	stripe listen --api-key "$$STRIPE_SECRET_KEY" --forward-to localhost:8000/webhooks/stripe

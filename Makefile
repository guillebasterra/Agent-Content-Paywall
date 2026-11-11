.PHONY: server server-test buyer buyer-test web wallets buy-test demo-reset demo-otp supabase-setup migrate-db agent topup payout stripe-listen rail web-demo treasury preflight tunnel test

server:
	cd server && uv run uvicorn app.main:app --reload --port 8000

server-test:
	cd server && uv run pytest -q

buyer:
	cd buyer-mcp && uv run python -m buyer_mcp.server

buyer-test:
	cd buyer-mcp && uv run pytest -q

test: server-test buyer-test

# Base demo: the treasury (CDP server wallet), a public URL for payments-mcp, and the pre-flight check.
treasury:
	cd server && uv run python ../scripts/treasury.py $(ARGS)

tunnel:
	cd server && uv run python ../scripts/tunnel.py

preflight:
	cd server && uv run python ../scripts/preflight.py

web:
	cd web && npm run dev

# For the live demo: a production build has no dev overlay and no compile pauses between pages.
web-demo:
	cd web && npm run build && npm run start

wallets:
	cd server && uv run python ../scripts/create_wallets.py $(ARGS)

buy-test:
	cd server && uv run python ../scripts/buy_test.py $(ARGS)

demo-reset:
	cd server && uv run python ../scripts/demo_reset.py $(ARGS)

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

stripe-listen:
	cd server && uv run python ../scripts/stripe_listen.py

# Server side: PAYMENT_RAIL=base|xrpl in .env, then restart `make server`.
# make rail RAIL=stripe  (or xrpl) only mattered to the old paying buyer MCP (tag buyer-mcp-xrpl-v1).
rail:
	cd server && uv run python -c "import sys; sys.path.insert(0, '../scripts'); from pathlib import Path; from create_wallets import write_env; write_env(Path('../.env'), {'BUYER_RAIL': '$(RAIL)'})"
	@echo "buyer rail: $(RAIL)"

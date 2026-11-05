.PHONY: server server-test buyer buyer-test web wallets buy-test demo-reset demo-otp supabase-setup migrate-db agent topup payout stripe-listen rail web-demo

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

# For the live demo: a production build has no dev overlay and no compile pauses between pages.
web-demo:
	cd web && npm run build && npm run start

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

stripe-listen:
	cd server && uv run python ../scripts/stripe_listen.py

# make rail RAIL=stripe  (or xrpl). The buyer MCP picks it up on its next call, no restart needed.
rail:
	cd server && uv run python -c "import sys; sys.path.insert(0, '../scripts'); from pathlib import Path; from create_wallets import write_env; write_env(Path('../.env'), {'BUYER_RAIL': '$(RAIL)'})"
	@echo "buyer rail: $(RAIL)"

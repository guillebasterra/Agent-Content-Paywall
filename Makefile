.PHONY: server server-test buyer buyer-test web wallets buy-test

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

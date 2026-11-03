.PHONY: server buyer buyer-test wallets buy-test

server:
	cd server && uv run uvicorn app.main:app --reload --port 8000

buyer:
	cd buyer-mcp && uv run python -m buyer_mcp.server

buyer-test:
	cd buyer-mcp && uv run pytest -q

wallets:
	cd server && uv run python ../scripts/create_wallets.py $(ARGS)

buy-test:
	cd server && uv run python ../scripts/buy_test.py $(ARGS)

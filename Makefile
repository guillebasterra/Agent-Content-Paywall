.PHONY: server buyer wallets

server:
	cd server && uv run uvicorn app.main:app --reload --port 8000

buyer:
	cd buyer-mcp && uv run python -m buyer_mcp.server

wallets:
	cd server && uv run python ../scripts/create_wallets.py

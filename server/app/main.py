from fastapi import FastAPI

app = FastAPI(title="Toll Gate")


@app.get("/health")
def health():
    return {"ok": True}

# Phase 3:
#   GET /catalog            free — title, author, abstract, price, license
#   GET /articles/{id}      paid — x402 paywall, full text + signed receipt
#   GET /ledger             recent purchases for the dashboard

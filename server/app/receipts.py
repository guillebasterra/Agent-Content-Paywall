"""Ed25519-signed purchase receipts.

A receipt binds: what was bought (article id + content hash), under which license,
for how much, by whom, and the XRPL transaction that paid for it. Anyone can verify
it with the public key served at /.well-known/tollgate-receipt-key.
"""

import base64
import json
from datetime import datetime, timezone

from nacl.encoding import HexEncoder
from nacl.signing import SigningKey, VerifyKey


def canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


class ReceiptSigner:
    def __init__(self, key_hex: str):
        self._key = SigningKey(key_hex, encoder=HexEncoder)

    @staticmethod
    def generate_hex() -> str:
        return SigningKey.generate().encode(encoder=HexEncoder).decode()

    @property
    def public_key_hex(self) -> str:
        return self._key.verify_key.encode(encoder=HexEncoder).decode()

    def sign(self, payload: dict) -> dict:
        payload = {**payload, "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        sig = self._key.sign(canonical(payload)).signature
        return {"payload": payload, "signature": base64.b64encode(sig).decode(), "alg": "ed25519"}


def verify(receipt: dict, public_key_hex: str) -> bool:
    try:
        VerifyKey(public_key_hex, encoder=HexEncoder).verify(
            canonical(receipt["payload"]), base64.b64decode(receipt["signature"])
        )
        return True
    except Exception:
        return False

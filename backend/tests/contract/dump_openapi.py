"""Dump the FastAPI OpenAPI spec to ``openapi.json`` for Schemathesis.

Used in CI by the ``connector-contract`` job::

    cd backend
    python -m tests.contract.dump_openapi > openapi.json
    schemathesis run openapi.json --base-url http://localhost:8000 --checks all

Run the same command locally (with the backend stack up) to reproduce CI
fuzz failures.
"""
from __future__ import annotations

import json
import os
import sys

# Set required env vars before any app.* imports — mirrors tests/conftest.py.
from cryptography.fernet import Fernet  # noqa: E402

os.environ.setdefault("JWT_SECRET", "dump-jwt-secret-key-must-be-32-chars-ok!")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")


def main() -> int:
    from app.main import app

    spec = app.openapi()
    json.dump(spec, sys.stdout, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())

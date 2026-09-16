"""Tests for the platform_connections -> legacy conn_doc adapter in app.deps.

Regression cover for the auth bug where encrypted credential fields (notably
`user`) were passed through un-decrypted, producing a ciphertext username and a
"JWT token is invalid" failure on every Snowflake dashboard page.
"""

from app.deps import _platform_conn_to_sf_doc
from app.services.encryption import encrypt_value


def test_adapter_decrypts_encrypted_fields():
    pc = {
        "_id": "conn1",
        "user_id": "u1",
        "name": "Snowflake",
        "credentials": {
            "account": "ACME-XY123",                 # stored plaintext
            "user": encrypt_value("SVC_USER"),        # stored encrypted
            "private_key": encrypt_value(
                "-----BEGIN PRIVATE KEY-----\nabc\n-----END PRIVATE KEY-----"
            ),
            "warehouse": "REPORTING_WH",
            "role": "READER_ROLE",
        },
    }
    doc = _platform_conn_to_sf_doc(pc)

    # The encrypted username must be decrypted, not passed as ciphertext.
    assert doc["username"] == "SVC_USER"
    # Plaintext fields pass through unchanged.
    assert doc["account"] == "ACME-XY123"
    assert doc["warehouse"] == "REPORTING_WH"
    assert doc["role"] == "READER_ROLE"
    assert doc["auth_type"] == "keypair"
    # The private key is handed on encrypted for build_sf_connection to decrypt.
    assert doc["private_key_encrypted"]


def test_adapter_fills_defaults_when_missing():
    pc = {"_id": "c2", "user_id": "u2", "credentials": {"user": encrypt_value("SVC")}}
    doc = _platform_conn_to_sf_doc(pc)
    assert doc["username"] == "SVC"
    assert doc["warehouse"] == "COMPUTE_WH"
    assert doc["database"] == "SNOWFLAKE"
    assert doc["schema_name"] == "ACCOUNT_USAGE"

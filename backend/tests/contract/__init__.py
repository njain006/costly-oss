"""Contract tests for vendor connectors.

Each test module pairs a connector with a JSON fixture captured from the
vendor's documented response shape. Tests use ``respx`` to short-circuit
``httpx`` so no real network call ever happens, and assert that the
connector parses the response into the expected ``UnifiedCost`` shape.

Re-recording fixtures
---------------------
The fixtures under ``tests/fixtures/<platform>/`` are intentionally hand-written
from vendor docs (so they don't leak any real account data). To capture a fresh
fixture against a real API, set ``RECORD_CASSETTES=1`` and the matching
``*_API_KEY`` for the platform, then run::

    cd backend
    RECORD_CASSETTES=1 pytest tests/contract/test_<platform>.py --record-mode=once

See ``docs/testing/contract-tests.md`` for the full re-recording guide.
"""

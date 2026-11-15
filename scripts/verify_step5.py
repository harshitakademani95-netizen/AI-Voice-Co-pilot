import io
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from starlette.testclient import TestClient
from src.app import create_app

stream = io.StringIO()
handler = logging.StreamHandler(stream)
handler.setFormatter(logging.Formatter('%(message)s'))
logger = logging.getLogger('backend.structured')
logger.setLevel(logging.INFO)
logger.addHandler(handler)

client = TestClient(create_app())

client.post('/api/v1/sessions', json={'api_key': 'sk-test-12345', 'password': 'supersecretpassword123'}, headers={'X-Correlation-ID': 'corr-log-1'})
client.post('/api/v1/sessions/session-xyz/pause', headers={'X-Correlation-ID': 'corr-log-2'})
client.post('/api/v1/sessions', content=b'{bad_json', headers={'Content-Type': 'application/json', 'X-Correlation-ID': 'corr-log-3'})
client.get('/api/v1/health', headers={'X-Correlation-ID': 'corr-log-4'})
client.get('/api/v1/sessions', headers={'X-Correlation-ID': 'corr-log-5'})

raw_log = stream.getvalue()
lines = [l for l in raw_log.strip().split('\n') if l]
print(f"Total structured log lines captured: {len(lines)}\n")
for i, line in enumerate(lines[:5], 1):
    print(f"Log {i}: {line}")

print("\n--- Secret Protection Check ---")
print("Does 'sk-test-12345' appear in logs?:", "sk-test-12345" in raw_log)
print("Does 'supersecretpassword123' appear in logs?:", "supersecretpassword123" in raw_log)

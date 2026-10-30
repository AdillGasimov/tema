"""Run PostgreSQL integration tests with a private local test configuration."""
import json
import os
from pathlib import Path
import subprocess
import sys

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path('/tmp/mikrofiber-pg-test.json')
url = json.loads(path.read_text())['url']
env = {**os.environ, 'PG_TEST_URL': url}
result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_postgres.py', '-v'], env=env)
raise SystemExit(result.returncode)

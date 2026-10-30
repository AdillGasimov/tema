#!/bin/sh
set -eu
cd /workspace/tema
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.txt
.venv/bin/python -m mikrofiber init
.venv/bin/python -m mikrofiber import-original

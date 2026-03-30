#!/bin/bash
set -e
pip install -r requirements.txt
playwright install chromium
echo "Runner setup complete"

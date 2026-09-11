#!/bin/bash

# Start backend using run.py with venv
cd "$(dirname "$0")"

echo "🚀 Starting Test Automation Backend..."
echo "Using virtual environment: ./venv"
echo ""

./venv/bin/python run.py

#!/bin/bash

echo "🔄 Restarting Frontend..."
echo ""

# Kill old frontend processes
echo "⏹️  Stopping old frontend processes..."
pkill -f "npm run dev" 2>/dev/null || echo "No running processes found"
sleep 2

# Navigate to frontend directory
cd "/home/admin1/project - POCs/test-automation-project/test-automation/frontend"

# Start frontend
echo ""
echo "▶️  Starting frontend..."
npm run dev


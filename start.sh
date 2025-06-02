#!/bin/bash
echo "🚀 Installing Playwright browsers..."
npx playwright install

echo "🚀 Starting FastAPI app..."
uvicorn main:app --host 0.0.0.0 --port $PORT

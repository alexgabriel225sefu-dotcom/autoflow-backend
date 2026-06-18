#!/bin/bash
# Runs ON the Oracle VM — called by GitHub Actions
set -e

echo "[1/4] Installing Node.js 20..."
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash - > /dev/null 2>&1
sudo dnf install -y nodejs git > /dev/null 2>&1
node --version

echo "[2/4] Cloning repo..."
sudo rm -rf /opt/apex-bot
sudo git clone --depth 1 -b claude/arcads-external-api-gExX7 \
  https://github.com/alexgabriel225sefu-dotcom/autoflow-backend.git /opt/apex-bot

echo "[3/4] Installing dependencies..."
cd /opt/apex-bot/apex-trade-bot
sudo npm install --production > /dev/null 2>&1

echo "[4/4] Starting bot..."
sudo pkill -f "index-server.js" 2>/dev/null || true
sudo bash -c "cd /opt/apex-bot/apex-trade-bot && nohup node src/index-server.js >> /var/log/apex-bot.log 2>&1 &"
sleep 3

if pgrep -f "index-server.js" > /dev/null; then
  echo ""
  echo "SUCCESS: Apex Trade Bot is running!"
  echo "Logs: tail -f /var/log/apex-bot.log"
else
  echo "ERROR: Bot failed to start. Check /var/log/apex-bot.log"
  exit 1
fi

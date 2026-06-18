#!/bin/bash
# Apex Trade Bot — One-click VPS setup from Codespaces
# Usage: bash apex-trade-bot/setup-server.sh <VM_IP>

set -e

IP="${1:-}"
if [ -z "$IP" ]; then
  echo "Usage: bash apex-trade-bot/setup-server.sh <VM_IP>"
  exit 1
fi

echo ""
echo "=== Apex Trade Bot Setup ==="
echo "Target VM: $IP"
echo ""

# Install sshpass if missing
if ! command -v sshpass &>/dev/null; then
  echo "[1/5] Installing sshpass..."
  sudo apt-get install -y sshpass -qq 2>/dev/null || true
fi

# Collect env vars
echo "[2/5] Collecting config..."
read -p "TELEGRAM_BOT_TOKEN: " TG_TOKEN
read -p "GROQ_API_KEY: " GROQ_KEY
MASTER_KEY=$(openssl rand -hex 16)
echo "MASTER_KEY generated: $MASTER_KEY (save this!)"
echo ""

# SSH into VM and install everything
echo "[3/5] Connecting to VM and installing..."
sshpass -p 'test1234' ssh -o StrictHostKeyChecking=no opc@$IP bash -s << REMOTE
set -e
echo "--- Node.js install ---"
curl -fsSL https://rpm.nodesource.com/setup_20.x | sudo bash - > /dev/null 2>&1
sudo dnf install -y nodejs git > /dev/null 2>&1

echo "--- Clone repo ---"
sudo rm -rf /opt/apex-bot
sudo git clone --depth 1 https://github.com/alexgabriel225sefu-dotcom/autoflow-backend.git /opt/apex-bot

echo "--- Install deps ---"
cd /opt/apex-bot/apex-trade-bot
sudo npm install > /dev/null 2>&1

echo "--- Write .env ---"
sudo tee /opt/apex-bot/apex-trade-bot/.env > /dev/null << ENV
TELEGRAM_BOT_TOKEN=$TG_TOKEN
GROQ_API_KEY=$GROQ_KEY
MASTER_KEY=$MASTER_KEY
NODE_ENV=production
ENV

echo "--- Start bot ---"
sudo pkill -f "index-server.js" 2>/dev/null || true
cd /opt/apex-bot/apex-trade-bot
sudo nohup node src/index-server.js >> /var/log/apex-bot.log 2>&1 &
sleep 2
echo "--- Done! ---"
REMOTE

echo ""
echo "[4/5] Checking bot status..."
sshpass -p 'test1234' ssh -o StrictHostKeyChecking=no opc@$IP "pgrep -f index-server && echo 'BOT IS RUNNING' || echo 'ERROR: bot not started'"

echo ""
echo "=== SUCCESS ==="
echo "Bot URL: send /start to your Telegram bot"
echo "Logs: ssh opc@$IP 'tail -f /var/log/apex-bot.log'"
echo ""

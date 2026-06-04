const https = require('https');

class TelegramBot {
  constructor(token, chatId) {
    this.token = token;
    this.chatId = chatId;
    this.apiBase = `https://api.telegram.org/bot${token}`;
    this.onStop = null;    // callback when /stop is issued
    this.onStatus = null;  // callback for /status
    this.polling = false;
    this.lastUpdateId = 0;
  }

  async send(text) {
    if (!this.token || !this.chatId) return;
    try {
      const body = JSON.stringify({ chat_id: this.chatId, text, parse_mode: 'HTML' });
      await new Promise((resolve, reject) => {
        const req = https.request(
          `${this.apiBase}/sendMessage`,
          { method: 'POST', headers: { 'Content-Type': 'application/json' } },
          (res) => { res.on('data', () => {}); res.on('end', resolve); }
        );
        req.on('error', reject);
        req.write(body);
        req.end();
      });
    } catch (err) {
      console.error('[Telegram] send error:', err.message);
    }
  }

  async _getUpdates() {
    return new Promise((resolve) => {
      const url = `${this.apiBase}/getUpdates?offset=${this.lastUpdateId + 1}&timeout=10`;
      https.get(url, (res) => {
        let data = '';
        res.on('data', (chunk) => { data += chunk; });
        res.on('end', () => {
          try { resolve(JSON.parse(data)); }
          catch { resolve({ ok: false }); }
        });
      }).on('error', () => resolve({ ok: false }));
    });
  }

  async startPolling() {
    if (this.polling) return;
    this.polling = true;
    console.log('[Telegram] Polling started');

    const poll = async () => {
      if (!this.polling) return;
      try {
        const data = await this._getUpdates();
        if (data.ok && data.result) {
          for (const update of data.result) {
            this.lastUpdateId = update.update_id;
            const text = update.message?.text?.trim();
            const from = update.message?.chat?.id?.toString();

            // Only respond to configured chat
            if (from !== this.chatId?.toString()) continue;

            if (text === '/stop' || text?.startsWith('/stop@')) {
              await this.send('⛔ <b>Bot oprit!</b> Toate pozițiile deschise vor fi închise.');
              if (this.onStop) await this.onStop();
            } else if (text === '/status' || text?.startsWith('/status@')) {
              const status = this.onStatus ? await this.onStatus() : 'Bot activ.';
              await this.send(`📊 <b>Status</b>\n${status}`);
            } else if (text === '/help' || text === '/start') {
              await this.send(
                '🤖 <b>Apex Trade Bot</b>\n\n' +
                '/status — Poziții curente și P&L\n' +
                '/stop — Oprește botul de urgență\n' +
                '/help — Această listă'
              );
            }
          }
        }
      } catch (err) {
        console.error('[Telegram] poll error:', err.message);
      }
      setTimeout(poll, 3000);
    };

    poll();
  }

  stopPolling() {
    this.polling = false;
  }

  async notifyTrade(side, symbol, price, qty, reason = '') {
    const emoji = side === 'BUY' ? '🟢' : '🔴';
    const msg = `${emoji} <b>${side} ${symbol}</b>\nPreț: <code>$${price.toFixed(4)}</code>\nQty: <code>${qty}</code>${reason ? `\nMotiv: ${reason}` : ''}`;
    await this.send(msg);
  }

  async notifyError(msg) {
    await this.send(`⚠️ <b>Eroare:</b> ${msg}`);
  }

  async notifyStarted(strategy, symbol) {
    await this.send(`🚀 <b>Bot pornit</b>\nStrategie: <code>${strategy}</code>\nPereche: <code>${symbol}</code>\n\nTrimite /stop pentru oprire de urgență.`);
  }
}

module.exports = TelegramBot;

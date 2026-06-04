const BinanceExchange = require('./exchange');
const TelegramBot = require('./telegram-bot');
const { createStrategy } = require('./strategies/index');

let _engine = null;

class TradingEngine {
  constructor(config) {
    this.exchange = new BinanceExchange(config.apiKey, config.apiSecret, config.testnet === 'true');
    this.strategy = createStrategy(config.strategy, {
      symbol: config.symbol,
      orderAmount: config.orderAmount,
      intervalHours: config.dcaIntervalHours,
      takeProfitPct: config.takeProfitPct,
      stopLossPct: config.stopLossPct,
      gridLevels: config.gridLevels,
      lowerPrice: config.gridLower,
      upperPrice: config.gridUpper,
      investmentUSDT: config.investmentUSDT,
      interval: config.timeframe,
      maxOrders: config.dcaMaxOrders,
    });

    this.telegram = config.telegramToken && config.telegramChatId
      ? new TelegramBot(config.telegramToken, config.telegramChatId)
      : null;

    this.symbol = config.symbol || 'BTCUSDT';
    this.running = false;
    this.trades = [];
    this.errors = [];
    this.tickIntervalMs = 30 * 1000; // 30s main loop
    this._timer = null;
  }

  async start() {
    if (this.running) return;

    // Validate exchange connection
    const ok = await this.exchange.testConnection();
    if (!ok) {
      const msg = 'Conexiune Binance eșuată — verifică API Key și Secret';
      this.errors.push({ time: new Date().toISOString(), msg });
      if (this.telegram) await this.telegram.notifyError(msg);
      return;
    }

    this.running = true;
    console.log(`[Engine] Started — ${this.strategy.name} on ${this.symbol}`);

    if (this.telegram) {
      this.telegram.onStop = () => this.emergencyStop();
      this.telegram.onStatus = () => this._statusText();
      await this.telegram.startPolling();
      await this.telegram.notifyStarted(this.strategy.name, this.symbol);
    }

    this._tick();
  }

  async _tick() {
    if (!this.running) return;

    try {
      const price = await this.exchange.getPrice(this.symbol);
      const signal = await this.strategy.tick(this.exchange, price);

      if (signal) {
        await this._executeSignal(signal, price);
      }
    } catch (err) {
      console.error('[Engine] tick error:', err.message);
      this.errors.push({ time: new Date().toISOString(), msg: err.message });
      if (this.telegram) await this.telegram.notifyError(err.message);
    }

    this._timer = setTimeout(() => this._tick(), this.tickIntervalMs);
  }

  async _executeSignal(signal, currentPrice) {
    try {
      let order;
      let filledQty = 0;

      if (signal.action === 'BUY') {
        const usdt = signal.quoteAmount || (signal.qty ? signal.qty * currentPrice : 0);
        if (usdt < 5) return; // Binance min order
        order = await this.exchange.buyMarket(this.symbol, usdt);
        filledQty = parseFloat(order.executedQty || signal.qty || 0);
      } else if (signal.action === 'SELL') {
        const lot = await this.exchange.getLotSize(this.symbol);
        const qty = this.exchange.roundQty(signal.qty, lot.stepSize);
        if (qty < lot.minQty) return;
        order = await this.exchange.sellMarket(this.symbol, qty);
        filledQty = parseFloat(order.executedQty || qty);
      }

      const fillPrice = order?.fills?.[0]
        ? order.fills.reduce((acc, f) => acc + parseFloat(f.price) * parseFloat(f.qty), 0) / filledQty
        : currentPrice;

      this.strategy.onOrderFilled(signal.action, fillPrice, filledQty);

      const trade = { time: new Date().toISOString(), side: signal.action, price: fillPrice, qty: filledQty, reason: signal.reason };
      this.trades.unshift(trade);
      if (this.trades.length > 200) this.trades.pop();

      if (this.telegram) {
        await this.telegram.notifyTrade(signal.action, this.symbol, fillPrice, filledQty, signal.reason);
      }

      console.log(`[Engine] ${signal.action} ${filledQty} ${this.symbol} @ $${fillPrice.toFixed(4)} — ${signal.reason}`);
    } catch (err) {
      console.error('[Engine] order error:', err.message);
      if (this.telegram) await this.telegram.notifyError(`Order failed: ${err.message}`);
    }
  }

  async emergencyStop() {
    this.running = false;
    if (this._timer) clearTimeout(this._timer);

    try {
      await this.exchange.cancelAllOrders(this.symbol);
    } catch {}

    if (this.telegram) {
      await this.telegram.send('⛔ <b>Bot oprit complet.</b> Toate ordinele anulate.');
      this.telegram.stopPolling();
    }

    console.log('[Engine] Emergency stop executed');
  }

  async _statusText() {
    try {
      const price = await this.exchange.getPrice(this.symbol);
      const balance = await this.exchange.getUSDTBalance();
      const stratStatus = this.strategy.getStatus();
      const lastTrades = this.trades.slice(0, 3).map((t) => `${t.side} $${t.price.toFixed(2)} — ${t.reason}`).join('\n') || 'Nicio tranzacție încă';

      return `Preț ${this.symbol}: <code>$${price.toFixed(2)}</code>\n` +
        `Sold USDT: <code>$${balance.toFixed(2)}</code>\n` +
        `Strategie: <code>${stratStatus.strategy}</code>\n` +
        `Tranzacții recente:\n${lastTrades}`;
    } catch {
      return 'Status indisponibil momentan.';
    }
  }

  getStatus() {
    return {
      running: this.running,
      symbol: this.symbol,
      strategy: this.strategy.getStatus(),
      trades: this.trades.slice(0, 20),
      errors: this.errors.slice(0, 5),
    };
  }

  stop() {
    this.running = false;
    if (this._timer) clearTimeout(this._timer);
    if (this.telegram) this.telegram.stopPolling();
  }
}

function getEngine() { return _engine; }

function initEngine(config) {
  if (_engine) _engine.stop();
  _engine = new TradingEngine(config);
  return _engine;
}

module.exports = { TradingEngine, getEngine, initEngine };

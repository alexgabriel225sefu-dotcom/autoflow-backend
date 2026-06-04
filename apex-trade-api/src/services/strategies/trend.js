// Trend Following — EMA 20/50 crossover pe 1h + confirmare RSI
class TrendStrategy {
  constructor(params = {}) {
    this.symbol = params.symbol || 'BTCUSDT';
    this.orderAmount = parseFloat(params.orderAmount || 50); // USDT
    this.stopLossPct = parseFloat(params.stopLossPct || 2.5) / 100;
    this.takeProfitPct = parseFloat(params.takeProfitPct || 6) / 100;
    this.interval = params.interval || '1h';
    this.name = 'Trend';

    this.position = null;
    this.lastTickTime = 0;
    this.tickIntervalMs = 60 * 60 * 1000; // 1h check
  }

  _calcEMA(closes, period) {
    if (closes.length < period) return closes[closes.length - 1] || 0;
    const k = 2 / (period + 1);
    let ema = closes.slice(0, period).reduce((a, b) => a + b, 0) / period;
    for (let i = period; i < closes.length; i++) {
      ema = closes[i] * k + ema * (1 - k);
    }
    return ema;
  }

  _calcRSI(closes, period = 14) {
    if (closes.length < period + 1) return 50;
    let gains = 0, losses = 0;
    for (let i = closes.length - period; i < closes.length; i++) {
      const diff = closes[i] - closes[i - 1];
      if (diff > 0) gains += diff;
      else losses -= diff;
    }
    const avgGain = gains / period;
    const avgLoss = losses / period;
    if (avgLoss === 0) return 100;
    return 100 - 100 / (1 + avgGain / avgLoss);
  }

  async tick(exchange, currentPrice) {
    const now = Date.now();
    if (now - this.lastTickTime < this.tickIntervalMs) return null;
    this.lastTickTime = now;

    // Manage open position
    if (this.position) {
      const pnl = (currentPrice - this.position.entryPrice) / this.position.entryPrice;
      if (pnl <= -this.stopLossPct) {
        const pos = this.position;
        this.position = null;
        return { action: 'SELL', qty: pos.qty, price: currentPrice, reason: `SL ${(pnl * 100).toFixed(2)}%` };
      }
      if (pnl >= this.takeProfitPct) {
        const pos = this.position;
        this.position = null;
        return { action: 'SELL', qty: pos.qty, price: currentPrice, reason: `TP +${(pnl * 100).toFixed(2)}%` };
      }
      // Check death cross (EMA bearish cross) — close position early
      try {
        const klines = await exchange.getKlines(this.symbol, this.interval, 60);
        const closes = klines.map((k) => k.close);
        const ema20 = this._calcEMA(closes, 20);
        const ema50 = this._calcEMA(closes, 50);
        const prevEma20 = this._calcEMA(closes.slice(0, -1), 20);
        const prevEma50 = this._calcEMA(closes.slice(0, -1), 50);

        if (ema20 < ema50 && prevEma20 >= prevEma50) {
          const pos = this.position;
          this.position = null;
          return { action: 'SELL', qty: pos.qty, price: currentPrice, reason: 'Death cross' };
        }
      } catch {}
      return null;
    }

    // Look for entry signal
    try {
      const klines = await exchange.getKlines(this.symbol, this.interval, 60);
      const closes = klines.map((k) => k.close);
      const ema20 = this._calcEMA(closes, 20);
      const ema50 = this._calcEMA(closes, 50);
      const prevEma20 = this._calcEMA(closes.slice(0, -1), 20);
      const prevEma50 = this._calcEMA(closes.slice(0, -1), 50);
      const rsi = this._calcRSI(closes);

      // Golden cross + RSI not overbought
      if (ema20 > ema50 && prevEma20 <= prevEma50 && rsi < 70) {
        return { action: 'BUY', quoteAmount: this.orderAmount, price: currentPrice, reason: `Golden cross, RSI ${rsi.toFixed(1)}` };
      }
    } catch (err) {
      console.error('[Trend] tick error:', err.message);
    }

    return null;
  }

  onOrderFilled(side, price, qty) {
    if (side === 'BUY') {
      this.position = { entryPrice: price, qty };
    } else {
      this.position = null;
    }
  }

  getStatus() {
    return {
      strategy: 'Trend',
      hasPosition: !!this.position,
      entryPrice: this.position?.entryPrice || null,
      positionQty: this.position?.qty || 0,
      interval: this.interval,
    };
  }
}

module.exports = TrendStrategy;

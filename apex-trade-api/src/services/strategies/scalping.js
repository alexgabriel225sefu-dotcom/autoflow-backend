// Scalping — tranzacții rapide pe semnale RSI + EMA (5 minute)
class ScalpingStrategy {
  constructor(params = {}) {
    this.symbol = params.symbol || 'BTCUSDT';
    this.orderAmount = parseFloat(params.orderAmount || 30); // USDT
    this.stopLossPct = parseFloat(params.stopLossPct || 1) / 100;
    this.takeProfitPct = parseFloat(params.takeProfitPct || 1.5) / 100;
    this.name = 'Scalping';

    this.position = null;
    this.lastTickTime = 0;
    this.tickIntervalMs = 5 * 60 * 1000; // 5 minutes
    this.closesCache = [];
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
    const rs = avgGain / avgLoss;
    return 100 - 100 / (1 + rs);
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

  async tick(exchange, currentPrice) {
    const now = Date.now();
    if (now - this.lastTickTime < this.tickIntervalMs) return null;
    this.lastTickTime = now;

    // Check stop-loss / take-profit on open position
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
      return null;
    }

    // Get klines and calculate indicators
    try {
      const klines = await exchange.getKlines(this.symbol, '5m', 50);
      const closes = klines.map((k) => k.close);
      this.closesCache = closes;

      const rsi = this._calcRSI(closes);
      const ema9 = this._calcEMA(closes, 9);
      const ema21 = this._calcEMA(closes, 21);
      const prevEma9 = this._calcEMA(closes.slice(0, -1), 9);
      const prevEma21 = this._calcEMA(closes.slice(0, -1), 21);

      // BUY: RSI oversold + EMA crossover up
      if (rsi < 40 && ema9 > ema21 && prevEma9 <= prevEma21) {
        return { action: 'BUY', quoteAmount: this.orderAmount, price: currentPrice, reason: `RSI ${rsi.toFixed(1)} + EMA cross up` };
      }

      // SELL SHORT signal (if no position, just skip — no shorting on spot)
      return null;
    } catch (err) {
      console.error('[Scalping] tick error:', err.message);
      return null;
    }
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
      strategy: 'Scalping',
      hasPosition: !!this.position,
      entryPrice: this.position?.entryPrice || null,
      positionQty: this.position?.qty || 0,
    };
  }
}

module.exports = ScalpingStrategy;

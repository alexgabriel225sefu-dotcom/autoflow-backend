// DCA — cumperi o sumă fixă la intervale regulate, vinzi când ai profit
class DCAStrategy {
  constructor(params = {}) {
    this.symbol = params.symbol || 'BTCUSDT';
    this.orderAmount = parseFloat(params.orderAmount || 20); // USDT per order
    this.intervalMs = (parseInt(params.intervalHours || 4)) * 3600 * 1000;
    this.takeProfitPct = parseFloat(params.takeProfitPct || 3) / 100;
    this.maxOrders = parseInt(params.maxOrders || 10);

    this.orders = [];
    this.lastOrderTime = 0;
    this.name = 'DCA';
  }

  getAvgEntry() {
    if (!this.orders.length) return 0;
    const totalCost = this.orders.reduce((s, o) => s + o.price * o.qty, 0);
    const totalQty = this.orders.reduce((s, o) => s + o.qty, 0);
    return totalQty > 0 ? totalCost / totalQty : 0;
  }

  getTotalQty() {
    return this.orders.reduce((s, o) => s + o.qty, 0);
  }

  async tick(exchange, currentPrice) {
    const now = Date.now();
    const totalQty = this.getTotalQty();

    // Sell if profit target reached
    if (totalQty > 0) {
      const avgEntry = this.getAvgEntry();
      const profit = (currentPrice - avgEntry) / avgEntry;
      if (profit >= this.takeProfitPct) {
        return { action: 'SELL', qty: totalQty, price: currentPrice, reason: `TP +${(profit * 100).toFixed(2)}%` };
      }
    }

    // Buy at interval
    if (now - this.lastOrderTime >= this.intervalMs && this.orders.length < this.maxOrders) {
      this.lastOrderTime = now;
      return { action: 'BUY', quoteAmount: this.orderAmount, price: currentPrice, reason: 'DCA interval' };
    }

    return null;
  }

  onOrderFilled(side, price, qty) {
    if (side === 'BUY') {
      this.orders.push({ price, qty });
    } else {
      this.orders = []; // reset after sell
    }
  }

  getStatus() {
    const totalQty = this.getTotalQty();
    const avgEntry = this.getAvgEntry();
    return {
      strategy: 'DCA',
      orders: this.orders.length,
      totalQty,
      avgEntry,
      nextOrderIn: Math.max(0, this.intervalMs - (Date.now() - this.lastOrderTime)),
    };
  }
}

module.exports = DCAStrategy;

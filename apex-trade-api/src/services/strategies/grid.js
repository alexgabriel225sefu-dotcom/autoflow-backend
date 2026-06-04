// Grid Trading — plasezi ordine la intervale de preț, câștigi din oscilații
class GridStrategy {
  constructor(params = {}) {
    this.symbol = params.symbol || 'BTCUSDT';
    this.lowerPrice = parseFloat(params.lowerPrice || 0);  // 0 = auto-calc
    this.upperPrice = parseFloat(params.upperPrice || 0);  // 0 = auto-calc
    this.gridLevels = parseInt(params.gridLevels || 10);
    this.investmentUSDT = parseFloat(params.investmentUSDT || 100);
    this.name = 'Grid';

    this.grid = [];         // { price, side, filled, qty }
    this.initialized = false;
    this.totalProfit = 0;
  }

  _buildGrid(currentPrice) {
    // Auto range: ±10% of current price
    const lower = this.lowerPrice || currentPrice * 0.90;
    const upper = this.upperPrice || currentPrice * 1.10;
    const step = (upper - lower) / (this.gridLevels - 1);
    const amountPerGrid = this.investmentUSDT / this.gridLevels;

    this.grid = [];
    for (let i = 0; i < this.gridLevels; i++) {
      const price = lower + step * i;
      this.grid.push({
        price: Math.round(price * 100) / 100,
        side: price < currentPrice ? 'BUY' : 'SELL',
        filled: false,
        qty: amountPerGrid / price,
      });
    }
    this.initialized = true;
    console.log(`[Grid] Built ${this.gridLevels} levels from $${lower.toFixed(2)} to $${upper.toFixed(2)}`);
  }

  _findTriggeredLevel(currentPrice) {
    for (const level of this.grid) {
      if (level.filled) continue;
      if (level.side === 'BUY' && currentPrice <= level.price) return level;
      if (level.side === 'SELL' && currentPrice >= level.price) return level;
    }
    return null;
  }

  async tick(exchange, currentPrice) {
    if (!this.initialized) {
      this._buildGrid(currentPrice);
      return null;
    }

    const level = this._findTriggeredLevel(currentPrice);
    if (!level) return null;

    level.filled = true;

    // After filling a BUY, place a SELL one level above (and vice versa)
    const idx = this.grid.indexOf(level);
    if (level.side === 'BUY' && idx < this.grid.length - 1) {
      const above = this.grid[idx + 1];
      if (above.filled) above.filled = false; // re-arm
    } else if (level.side === 'SELL' && idx > 0) {
      const below = this.grid[idx - 1];
      if (below.filled) below.filled = false;
    }

    return {
      action: level.side,
      qty: level.qty,
      price: currentPrice,
      reason: `Grid level $${level.price}`,
    };
  }

  onOrderFilled(side, price, qty) {
    const step = this.grid.length > 1
      ? Math.abs(this.grid[1].price - this.grid[0].price)
      : 0;
    if (side === 'SELL') {
      this.totalProfit += qty * step * 0.8; // approx grid profit
    }
  }

  getStatus() {
    const filledBuys = this.grid.filter((g) => g.side === 'BUY' && g.filled).length;
    const filledSells = this.grid.filter((g) => g.side === 'SELL' && g.filled).length;
    return {
      strategy: 'Grid',
      levels: this.grid.length,
      filledBuys,
      filledSells,
      totalProfit: this.totalProfit,
      initialized: this.initialized,
    };
  }
}

module.exports = GridStrategy;

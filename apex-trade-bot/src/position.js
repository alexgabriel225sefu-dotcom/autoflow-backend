/**
 * Exit management — SL/TP, breakeven, trailing, runner mode.
 */
const cfg    = require('./config');
const logger = require('./logger');

function calcSLTP(side, price, atrValue) {
  if (cfg.ATR_BASED_SL && atrValue > 0) {
    const slDist = atrValue * cfg.ATR_SL_MULT;
    const tpDist = atrValue * cfg.ATR_TP_MULT;
    return {
      stopLoss:   side === 'BUY' ? price - slDist : price + slDist,
      takeProfit: side === 'BUY' ? price + tpDist : price - tpDist,
    };
  }
  return {
    stopLoss:   side === 'BUY' ? price * (1 - cfg.STOP_LOSS_PCT)   : price * (1 + cfg.STOP_LOSS_PCT),
    takeProfit: side === 'BUY' ? price * (1 + cfg.TAKE_PROFIT_PCT) : price * (1 - cfg.TAKE_PROFIT_PCT),
  };
}

function checkPosition(pos, price) {
  if (!pos) return null;
  const { side, entryPrice, takeProfit } = pos;

  if (cfg.BREAKEVEN_AT_R > 0 && !pos.beDone && pos.initialStop) {
    const oneR = Math.abs(entryPrice - pos.initialStop) * cfg.BREAKEVEN_AT_R;
    const bePrice = side === 'BUY' ? entryPrice * (1 + 2 * cfg.FEE_PCT) : entryPrice * (1 - 2 * cfg.FEE_PCT);
    if ((side === 'BUY' && price >= entryPrice + oneR && bePrice > pos.stopLoss) ||
        (side === 'SELL' && price <= entryPrice - oneR && bePrice < pos.stopLoss)) {
      Object.assign(pos, { stopLoss: bePrice, beDone: true });
      logger.info(`🛡️ Breakeven: SL moved to $${bePrice.toFixed(5)} — risk-free trade`);
    }
  }

  if (cfg.TRAILING_STOP) {
    const dist = pos.runner ? cfg.RUNNER_TRAIL_DIST : cfg.TRAILING_STOP_DIST;
    if (side === 'BUY') {
      pos.trailHigh = Math.max(pos.trailHigh ?? price, price);
      pos.stopLoss  = Math.max(pos.stopLoss, pos.trailHigh * (1 - dist));
    } else {
      pos.trailLow  = Math.min(pos.trailLow ?? price, price);
      pos.stopLoss  = Math.min(pos.stopLoss, pos.trailLow * (1 + dist));
    }
  }

  pos.pnlPct = (side === 'BUY' ? price - entryPrice : entryPrice - price) / entryPrice * 100;

  const hitSL = side === 'BUY' ? price <= pos.stopLoss : price >= pos.stopLoss;
  const hitTP = side === 'BUY' ? price >= takeProfit   : price <= takeProfit;

  if (hitSL) return pos.runner ? 'TRAIL_PROFIT' : 'STOP_LOSS';
  if (hitTP && !pos.runner) {
    if (cfg.LET_WINNERS_RUN && cfg.TRAILING_STOP && cfg.PAPER_TRADING) {
      pos.runner = true;
      logger.info(`🏃 TP reached at $${price} — runner mode: letting profits run (trail ${cfg.RUNNER_TRAIL_DIST * 100}%)`);
      return null;
    }
    return 'TAKE_PROFIT';
  }
  return null;
}

module.exports = { calcSLTP, checkPosition };

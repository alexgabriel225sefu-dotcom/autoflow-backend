const DCAStrategy = require('./dca');
const GridStrategy = require('./grid');
const ScalpingStrategy = require('./scalping');
const TrendStrategy = require('./trend');

const STRATEGIES = {
  dca: {
    name: 'DCA (Dollar Cost Averaging)',
    description: 'Cumperi o sumă fixă la intervale regulate. Cel mai safe — funcționează pe orice piață.',
    risk: 'Scăzut',
    Class: DCAStrategy,
  },
  grid: {
    name: 'Grid Trading',
    description: 'Plasezi ordine la intervale de preț fixe. Câștigi din oscilațiile prețului.',
    risk: 'Mediu',
    Class: GridStrategy,
  },
  scalping: {
    name: 'Scalping (RSI + EMA)',
    description: 'Tranzacții rapide de câteva minute bazate pe RSI și crossover EMA.',
    risk: 'Ridicat',
    Class: ScalpingStrategy,
  },
  trend: {
    name: 'Trend Following (EMA 20/50)',
    description: 'Urmărești trendul pe timeframe de 1h. Intri la golden cross, ieși la death cross.',
    risk: 'Mediu',
    Class: TrendStrategy,
  },
};

function createStrategy(name, params = {}) {
  const def = STRATEGIES[name];
  if (!def) throw new Error(`Strategie necunoscută: ${name}. Disponibile: ${Object.keys(STRATEGIES).join(', ')}`);
  return new def.Class(params);
}

module.exports = { STRATEGIES, createStrategy };

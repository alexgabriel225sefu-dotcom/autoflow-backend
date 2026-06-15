/**
 * Exchange factory — selects the connector based on cfg.EXCHANGE.
 * All connectors expose the same interface: getPrice, getCandles, getBalance, placeOrder.
 */
const cfg = require('./config');

const REGISTRY = {
  binance:  () => require('./binance'),
  bybit:    () => require('./bybit'),
  okx:      () => require('./okx'),
  kraken:   () => require('./kraken'),
  kucoin:   () => require('./kucoin'),
  coinbase: () => require('./coinbase'),
  bitget:   () => require('./bitget'),
  mexc:     () => require('./mexc'),
};

const name = (cfg.EXCHANGE || 'binance').toLowerCase();
const loader = REGISTRY[name];

if (!loader) {
  throw new Error(
    `Unsupported EXCHANGE="${cfg.EXCHANGE}". Supported: ${Object.keys(REGISTRY).join(', ')}`
  );
}

module.exports = loader();
module.exports.__name = name;

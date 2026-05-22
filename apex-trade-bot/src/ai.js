const Anthropic = require('@anthropic-ai/sdk');
const cfg = require('./config');

let client = null;
function getClient() {
  if (!client) client = new Anthropic({ apiKey: cfg.ANTHROPIC_API_KEY });
  return client;
}

async function getSignal(indicators, balance, openPosition) {
  const rsi   = parseFloat(indicators.rsi);
  const srsiK = parseFloat(indicators.stochRsiK);
  const macdH = parseFloat(indicators.macdHist);
  const volR  = parseFloat(indicators.volumeRatio);
  const bbPos = parseFloat(indicators.bb_position);

  const prompt = `Ești un trader profesionist cu 20 ani experiență în crypto spot trading. Analizează TOATE datele și dă un semnal precis.

## MARKET DATA — ${cfg.SYMBOL} (${cfg.TIMEFRAME})
### Preț & Trend
- Preț curent: $${indicators.price}
- EMA 20: ${indicators.ema20} | EMA 50: ${indicators.ema50} | EMA 200: ${indicators.ema200}
- Trend EMA20/50: ${indicators.emaTrend} | Trend EMA50/200: ${indicators.ema200Trend}
- Preț vs EMA20: ${indicators.priceVsEma20}
- Structura pieței: ${indicators.marketStructure}

### Momentum
- RSI (14): ${indicators.rsi} ${rsi < 30 ? '⚡ OVERSOLD EXTREM' : rsi < 40 ? '📉 Oversold' : rsi > 70 ? '🔥 OVERBOUGHT EXTREM' : rsi > 60 ? '📈 Overbought' : '⚖️ Neutru'}
- Stoch RSI K: ${indicators.stochRsiK} | D: ${indicators.stochRsiD} ${srsiK < 20 ? '⚡ Oversold' : srsiK > 80 ? '🔥 Overbought' : ''}
- MACD: ${indicators.macd} | Signal: ${indicators.macdSignal}
- MACD Histogram: ${indicators.macdHist} ${macdH > 0 ? '▲ Bullish' : '▼ Bearish'}
- Divergență RSI: ${indicators.divergence} ${indicators.divergence !== 'NONE' ? '⚡ SEMNAL PUTERNIC!' : ''}

### Volatilitate & Volum
- ATR: ${indicators.atr} (${indicators.atrPct}% din preț)
- Bollinger Bands: Upper=${indicators.bb_upper} | Mid=${indicators.bb_mid} | Lower=${indicators.bb_lower}
- BB Bandwidth: ${indicators.bb_bandwidth}% | Poziție în BB: ${indicators.bb_position}% ${bbPos < 15 ? '📉 Aproape de lower' : bbPos > 85 ? '📈 Aproape de upper' : ''}
- Volum curent: ${indicators.volume} | Avg 20: ${indicators.volumeAvg} | Ratio: ${indicators.volumeRatio}× ${volR > 1.5 ? '⚡ VOLUM MARE (confirmare)' : volR < 0.7 ? '⚠️ Volum mic' : ''}
- High 24h: ${indicators.high24h} | Low 24h: ${indicators.low24h}

### Ultimele 5 lumânări
${indicators.recentCandles.map((c, i) => `${i+1}. ${c.direction} O:${c.open} H:${c.high} L:${c.low} C:${c.close} (body: ${c.bodyPct}%)`).join('\n')}

## CONT
- Balanță: $${balance.toFixed(2)} USDT
- Poziție deschisă: ${openPosition ? `${openPosition.side} @ $${openPosition.entryPrice} | SL: $${openPosition.stopLoss?.toFixed(5)} | TP: $${openPosition.takeProfit?.toFixed(5)} | PnL: ${openPosition.pnlPct?.toFixed(2)}% | Trail high: $${openPosition.trailHigh?.toFixed(5) ?? 'N/A'}` : 'NICIUNA'}

## REGULI STRICTE
- Stop Loss: ${cfg.STOP_LOSS_PCT * 100}% | Take Profit: ${cfg.TAKE_PROFIT_PCT * 100}% | Risc: ${cfg.RISK_PER_TRADE * 100}% din balanță
- NU deschide dacă există deja o poziție (folosește CLOSE/HOLD)
- CLOSE = închide acum dacă poziția e în pericol sau a atins obiectivul
- Minimum confidence pentru execuție: ${cfg.MIN_CONFIDENCE}%
- Preferă BUY în uptrend, SELL în downtrend — nu tranzacționa contra trendului major

## CRITERII INTRARE (cel puțin 3 din 5 trebuie îndeplinite)
**BUY**: ema20>ema50, RSI<50 sau divergență bullish, MACD hist în creștere, volum>1.2×, preț la/sub EMA20 sau BB lower
**SELL**: ema20<ema50, RSI>50 sau divergență bearish, MACD hist în scădere, volum>1.2×, preț la/peste EMA20 sau BB upper

## TASK
Răspunde DOAR cu JSON valid:
{
  "action": "BUY" | "SELL" | "HOLD" | "CLOSE",
  "confidence": <0-100>,
  "reasoning": "<max 2 propoziții în română — explică DE CE>",
  "riskLevel": "LOW" | "MEDIUM" | "HIGH",
  "keyFactors": ["<factor1>", "<factor2>", "<factor3>"],
  "criteriaScore": <număr 0-5 criterii de intrare îndeplinite>
}`;

  // Modele în ordine de preferință (cel nou → fallback la cel vechi)
  const MODELS = [
    'claude-haiku-4-5-20251001',
    'claude-3-5-haiku-20241022',
    'claude-3-haiku-20240307',
  ];

  for (const model of MODELS) {
    try {
      const msg = await getClient().messages.create({
        model,
        max_tokens: 400,
        temperature: 0,
        messages: [{ role: 'user', content: prompt }],
      });
      const text  = msg.content[0].text.trim();
      const match = text.match(/\{[\s\S]*\}/);
      if (!match) throw new Error('No JSON in response');
      const result = JSON.parse(match[0]);
      if (model !== MODELS[0]) console.log(`[AI] Folosesc model fallback: ${model}`);
      return result;
    } catch (err) {
      console.error(`[AI] Model ${model} failed: ${err.message}`);
    }
  }
  return { action: 'HOLD', confidence: 0, reasoning: 'Eroare AI — HOLD implicit', riskLevel: 'HIGH', keyFactors: [], criteriaScore: 0 };
}

module.exports = { getSignal };

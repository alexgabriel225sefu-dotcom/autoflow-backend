const Anthropic = require('@anthropic-ai/sdk');
const cfg = require('./config');

let client = null;
function getClient() {
  if (!client) client = new Anthropic({ apiKey: cfg.ANTHROPIC_API_KEY });
  return client;
}

async function getSignal(indicators, balance, openPosition) {
  const prompt = `Ești un trader quant expert cu 20 ani experiență. Analizează datele și decide dacă să tranzacționezi.

## Date piață — ${cfg.SYMBOL} (${cfg.TIMEFRAME})
- Preț curent: $${indicators.price}
- RSI (14): ${indicators.rsi} ${parseFloat(indicators.rsi) < 30 ? '← OVERSOLD' : parseFloat(indicators.rsi) > 70 ? '← OVERBOUGHT' : ''}
- MACD: ${indicators.macd} | Signal: ${indicators.macdSignal} | Histogram: ${indicators.macdHist}
- EMA 20: ${indicators.ema20} | EMA 50: ${indicators.ema50} | Trend: ${indicators.emaTrend}
- Preț vs EMA20: ${indicators.priceVsEma20}
- Bollinger Bands: Upper=${indicators.bb_upper} | Mid=${indicators.bb_mid} | Lower=${indicators.bb_lower}
- Volum curent: ${indicators.volume} | Medie 20: ${indicators.volumeAvg}
- High 24h: ${indicators.high24h} | Low 24h: ${indicators.low24h}

## Ultimele 5 lumânări
${indicators.recentCandles.map((c, i) => `${i+1}. ${c.direction} O:${c.open} H:${c.high} L:${c.low} C:${c.close}`).join('\n')}

## Context cont
- Balanță disponibilă: $${balance.toFixed(2)} USDT
- Poziție deschisă: ${openPosition ? `${openPosition.side} @ $${openPosition.entryPrice} (PnL: ${openPosition.pnlPct?.toFixed(2)}%)` : 'NICIUNA'}

## Reguli obligatorii
- Stop Loss: -${cfg.STOP_LOSS_PCT * 100}% | Take Profit: +${cfg.TAKE_PROFIT_PCT * 100}%
- Risc per tranzacție: max ${cfg.RISK_PER_TRADE * 100}% din balanță
- NU deschide poziție dacă există deja una deschisă (închide-o dacă e cazul)
- Minimum confidence pentru execuție: ${cfg.MIN_CONFIDENCE}%

## Task
Răspunde DOAR cu JSON valid, fără alt text:
{
  "action": "BUY" | "SELL" | "HOLD" | "CLOSE",
  "confidence": <număr 0-100>,
  "reasoning": "<explicație scurtă în română, max 2 propoziții>",
  "riskLevel": "LOW" | "MEDIUM" | "HIGH",
  "keyFactors": ["<factor1>", "<factor2>", "<factor3>"]
}

CLOSE = închide poziția curentă dacă există.
BUY/SELL = deschide poziție nouă (nu dacă există deja una).
HOLD = nu face nimic.`;

  try {
    const msg = await getClient().messages.create({
      model: 'claude-haiku-4-5-20251001',
      max_tokens: 300,
      messages: [{ role: 'user', content: prompt }],
    });

    const text = msg.content[0].text.trim();
    // Extract JSON even if surrounded by markdown
    const match = text.match(/\{[\s\S]*\}/);
    if (!match) throw new Error('No JSON in response');
    return JSON.parse(match[0]);
  } catch (err) {
    console.error('[AI] Error:', err.message);
    return { action: 'HOLD', confidence: 0, reasoning: 'Eroare AI — HOLD implicit', riskLevel: 'HIGH', keyFactors: [] };
  }
}

module.exports = { getSignal };

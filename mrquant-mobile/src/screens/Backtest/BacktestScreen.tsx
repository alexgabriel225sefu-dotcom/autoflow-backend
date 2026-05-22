import React, { useState, useEffect } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  TextInput, ActivityIndicator, Alert,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { backtestAPI, BacktestParams } from '../../services/api';
import { Colors, FontSize, Spacing, BorderRadius } from '../../theme/colors';

const STRATEGIES = [
  { id: 'rsi_macd', name: 'RSI + MACD', description: 'Combinație clasică momentum' },
  { id: 'bb_rsi', name: 'Bollinger Bands + RSI', description: 'Mean reversion strategy' },
  { id: 'ema_crossover', name: 'EMA Crossover', description: 'Golden/Death cross' },
  { id: 'breakout', name: 'Breakout Strategy', description: 'Rupere nivele cheie' },
  { id: 'ai_adaptive', name: '🤖 AI Adaptive', description: 'Strategy adaptivă ML' },
];

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];
const MARKETS = ['crypto', 'stocks', 'forex'];

interface BacktestResult {
  id: string;
  totalReturn: number;
  annualizedReturn: number;
  sharpeRatio: number;
  maxDrawdown: number;
  winRate: number;
  totalTrades: number;
  profitFactor: number;
  avgTradeReturn: number;
  equityCurve: { date: string; value: number }[];
  trades: {
    date: string;
    action: string;
    price: number;
    pnl: number;
    pnlPercent: number;
  }[];
}

export default function BacktestScreen() {
  const [strategies, setStrategies] = useState<typeof STRATEGIES>([]);
  const [selectedStrategy, setSelectedStrategy] = useState(STRATEGIES[0]);
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [market, setMarket] = useState('crypto');
  const [startDate, setStartDate] = useState('2024-01-01');
  const [endDate, setEndDate] = useState('2024-12-31');
  const [capital, setCapital] = useState('10000');
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<BacktestResult | null>(null);
  const [tab, setTab] = useState<'setup' | 'result'>('setup');

  useEffect(() => {
    backtestAPI.getStrategies()
      .then((res) => setStrategies(res.data))
      .catch(() => setStrategies(STRATEGIES));
  }, []);

  const runBacktest = async () => {
    if (!symbol.trim()) {
      Alert.alert('Eroare', 'Introduceți simbolul');
      return;
    }
    setRunning(true);
    try {
      const params: BacktestParams = {
        strategy: selectedStrategy.id,
        symbol: symbol.trim().toUpperCase(),
        market,
        startDate,
        endDate,
        initialCapital: parseFloat(capital) || 10000,
      };
      const res = await backtestAPI.run(params);
      setResult(res.data);
      setTab('result');
    } catch (err: any) {
      Alert.alert('Eroare', err.response?.data?.message || 'Backtestul a eșuat');
    } finally {
      setRunning(false);
    }
  };

  const MetricCard = ({ label, value, color }: { label: string; value: string; color?: string }) => (
    <View style={styles.metricCard}>
      <Text style={[styles.metricValue, color ? { color } : {}]}>{value}</Text>
      <Text style={styles.metricLabel}>{label}</Text>
    </View>
  );

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Backtest</Text>
        <View style={styles.tabSwitch}>
          <TouchableOpacity
            style={[styles.tabBtn, tab === 'setup' && styles.tabBtnActive]}
            onPress={() => setTab('setup')}
          >
            <Text style={[styles.tabBtnText, tab === 'setup' && styles.tabBtnTextActive]}>Configurare</Text>
          </TouchableOpacity>
          <TouchableOpacity
            style={[styles.tabBtn, tab === 'result' && styles.tabBtnActive]}
            onPress={() => result && setTab('result')}
          >
            <Text style={[styles.tabBtnText, tab === 'result' && styles.tabBtnTextActive]}>Rezultate</Text>
          </TouchableOpacity>
        </View>
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {tab === 'setup' ? (
          <>
            {/* Strategy Selection */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>📋 Strategie</Text>
              {STRATEGIES.map((s) => (
                <TouchableOpacity
                  key={s.id}
                  style={[styles.strategyCard, selectedStrategy.id === s.id && styles.strategyCardActive]}
                  onPress={() => setSelectedStrategy(s)}
                >
                  <View style={styles.strategyInfo}>
                    <Text style={styles.strategyName}>{s.name}</Text>
                    <Text style={styles.strategyDesc}>{s.description}</Text>
                  </View>
                  {selectedStrategy.id === s.id && (
                    <View style={styles.selectedDot} />
                  )}
                </TouchableOpacity>
              ))}
            </View>

            {/* Parameters */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>⚙️ Parametri</Text>

              <View style={styles.inputRow}>
                <View style={[styles.inputGroup, { flex: 2 }]}>
                  <Text style={styles.inputLabel}>Simbol</Text>
                  <TextInput
                    style={styles.input}
                    value={symbol}
                    onChangeText={setSymbol}
                    placeholder="BTCUSDT"
                    placeholderTextColor={Colors.textMuted}
                    autoCapitalize="characters"
                  />
                </View>
                <View style={[styles.inputGroup, { flex: 1 }]}>
                  <Text style={styles.inputLabel}>Piață</Text>
                  <TouchableOpacity
                    style={styles.input}
                    onPress={() => {
                      const idx = MARKETS.indexOf(market);
                      setMarket(MARKETS[(idx + 1) % MARKETS.length]);
                    }}
                  >
                    <Text style={styles.inputValue}>{market}</Text>
                  </TouchableOpacity>
                </View>
              </View>

              <View style={styles.inputRow}>
                <View style={[styles.inputGroup, { flex: 1 }]}>
                  <Text style={styles.inputLabel}>Data început</Text>
                  <TextInput
                    style={styles.input}
                    value={startDate}
                    onChangeText={setStartDate}
                    placeholder="2024-01-01"
                    placeholderTextColor={Colors.textMuted}
                  />
                </View>
                <View style={[styles.inputGroup, { flex: 1 }]}>
                  <Text style={styles.inputLabel}>Data sfârșit</Text>
                  <TextInput
                    style={styles.input}
                    value={endDate}
                    onChangeText={setEndDate}
                    placeholder="2024-12-31"
                    placeholderTextColor={Colors.textMuted}
                  />
                </View>
              </View>

              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>Capital inițial ($)</Text>
                <TextInput
                  style={styles.input}
                  value={capital}
                  onChangeText={setCapital}
                  keyboardType="numeric"
                  placeholder="10000"
                  placeholderTextColor={Colors.textMuted}
                />
              </View>
            </View>

            {/* Run Button */}
            <TouchableOpacity onPress={runBacktest} disabled={running} activeOpacity={0.85}>
              <LinearGradient
                colors={running ? ['#333', '#444'] : ['#0066FF', '#0044CC']}
                style={styles.runButton}
                start={{ x: 0, y: 0 }}
                end={{ x: 1, y: 0 }}
              >
                {running ? (
                  <View style={styles.runningContainer}>
                    <ActivityIndicator color="#fff" size="small" />
                    <Text style={styles.runButtonText}>Procesând milioane de simulări...</Text>
                  </View>
                ) : (
                  <Text style={styles.runButtonText}>🚀 Rulează Backtest</Text>
                )}
              </LinearGradient>
            </TouchableOpacity>
          </>
        ) : result ? (
          <>
            {/* Results Summary */}
            <LinearGradient
              colors={result.totalReturn >= 0 ? ['#003300', '#001a00'] : ['#330000', '#1a0000']}
              style={styles.resultHeader}
            >
              <Text style={styles.resultTitle}>{selectedStrategy.name}</Text>
              <Text style={[
                styles.resultReturn,
                { color: result.totalReturn >= 0 ? Colors.green : Colors.red },
              ]}>
                {result.totalReturn >= 0 ? '+' : ''}{result.totalReturn.toFixed(2)}%
              </Text>
              <Text style={styles.resultLabel}>Return total</Text>
            </LinearGradient>

            {/* Metrics Grid */}
            <View style={styles.metricsGrid}>
              <MetricCard
                label="Return Anual"
                value={`${result.annualizedReturn >= 0 ? '+' : ''}${result.annualizedReturn.toFixed(1)}%`}
                color={result.annualizedReturn >= 0 ? Colors.green : Colors.red}
              />
              <MetricCard label="Sharpe Ratio" value={result.sharpeRatio.toFixed(2)} color={Colors.accent} />
              <MetricCard label="Max Drawdown" value={`${result.maxDrawdown.toFixed(1)}%`} color={Colors.red} />
              <MetricCard label="Win Rate" value={`${result.winRate.toFixed(0)}%`} color={Colors.green} />
              <MetricCard label="Total Trades" value={result.totalTrades.toString()} />
              <MetricCard label="Profit Factor" value={result.profitFactor.toFixed(2)} color={Colors.gold} />
            </View>

            {/* Trades List */}
            <View style={styles.section}>
              <Text style={styles.sectionTitle}>📋 Ultima 10 tranzacții</Text>
              {result.trades.slice(0, 10).map((trade, i) => (
                <View key={i} style={styles.tradeRow}>
                  <View>
                    <Text style={styles.tradeDate}>{trade.date}</Text>
                    <Text style={[
                      styles.tradeAction,
                      { color: trade.action === 'BUY' ? Colors.green : Colors.red },
                    ]}>
                      {trade.action}
                    </Text>
                  </View>
                  <Text style={styles.tradePrice}>${trade.price.toFixed(2)}</Text>
                  <Text style={[
                    styles.tradePnl,
                    { color: trade.pnl >= 0 ? Colors.green : Colors.red },
                  ]}>
                    {trade.pnl >= 0 ? '+' : ''}{trade.pnlPercent.toFixed(2)}%
                  </Text>
                </View>
              ))}
            </View>

            <TouchableOpacity style={styles.newBacktestBtn} onPress={() => setTab('setup')}>
              <Text style={styles.newBacktestText}>← Backtest nou</Text>
            </TouchableOpacity>
          </>
        ) : null}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  header: {
    paddingHorizontal: Spacing.lg,
    paddingTop: 60,
    paddingBottom: Spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  title: { fontSize: FontSize.xxl, fontWeight: '800', color: Colors.textPrimary },
  tabSwitch: { flexDirection: 'row', backgroundColor: Colors.card, borderRadius: BorderRadius.full, padding: 3 },
  tabBtn: { paddingHorizontal: Spacing.md, paddingVertical: 6, borderRadius: BorderRadius.full },
  tabBtnActive: { backgroundColor: Colors.primary },
  tabBtnText: { fontSize: FontSize.xs, color: Colors.textMuted, fontWeight: '600' },
  tabBtnTextActive: { color: Colors.textPrimary },
  content: { paddingHorizontal: Spacing.lg, paddingBottom: 100, gap: Spacing.lg },
  section: { gap: Spacing.sm },
  sectionTitle: { fontSize: FontSize.lg, fontWeight: '700', color: Colors.textPrimary, marginBottom: 4 },
  strategyCard: {
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.md,
    padding: Spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  strategyCardActive: { borderColor: Colors.primary, backgroundColor: Colors.primary + '10' },
  strategyInfo: { flex: 1 },
  strategyName: { fontSize: FontSize.md, fontWeight: '700', color: Colors.textPrimary },
  strategyDesc: { fontSize: FontSize.xs, color: Colors.textMuted, marginTop: 2 },
  selectedDot: { width: 10, height: 10, borderRadius: 5, backgroundColor: Colors.primary },
  inputRow: { flexDirection: 'row', gap: Spacing.md },
  inputGroup: { gap: Spacing.xs },
  inputLabel: { fontSize: FontSize.xs, color: Colors.textSecondary, fontWeight: '500' },
  input: {
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.md,
    paddingHorizontal: Spacing.md,
    paddingVertical: Spacing.md,
    fontSize: FontSize.md,
    color: Colors.textPrimary,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  inputValue: { fontSize: FontSize.md, color: Colors.textPrimary },
  runButton: {
    paddingVertical: Spacing.md + 2,
    borderRadius: BorderRadius.full,
    alignItems: 'center',
  },
  runningContainer: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  runButtonText: { fontSize: FontSize.lg, color: Colors.textPrimary, fontWeight: '700' },
  resultHeader: {
    borderRadius: BorderRadius.xl,
    padding: Spacing.xl,
    alignItems: 'center',
    gap: Spacing.xs,
  },
  resultTitle: { fontSize: FontSize.md, color: Colors.textSecondary },
  resultReturn: { fontSize: 48, fontWeight: '800' },
  resultLabel: { fontSize: FontSize.sm, color: Colors.textMuted },
  metricsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.md },
  metricCard: {
    flex: 1,
    minWidth: '30%',
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.md,
    padding: Spacing.md,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  metricValue: { fontSize: FontSize.lg, fontWeight: '800', color: Colors.textPrimary },
  metricLabel: { fontSize: FontSize.xs, color: Colors.textMuted, marginTop: 2, textAlign: 'center' },
  tradeRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: Spacing.sm,
    borderBottomWidth: 1,
    borderBottomColor: Colors.cardBorder,
  },
  tradeDate: { fontSize: FontSize.xs, color: Colors.textMuted },
  tradeAction: { fontSize: FontSize.sm, fontWeight: '700' },
  tradePrice: { fontSize: FontSize.sm, color: Colors.textPrimary },
  tradePnl: { fontSize: FontSize.sm, fontWeight: '700' },
  newBacktestBtn: {
    alignItems: 'center',
    paddingVertical: Spacing.md,
    borderRadius: BorderRadius.md,
    backgroundColor: Colors.card,
  },
  newBacktestText: { color: Colors.primary, fontWeight: '700', fontSize: FontSize.md },
});

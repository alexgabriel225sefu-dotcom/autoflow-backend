import React, { useEffect, useRef } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  RefreshControl, Animated, Dimensions,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useDispatch, useSelector } from 'react-redux';
import { AppDispatch, RootState } from '../../store';
import { fetchPortfolio } from '../../store/slices/portfolioSlice';
import { fetchSignals } from '../../store/slices/signalsSlice';
import { fetchCrypto, fetchNews } from '../../store/slices/marketsSlice';
import { Colors, FontSize, Spacing, BorderRadius } from '../../theme/colors';

const { width } = Dimensions.get('window');

export default function DashboardScreen({ navigation }: any) {
  const dispatch = useDispatch<AppDispatch>();
  const { summary, positions, loading } = useSelector((s: RootState) => s.portfolio);
  const { signals } = useSelector((s: RootState) => s.signals);
  const { crypto, news } = useSelector((s: RootState) => s.markets);
  const { user } = useSelector((s: RootState) => s.auth);
  const scrollY = useRef(new Animated.Value(0)).current;

  const fetchAll = () => {
    dispatch(fetchPortfolio());
    dispatch(fetchSignals());
    dispatch(fetchCrypto());
    dispatch(fetchNews());
  };

  useEffect(() => { fetchAll(); }, []);

  const headerOpacity = scrollY.interpolate({
    inputRange: [0, 80],
    outputRange: [1, 0],
    extrapolate: 'clamp',
  });

  const pnlColor = (summary?.dailyPnLPercent ?? 0) >= 0 ? Colors.green : Colors.red;
  const activeSignals = signals.filter((s) => s.status === 'active').slice(0, 3);
  const topMovers = [...crypto].sort((a, b) => Math.abs(b.changePercent24h) - Math.abs(a.changePercent24h)).slice(0, 5);

  return (
    <View style={styles.container}>
      {/* Sticky Header */}
      <View style={styles.header}>
        <View>
          <Text style={styles.greeting}>Bună, {user?.name?.split(' ')[0] ?? 'Trader'}! 👋</Text>
          <Text style={styles.subtitle}>Piața e în mișcare</Text>
        </View>
        <TouchableOpacity style={styles.notifBtn}>
          <Text style={styles.notifIcon}>🔔</Text>
        </TouchableOpacity>
      </View>

      <Animated.ScrollView
        onScroll={Animated.event([{ nativeEvent: { contentOffset: { y: scrollY } } }], { useNativeDriver: true })}
        scrollEventThrottle={16}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={fetchAll} tintColor={Colors.primary} />}
        showsVerticalScrollIndicator={false}
        contentContainerStyle={styles.scrollContent}
      >
        {/* Portfolio Card */}
        <LinearGradient colors={['#0A1628', '#0D1F3C']} style={styles.portfolioCard}>
          <View style={styles.portfolioHeader}>
            <Text style={styles.portfolioLabel}>Portofoliu total</Text>
            <View style={styles.planBadge}>
              <Text style={styles.planText}>{user?.plan?.toUpperCase() ?? 'FREE'}</Text>
            </View>
          </View>
          <Text style={styles.portfolioValue}>
            ${summary?.totalValue?.toLocaleString('en-US', { minimumFractionDigits: 2 }) ?? '0.00'}
          </Text>
          <View style={styles.portfolioRow}>
            <View style={[styles.changeBadge, { backgroundColor: pnlColor + '20' }]}>
              <Text style={[styles.changeText, { color: pnlColor }]}>
                {(summary?.dailyPnLPercent ?? 0) >= 0 ? '▲' : '▼'}{' '}
                {Math.abs(summary?.dailyPnLPercent ?? 0).toFixed(2)}% astăzi
              </Text>
            </View>
            <Text style={styles.pnlTotal}>
              {(summary?.totalPnL ?? 0) >= 0 ? '+' : ''}{summary?.totalPnL?.toFixed(2) ?? '0.00'}$
            </Text>
          </View>

          {/* Stats Row */}
          <View style={styles.statsRow}>
            <View style={styles.stat}>
              <Text style={styles.statValue}>{summary?.winRate?.toFixed(0) ?? 0}%</Text>
              <Text style={styles.statLabel}>Win Rate</Text>
            </View>
            <View style={styles.statDivider} />
            <View style={styles.stat}>
              <Text style={styles.statValue}>{summary?.totalTrades ?? 0}</Text>
              <Text style={styles.statLabel}>Tranzacții</Text>
            </View>
            <View style={styles.statDivider} />
            <View style={styles.stat}>
              <Text style={styles.statValue}>{positions.length}</Text>
              <Text style={styles.statLabel}>Poziții active</Text>
            </View>
          </View>
        </LinearGradient>

        {/* AI Signals */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>🤖 Semnale AI active</Text>
            <TouchableOpacity onPress={() => navigation.navigate('Signals')}>
              <Text style={styles.seeAll}>Vezi toate</Text>
            </TouchableOpacity>
          </View>

          {activeSignals.length === 0 ? (
            <View style={styles.emptyCard}>
              <Text style={styles.emptyText}>Se generează semnale...</Text>
            </View>
          ) : (
            activeSignals.map((signal) => (
              <TouchableOpacity
                key={signal.id}
                style={styles.signalCard}
                onPress={() => navigation.navigate('Signals', { signalId: signal.id })}
              >
                <View style={styles.signalLeft}>
                  <View style={[
                    styles.actionBadge,
                    { backgroundColor: signal.action === 'BUY' ? Colors.green + '20' : signal.action === 'SELL' ? Colors.red + '20' : Colors.primary + '20' },
                  ]}>
                    <Text style={[
                      styles.actionText,
                      { color: signal.action === 'BUY' ? Colors.green : signal.action === 'SELL' ? Colors.red : Colors.primary },
                    ]}>
                      {signal.action}
                    </Text>
                  </View>
                  <View>
                    <Text style={styles.signalSymbol}>{signal.symbol}</Text>
                    <Text style={styles.signalMarket}>{signal.market} • {signal.timeframe}</Text>
                  </View>
                </View>
                <View style={styles.signalRight}>
                  <Text style={styles.confidence}>{signal.confidence}%</Text>
                  <Text style={styles.confidenceLabel}>Confidence</Text>
                </View>
              </TouchableOpacity>
            ))
          )}
        </View>

        {/* Top Movers */}
        <View style={styles.section}>
          <View style={styles.sectionHeader}>
            <Text style={styles.sectionTitle}>🔥 Top Mișcări</Text>
            <TouchableOpacity onPress={() => navigation.navigate('Markets')}>
              <Text style={styles.seeAll}>Piețe</Text>
            </TouchableOpacity>
          </View>

          {topMovers.map((asset) => (
            <TouchableOpacity key={asset.symbol} style={styles.assetCard}>
              <View style={styles.assetLeft}>
                <View style={styles.assetIcon}>
                  <Text style={styles.assetIconText}>{asset.symbol.slice(0, 2)}</Text>
                </View>
                <View>
                  <Text style={styles.assetSymbol}>{asset.symbol}</Text>
                  <Text style={styles.assetName}>{asset.name}</Text>
                </View>
              </View>
              <View style={styles.assetRight}>
                <Text style={styles.assetPrice}>
                  ${asset.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}
                </Text>
                <Text style={[
                  styles.assetChange,
                  { color: asset.changePercent24h >= 0 ? Colors.green : Colors.red },
                ]}>
                  {asset.changePercent24h >= 0 ? '▲' : '▼'} {Math.abs(asset.changePercent24h).toFixed(2)}%
                </Text>
              </View>
            </TouchableOpacity>
          ))}
        </View>

        {/* News */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>📰 Știri piețe</Text>
          {news.slice(0, 3).map((item) => (
            <View key={item.id} style={styles.newsCard}>
              <View style={[
                styles.sentimentDot,
                {
                  backgroundColor: item.sentiment === 'positive' ? Colors.green
                    : item.sentiment === 'negative' ? Colors.red : Colors.textMuted,
                },
              ]} />
              <View style={styles.newsContent}>
                <Text style={styles.newsTitle} numberOfLines={2}>{item.title}</Text>
                <Text style={styles.newsSource}>{item.source} • {new Date(item.publishedAt).toLocaleDateString('ro-RO')}</Text>
              </View>
            </View>
          ))}
        </View>
      </Animated.ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingHorizontal: Spacing.lg,
    paddingTop: 60,
    paddingBottom: Spacing.md,
  },
  greeting: { fontSize: FontSize.xl, fontWeight: '700', color: Colors.textPrimary },
  subtitle: { fontSize: FontSize.sm, color: Colors.textSecondary, marginTop: 2 },
  notifBtn: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: Colors.card,
    alignItems: 'center',
    justifyContent: 'center',
  },
  notifIcon: { fontSize: 18 },
  scrollContent: { paddingBottom: 100, gap: Spacing.lg, paddingHorizontal: Spacing.lg },
  portfolioCard: {
    borderRadius: BorderRadius.xl,
    padding: Spacing.lg,
    gap: Spacing.sm,
    borderWidth: 1,
    borderColor: 'rgba(0,102,255,0.2)',
  },
  portfolioHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  portfolioLabel: { fontSize: FontSize.sm, color: Colors.textSecondary },
  planBadge: {
    backgroundColor: Colors.primary + '30',
    paddingHorizontal: Spacing.sm,
    paddingVertical: 3,
    borderRadius: BorderRadius.full,
  },
  planText: { fontSize: FontSize.xs, color: Colors.primary, fontWeight: '700' },
  portfolioValue: { fontSize: FontSize.xxxl, fontWeight: '800', color: Colors.textPrimary, letterSpacing: -1 },
  portfolioRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  changeBadge: { paddingHorizontal: Spacing.sm, paddingVertical: 4, borderRadius: BorderRadius.sm },
  changeText: { fontSize: FontSize.sm, fontWeight: '600' },
  pnlTotal: { fontSize: FontSize.md, color: Colors.textSecondary },
  statsRow: {
    flexDirection: 'row',
    marginTop: Spacing.sm,
    paddingTop: Spacing.md,
    borderTopWidth: 1,
    borderTopColor: 'rgba(255,255,255,0.05)',
  },
  stat: { flex: 1, alignItems: 'center' },
  statValue: { fontSize: FontSize.lg, fontWeight: '700', color: Colors.textPrimary },
  statLabel: { fontSize: FontSize.xs, color: Colors.textMuted, marginTop: 2 },
  statDivider: { width: 1, backgroundColor: 'rgba(255,255,255,0.05)' },
  section: { gap: Spacing.sm },
  sectionHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  sectionTitle: { fontSize: FontSize.lg, fontWeight: '700', color: Colors.textPrimary },
  seeAll: { fontSize: FontSize.sm, color: Colors.primary },
  emptyCard: {
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.md,
    padding: Spacing.lg,
    alignItems: 'center',
  },
  emptyText: { color: Colors.textMuted, fontSize: FontSize.sm },
  signalCard: {
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.md,
    padding: Spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  signalLeft: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  actionBadge: { paddingHorizontal: Spacing.sm, paddingVertical: 4, borderRadius: BorderRadius.sm },
  actionText: { fontSize: FontSize.xs, fontWeight: '800', letterSpacing: 1 },
  signalSymbol: { fontSize: FontSize.md, fontWeight: '700', color: Colors.textPrimary },
  signalMarket: { fontSize: FontSize.xs, color: Colors.textMuted },
  signalRight: { alignItems: 'flex-end' },
  confidence: { fontSize: FontSize.xl, fontWeight: '800', color: Colors.accent },
  confidenceLabel: { fontSize: FontSize.xs, color: Colors.textMuted },
  assetCard: {
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.md,
    padding: Spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  assetLeft: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  assetIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: Colors.primary + '20',
    alignItems: 'center',
    justifyContent: 'center',
  },
  assetIconText: { fontSize: FontSize.sm, fontWeight: '700', color: Colors.primary },
  assetSymbol: { fontSize: FontSize.md, fontWeight: '700', color: Colors.textPrimary },
  assetName: { fontSize: FontSize.xs, color: Colors.textMuted },
  assetRight: { alignItems: 'flex-end' },
  assetPrice: { fontSize: FontSize.md, fontWeight: '600', color: Colors.textPrimary },
  assetChange: { fontSize: FontSize.sm, fontWeight: '600' },
  newsCard: {
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.md,
    padding: Spacing.md,
    flexDirection: 'row',
    gap: Spacing.md,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
    alignItems: 'flex-start',
  },
  sentimentDot: { width: 8, height: 8, borderRadius: 4, marginTop: 5 },
  newsContent: { flex: 1, gap: 4 },
  newsTitle: { fontSize: FontSize.sm, fontWeight: '600', color: Colors.textPrimary, lineHeight: 20 },
  newsSource: { fontSize: FontSize.xs, color: Colors.textMuted },
});

import React, { useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity, RefreshControl,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useDispatch, useSelector } from 'react-redux';
import { AppDispatch, RootState } from '../../store';
import { fetchPortfolio, fetchPnLHistory } from '../../store/slices/portfolioSlice';
import { Colors, FontSize, Spacing, BorderRadius } from '../../theme/colors';

const PERIODS = ['1D', '1W', '1M', '3M', '1Y', 'ALL'];

export default function PortfolioScreen() {
  const dispatch = useDispatch<AppDispatch>();
  const { summary, positions, pnlHistory, loading } = useSelector((s: RootState) => s.portfolio);
  const [period, setPeriod] = useState('1M');

  useEffect(() => {
    dispatch(fetchPortfolio());
    dispatch(fetchPnLHistory('1M'));
  }, []);

  const handlePeriod = (p: string) => {
    setPeriod(p);
    dispatch(fetchPnLHistory(p));
  };

  const pnlPositive = (summary?.totalPnLPercent ?? 0) >= 0;

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Portofoliu</Text>
        <TouchableOpacity style={styles.addBtn}>
          <Text style={styles.addBtnText}>+ Depozit</Text>
        </TouchableOpacity>
      </View>

      <ScrollView
        refreshControl={
          <RefreshControl refreshing={loading} onRefresh={() => dispatch(fetchPortfolio())} tintColor={Colors.primary} />
        }
        showsVerticalScrollIndicator={false}
        contentContainerStyle={styles.content}
      >
        {/* Main Portfolio Value */}
        <LinearGradient colors={['#0A1628', '#0D1F3C']} style={styles.mainCard}>
          <Text style={styles.valueLabel}>Valoare totală portofoliu</Text>
          <Text style={styles.mainValue}>
            ${summary?.totalValue?.toLocaleString('en-US', { minimumFractionDigits: 2 }) ?? '0.00'}
          </Text>
          <View style={styles.pnlRow}>
            <Text style={[styles.pnlValue, { color: pnlPositive ? Colors.green : Colors.red }]}>
              {pnlPositive ? '▲ +' : '▼ '}{summary?.totalPnL?.toFixed(2) ?? '0.00'}$
            </Text>
            <Text style={[styles.pnlPercent, { color: pnlPositive ? Colors.green : Colors.red }]}>
              ({pnlPositive ? '+' : ''}{summary?.totalPnLPercent?.toFixed(2) ?? '0.00'}%)
            </Text>
          </View>
        </LinearGradient>

        {/* Period Selector */}
        <View style={styles.periodRow}>
          {PERIODS.map((p) => (
            <TouchableOpacity
              key={p}
              style={[styles.periodBtn, period === p && styles.periodBtnActive]}
              onPress={() => handlePeriod(p)}
            >
              <Text style={[styles.periodText, period === p && styles.periodTextActive]}>{p}</Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Chart Placeholder */}
        <View style={styles.chartContainer}>
          <LinearGradient
            colors={['rgba(0,102,255,0.1)', 'rgba(0,102,255,0)']}
            style={styles.chartGradient}
          >
            <Text style={styles.chartPlaceholder}>
              📈 Grafic evoluție portofoliu{'\n'}
              <Text style={styles.chartSubPlaceholder}>Integrare chart completă în build</Text>
            </Text>
          </LinearGradient>
        </View>

        {/* Stats */}
        <View style={styles.statsGrid}>
          <View style={styles.statCard}>
            <Text style={[styles.statValue, { color: Colors.green }]}>{summary?.winRate?.toFixed(0) ?? 0}%</Text>
            <Text style={styles.statLabel}>Win Rate</Text>
          </View>
          <View style={styles.statCard}>
            <Text style={styles.statValue}>{summary?.totalTrades ?? 0}</Text>
            <Text style={styles.statLabel}>Total Trades</Text>
          </View>
          <View style={styles.statCard}>
            <Text style={[styles.statValue, { color: summary?.dailyPnLPercent ?? 0 >= 0 ? Colors.green : Colors.red }]}>
              {(summary?.dailyPnLPercent ?? 0) >= 0 ? '+' : ''}{summary?.dailyPnLPercent?.toFixed(2) ?? '0.00'}%
            </Text>
            <Text style={styles.statLabel}>Azi</Text>
          </View>
        </View>

        {/* Open Positions */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>Poziții deschise ({positions.length})</Text>

          {positions.length === 0 ? (
            <View style={styles.emptyPositions}>
              <Text style={styles.emptyIcon}>📭</Text>
              <Text style={styles.emptyText}>Nicio poziție deschisă</Text>
              <Text style={styles.emptySubtext}>Folosește semnalele AI pentru a tranzacționa</Text>
            </View>
          ) : (
            positions.map((pos) => {
              const isProfitable = pos.pnl >= 0;
              return (
                <View key={pos.id} style={styles.positionCard}>
                  <View style={styles.positionLeft}>
                    <View style={[
                      styles.positionSide,
                      { backgroundColor: pos.side === 'long' ? Colors.green + '20' : Colors.red + '20' },
                    ]}>
                      <Text style={[
                        styles.positionSideText,
                        { color: pos.side === 'long' ? Colors.green : Colors.red },
                      ]}>
                        {pos.side.toUpperCase()}
                      </Text>
                    </View>
                    <View>
                      <Text style={styles.positionSymbol}>{pos.symbol}</Text>
                      <Text style={styles.positionMarket}>{pos.market} • {pos.quantity} units</Text>
                    </View>
                  </View>
                  <View style={styles.positionRight}>
                    <Text style={[styles.positionPnl, { color: isProfitable ? Colors.green : Colors.red }]}>
                      {isProfitable ? '+' : ''}{pos.pnl.toFixed(2)}$
                    </Text>
                    <Text style={[styles.positionPnlPct, { color: isProfitable ? Colors.green : Colors.red }]}>
                      {isProfitable ? '+' : ''}{pos.pnlPercent.toFixed(2)}%
                    </Text>
                  </View>
                </View>
              );
            })
          )}
        </View>
      </ScrollView>
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
  title: { fontSize: FontSize.xxl, fontWeight: '800', color: Colors.textPrimary },
  addBtn: {
    backgroundColor: Colors.primary,
    paddingHorizontal: Spacing.md,
    paddingVertical: 8,
    borderRadius: BorderRadius.full,
  },
  addBtnText: { color: Colors.textPrimary, fontWeight: '700', fontSize: FontSize.sm },
  content: { paddingHorizontal: Spacing.lg, paddingBottom: 100, gap: Spacing.lg },
  mainCard: {
    borderRadius: BorderRadius.xl,
    padding: Spacing.xl,
    gap: Spacing.sm,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: 'rgba(0,102,255,0.2)',
  },
  valueLabel: { fontSize: FontSize.sm, color: Colors.textSecondary },
  mainValue: { fontSize: 42, fontWeight: '800', color: Colors.textPrimary, letterSpacing: -1 },
  pnlRow: { flexDirection: 'row', gap: Spacing.sm, alignItems: 'center' },
  pnlValue: { fontSize: FontSize.lg, fontWeight: '700' },
  pnlPercent: { fontSize: FontSize.md, fontWeight: '600' },
  periodRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.full,
    padding: 4,
  },
  periodBtn: { flex: 1, paddingVertical: 8, borderRadius: BorderRadius.full, alignItems: 'center' },
  periodBtnActive: { backgroundColor: Colors.primary },
  periodText: { fontSize: FontSize.xs, color: Colors.textMuted, fontWeight: '600' },
  periodTextActive: { color: Colors.textPrimary },
  chartContainer: {
    height: 180,
    borderRadius: BorderRadius.lg,
    overflow: 'hidden',
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  chartGradient: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  chartPlaceholder: { color: Colors.primary, fontSize: FontSize.md, textAlign: 'center', fontWeight: '600' },
  chartSubPlaceholder: { color: Colors.textMuted, fontSize: FontSize.xs },
  statsGrid: { flexDirection: 'row', gap: Spacing.md },
  statCard: {
    flex: 1,
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.md,
    padding: Spacing.md,
    alignItems: 'center',
    gap: 4,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  statValue: { fontSize: FontSize.xl, fontWeight: '800', color: Colors.textPrimary },
  statLabel: { fontSize: FontSize.xs, color: Colors.textMuted },
  section: { gap: Spacing.md },
  sectionTitle: { fontSize: FontSize.lg, fontWeight: '700', color: Colors.textPrimary },
  emptyPositions: { alignItems: 'center', paddingVertical: Spacing.xxl, gap: Spacing.md },
  emptyIcon: { fontSize: 40 },
  emptyText: { fontSize: FontSize.lg, fontWeight: '600', color: Colors.textPrimary },
  emptySubtext: { fontSize: FontSize.sm, color: Colors.textMuted, textAlign: 'center' },
  positionCard: {
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.md,
    padding: Spacing.md,
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  positionLeft: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  positionSide: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6 },
  positionSideText: { fontSize: FontSize.xs, fontWeight: '800' },
  positionSymbol: { fontSize: FontSize.md, fontWeight: '700', color: Colors.textPrimary },
  positionMarket: { fontSize: FontSize.xs, color: Colors.textMuted },
  positionRight: { alignItems: 'flex-end' },
  positionPnl: { fontSize: FontSize.md, fontWeight: '700' },
  positionPnlPct: { fontSize: FontSize.sm, fontWeight: '600' },
});

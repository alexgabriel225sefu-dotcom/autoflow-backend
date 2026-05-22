import React, { useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity,
  RefreshControl, Modal, ScrollView, ActivityIndicator,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useDispatch, useSelector } from 'react-redux';
import { AppDispatch, RootState } from '../../store';
import { fetchSignals, Signal } from '../../store/slices/signalsSlice';
import { Colors, FontSize, Spacing, BorderRadius } from '../../theme/colors';

const FILTERS = ['all', 'crypto', 'stocks', 'forex'] as const;
const ACTIONS = ['all', 'BUY', 'SELL'] as const;

export default function SignalsScreen() {
  const dispatch = useDispatch<AppDispatch>();
  const { signals, loading } = useSelector((s: RootState) => s.signals);
  const [marketFilter, setMarketFilter] = useState<string>('all');
  const [actionFilter, setActionFilter] = useState<string>('all');
  const [selectedSignal, setSelectedSignal] = useState<Signal | null>(null);

  useEffect(() => { dispatch(fetchSignals()); }, []);

  const filtered = signals.filter((s) => {
    const marketOk = marketFilter === 'all' || s.market === marketFilter;
    const actionOk = actionFilter === 'all' || s.action === actionFilter;
    return marketOk && actionOk;
  });

  const renderSignal = ({ item }: { item: Signal }) => {
    const actionColor = item.action === 'BUY' ? Colors.green : item.action === 'SELL' ? Colors.red : Colors.primary;
    const confidenceColor = item.confidence >= 75 ? Colors.green : item.confidence >= 50 ? Colors.gold : Colors.red;

    return (
      <TouchableOpacity style={styles.signalCard} onPress={() => setSelectedSignal(item)}>
        {/* Top Row */}
        <View style={styles.signalTop}>
          <View style={styles.symbolRow}>
            <View style={[styles.actionBadge, { backgroundColor: actionColor + '20' }]}>
              <Text style={[styles.actionText, { color: actionColor }]}>{item.action}</Text>
            </View>
            <Text style={styles.symbol}>{item.symbol}</Text>
            <Text style={styles.marketTag}>{item.market.toUpperCase()}</Text>
          </View>
          <View style={styles.confidenceCircle}>
            <Text style={[styles.confidenceNum, { color: confidenceColor }]}>{item.confidence}%</Text>
            <Text style={styles.confidenceLabel}>AI</Text>
          </View>
        </View>

        {/* Price Targets */}
        <View style={styles.priceRow}>
          <View style={styles.priceItem}>
            <Text style={styles.priceLabel}>Intrare</Text>
            <Text style={styles.priceValue}>${item.entryPrice.toFixed(4)}</Text>
          </View>
          <Text style={styles.arrow}>→</Text>
          <View style={styles.priceItem}>
            <Text style={styles.priceLabel}>Target</Text>
            <Text style={[styles.priceValue, { color: Colors.green }]}>${item.targetPrice.toFixed(4)}</Text>
          </View>
          <View style={styles.priceItem}>
            <Text style={styles.priceLabel}>Stop Loss</Text>
            <Text style={[styles.priceValue, { color: Colors.red }]}>${item.stopLoss.toFixed(4)}</Text>
          </View>
        </View>

        {/* Footer */}
        <View style={styles.signalFooter}>
          <Text style={styles.timeframe}>⏱ {item.timeframe}</Text>
          <Text style={styles.rrr}>R/R: {item.riskRewardRatio.toFixed(2)}x</Text>
          <View style={[
            styles.sentimentTag,
            { backgroundColor: item.newssentiment === 'positive' ? Colors.green + '20'
              : item.newssentiment === 'negative' ? Colors.red + '20' : Colors.textMuted + '20' },
          ]}>
            <Text style={[
              styles.sentimentText,
              { color: item.newssentiment === 'positive' ? Colors.green
                : item.newssentiment === 'negative' ? Colors.red : Colors.textMuted },
            ]}>
              {item.newssentiment === 'positive' ? '📰 Pozitiv' : item.newssentiment === 'negative' ? '📰 Negativ' : '📰 Neutru'}
            </Text>
          </View>
        </View>
      </TouchableOpacity>
    );
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Semnale AI</Text>
        <View style={styles.liveIndicator}>
          <View style={styles.liveDot} />
          <Text style={styles.liveText}>LIVE</Text>
        </View>
      </View>

      {/* Filters */}
      <ScrollView horizontal showsHorizontalScrollIndicator={false} style={styles.filterScroll}>
        <View style={styles.filters}>
          {FILTERS.map((f) => (
            <TouchableOpacity
              key={f}
              style={[styles.filterBtn, marketFilter === f && styles.filterBtnActive]}
              onPress={() => setMarketFilter(f)}
            >
              <Text style={[styles.filterText, marketFilter === f && styles.filterTextActive]}>
                {f === 'all' ? 'Toate' : f.charAt(0).toUpperCase() + f.slice(1)}
              </Text>
            </TouchableOpacity>
          ))}
          <View style={styles.filterDivider} />
          {ACTIONS.map((a) => (
            <TouchableOpacity
              key={a}
              style={[
                styles.filterBtn,
                actionFilter === a && styles.filterBtnActive,
                a === 'BUY' && actionFilter === a && { backgroundColor: Colors.green },
                a === 'SELL' && actionFilter === a && { backgroundColor: Colors.red },
              ]}
              onPress={() => setActionFilter(a)}
            >
              <Text style={[styles.filterText, actionFilter === a && styles.filterTextActive]}>
                {a === 'all' ? 'Toate' : a}
              </Text>
            </TouchableOpacity>
          ))}
        </View>
      </ScrollView>

      <FlatList
        data={filtered}
        keyExtractor={(item) => item.id}
        renderItem={renderSignal}
        refreshControl={
          <RefreshControl refreshing={loading} onRefresh={() => dispatch(fetchSignals())} tintColor={Colors.primary} />
        }
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ paddingHorizontal: Spacing.lg, paddingBottom: 100, gap: Spacing.md }}
        ListEmptyComponent={
          loading ? (
            <ActivityIndicator color={Colors.primary} style={{ marginTop: 40 }} />
          ) : (
            <View style={styles.emptyState}>
              <Text style={styles.emptyIcon}>🤖</Text>
              <Text style={styles.emptyTitle}>AI analizează piața...</Text>
              <Text style={styles.emptyText}>Semnalele vor apărea în curând</Text>
            </View>
          )
        }
      />

      {/* Signal Detail Modal */}
      <Modal visible={!!selectedSignal} transparent animationType="slide">
        <View style={styles.modalOverlay}>
          <View style={styles.modalContainer}>
            {selectedSignal && (
              <ScrollView showsVerticalScrollIndicator={false}>
                <View style={styles.modalHeader}>
                  <Text style={styles.modalTitle}>{selectedSignal.symbol} Analiză AI</Text>
                  <TouchableOpacity onPress={() => setSelectedSignal(null)}>
                    <Text style={styles.closeBtn}>✕</Text>
                  </TouchableOpacity>
                </View>

                <View style={styles.modalBody}>
                  <Text style={styles.reasoningTitle}>🧠 Raționamentul AI</Text>
                  <Text style={styles.reasoning}>{selectedSignal.reasoning}</Text>

                  <Text style={styles.indicatorsTitle}>📊 Indicatori tehnici</Text>
                  <View style={styles.indicatorsGrid}>
                    {Object.entries(selectedSignal.indicators).map(([key, val]) => (
                      <View key={key} style={styles.indicatorItem}>
                        <Text style={styles.indicatorLabel}>{key.toUpperCase()}</Text>
                        <Text style={styles.indicatorValue}>{typeof val === 'number' ? val.toFixed(4) : val}</Text>
                      </View>
                    ))}
                  </View>

                  <LinearGradient colors={['#0066FF', '#0044CC']} style={styles.executeBtn}>
                    <TouchableOpacity style={styles.executeBtnInner} onPress={() => setSelectedSignal(null)}>
                      <Text style={styles.executeBtnText}>
                        {selectedSignal.action === 'BUY' ? '🚀 Execută BUY' : '📉 Execută SELL'}
                      </Text>
                    </TouchableOpacity>
                  </LinearGradient>
                </View>
              </ScrollView>
            )}
          </View>
        </View>
      </Modal>
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
  liveIndicator: { flexDirection: 'row', alignItems: 'center', gap: 6 },
  liveDot: { width: 8, height: 8, borderRadius: 4, backgroundColor: Colors.green },
  liveText: { fontSize: FontSize.xs, color: Colors.green, fontWeight: '700', letterSpacing: 1 },
  filterScroll: { maxHeight: 48, marginBottom: Spacing.sm },
  filters: { flexDirection: 'row', paddingHorizontal: Spacing.lg, gap: Spacing.sm, alignItems: 'center' },
  filterBtn: {
    paddingHorizontal: Spacing.md,
    paddingVertical: 7,
    borderRadius: BorderRadius.full,
    backgroundColor: Colors.card,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  filterBtnActive: { backgroundColor: Colors.primary, borderColor: Colors.primary },
  filterText: { fontSize: FontSize.sm, color: Colors.textSecondary, fontWeight: '600' },
  filterTextActive: { color: Colors.textPrimary },
  filterDivider: { width: 1, height: 20, backgroundColor: Colors.cardBorder },
  signalCard: {
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.lg,
    padding: Spacing.md,
    gap: Spacing.md,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  signalTop: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  symbolRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm },
  actionBadge: { paddingHorizontal: Spacing.sm, paddingVertical: 4, borderRadius: 6 },
  actionText: { fontSize: FontSize.xs, fontWeight: '800', letterSpacing: 1 },
  symbol: { fontSize: FontSize.lg, fontWeight: '800', color: Colors.textPrimary },
  marketTag: {
    fontSize: FontSize.xs,
    color: Colors.textMuted,
    backgroundColor: Colors.surface,
    paddingHorizontal: 6,
    paddingVertical: 2,
    borderRadius: 4,
  },
  confidenceCircle: { alignItems: 'center' },
  confidenceNum: { fontSize: FontSize.xl, fontWeight: '800' },
  confidenceLabel: { fontSize: FontSize.xs, color: Colors.textMuted },
  priceRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: Spacing.sm,
    borderTopWidth: 1,
    borderBottomWidth: 1,
    borderColor: Colors.cardBorder,
  },
  priceItem: { alignItems: 'center' },
  priceLabel: { fontSize: FontSize.xs, color: Colors.textMuted },
  priceValue: { fontSize: FontSize.sm, fontWeight: '700', color: Colors.textPrimary },
  arrow: { color: Colors.textMuted, fontSize: FontSize.lg },
  signalFooter: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md },
  timeframe: { fontSize: FontSize.xs, color: Colors.textMuted },
  rrr: { fontSize: FontSize.xs, color: Colors.accent, fontWeight: '700' },
  sentimentTag: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: 8 },
  sentimentText: { fontSize: FontSize.xs, fontWeight: '600' },
  emptyState: { alignItems: 'center', paddingTop: 80, gap: Spacing.md },
  emptyIcon: { fontSize: 48 },
  emptyTitle: { fontSize: FontSize.lg, fontWeight: '700', color: Colors.textPrimary },
  emptyText: { fontSize: FontSize.sm, color: Colors.textMuted },
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.8)', justifyContent: 'flex-end' },
  modalContainer: {
    backgroundColor: Colors.surface,
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    maxHeight: '85%',
  },
  modalHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: Spacing.lg,
    borderBottomWidth: 1,
    borderBottomColor: Colors.cardBorder,
  },
  modalTitle: { fontSize: FontSize.lg, fontWeight: '700', color: Colors.textPrimary },
  closeBtn: { fontSize: 20, color: Colors.textMuted, padding: 4 },
  modalBody: { padding: Spacing.lg, gap: Spacing.lg },
  reasoningTitle: { fontSize: FontSize.md, fontWeight: '700', color: Colors.textPrimary },
  reasoning: { fontSize: FontSize.sm, color: Colors.textSecondary, lineHeight: 22 },
  indicatorsTitle: { fontSize: FontSize.md, fontWeight: '700', color: Colors.textPrimary },
  indicatorsGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: Spacing.sm },
  indicatorItem: {
    backgroundColor: Colors.card,
    borderRadius: BorderRadius.sm,
    padding: Spacing.sm,
    minWidth: '30%',
    alignItems: 'center',
  },
  indicatorLabel: { fontSize: FontSize.xs, color: Colors.textMuted },
  indicatorValue: { fontSize: FontSize.sm, fontWeight: '700', color: Colors.textPrimary },
  executeBtn: { borderRadius: BorderRadius.full, overflow: 'hidden', marginTop: Spacing.md },
  executeBtnInner: { paddingVertical: Spacing.md, alignItems: 'center' },
  executeBtnText: { fontSize: FontSize.lg, fontWeight: '700', color: Colors.textPrimary },
});

import React, { useEffect, useState } from 'react';
import {
  View, Text, StyleSheet, FlatList, TouchableOpacity,
  TextInput, RefreshControl,
} from 'react-native';
import { useDispatch, useSelector } from 'react-redux';
import { AppDispatch, RootState } from '../../store';
import { fetchCrypto, fetchStocks, fetchForex, setActiveMarket } from '../../store/slices/marketsSlice';
import { Colors, FontSize, Spacing, BorderRadius } from '../../theme/colors';
import { Asset } from '../../store/slices/marketsSlice';

const MARKETS = ['crypto', 'stocks', 'forex'] as const;
const MARKET_LABELS: Record<string, string> = {
  crypto: '₿ Crypto',
  stocks: '📈 Acțiuni',
  forex: '💱 Forex',
};

export default function MarketsScreen({ navigation }: any) {
  const dispatch = useDispatch<AppDispatch>();
  const { crypto, stocks, forex, loading, activeMarket } = useSelector((s: RootState) => s.markets);
  const [search, setSearch] = useState('');
  const [sortBy, setSortBy] = useState<'price' | 'change' | 'volume'>('change');

  const fetchForMarket = (market: string) => {
    if (market === 'crypto') dispatch(fetchCrypto());
    else if (market === 'stocks') dispatch(fetchStocks());
    else dispatch(fetchForex());
  };

  useEffect(() => { fetchForMarket(activeMarket); }, [activeMarket]);

  const raw = activeMarket === 'crypto' ? crypto : activeMarket === 'stocks' ? stocks : forex;
  const filtered = raw
    .filter((a) =>
      a.symbol.toLowerCase().includes(search.toLowerCase()) ||
      a.name.toLowerCase().includes(search.toLowerCase())
    )
    .sort((a, b) => {
      if (sortBy === 'change') return b.changePercent24h - a.changePercent24h;
      if (sortBy === 'volume') return b.volume24h - a.volume24h;
      return b.price - a.price;
    });

  const renderAsset = ({ item }: { item: Asset }) => (
    <TouchableOpacity
      style={styles.assetRow}
      onPress={() => navigation.navigate('AssetDetail', { asset: item })}
    >
      <View style={styles.assetIcon}>
        <Text style={styles.assetIconText}>{item.symbol.slice(0, 2)}</Text>
      </View>
      <View style={styles.assetInfo}>
        <Text style={styles.assetSymbol}>{item.symbol}</Text>
        <Text style={styles.assetName}>{item.name}</Text>
      </View>
      <View style={styles.sparklinePlaceholder} />
      <View style={styles.assetPrices}>
        <Text style={styles.assetPrice}>
          ${item.price < 0.01
            ? item.price.toFixed(8)
            : item.price < 1
            ? item.price.toFixed(4)
            : item.price.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}
        </Text>
        <View style={[
          styles.changeBadge,
          { backgroundColor: item.changePercent24h >= 0 ? Colors.green + '20' : Colors.red + '20' },
        ]}>
          <Text style={[
            styles.changeText,
            { color: item.changePercent24h >= 0 ? Colors.green : Colors.red },
          ]}>
            {item.changePercent24h >= 0 ? '+' : ''}{item.changePercent24h.toFixed(2)}%
          </Text>
        </View>
      </View>
    </TouchableOpacity>
  );

  return (
    <View style={styles.container}>
      {/* Header */}
      <View style={styles.header}>
        <Text style={styles.title}>Piețe</Text>
      </View>

      {/* Market Tabs */}
      <View style={styles.tabs}>
        {MARKETS.map((m) => (
          <TouchableOpacity
            key={m}
            style={[styles.tab, activeMarket === m && styles.tabActive]}
            onPress={() => dispatch(setActiveMarket(m))}
          >
            <Text style={[styles.tabText, activeMarket === m && styles.tabTextActive]}>
              {MARKET_LABELS[m]}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Search */}
      <View style={styles.searchContainer}>
        <Text style={styles.searchIcon}>🔍</Text>
        <TextInput
          style={styles.searchInput}
          placeholder="Caută simbol sau nume..."
          placeholderTextColor={Colors.textMuted}
          value={search}
          onChangeText={setSearch}
        />
        {search.length > 0 && (
          <TouchableOpacity onPress={() => setSearch('')}>
            <Text style={styles.clearSearch}>✕</Text>
          </TouchableOpacity>
        )}
      </View>

      {/* Sort Buttons */}
      <View style={styles.sortRow}>
        <Text style={styles.sortLabel}>Sortare:</Text>
        {(['change', 'volume', 'price'] as const).map((s) => (
          <TouchableOpacity
            key={s}
            style={[styles.sortBtn, sortBy === s && styles.sortBtnActive]}
            onPress={() => setSortBy(s)}
          >
            <Text style={[styles.sortBtnText, sortBy === s && styles.sortBtnTextActive]}>
              {s === 'change' ? 'Schimb' : s === 'volume' ? 'Volum' : 'Preț'}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Column Headers */}
      <View style={styles.columnHeaders}>
        <Text style={[styles.colHeader, { flex: 2 }]}>Activ</Text>
        <Text style={styles.colHeader}>Chart</Text>
        <Text style={[styles.colHeader, { textAlign: 'right', flex: 1.5 }]}>Preț / Schimb</Text>
      </View>

      {/* List */}
      <FlatList
        data={filtered}
        keyExtractor={(item) => item.symbol}
        renderItem={renderAsset}
        refreshControl={
          <RefreshControl
            refreshing={loading}
            onRefresh={() => fetchForMarket(activeMarket)}
            tintColor={Colors.primary}
          />
        }
        showsVerticalScrollIndicator={false}
        contentContainerStyle={{ paddingBottom: 100 }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  header: {
    paddingHorizontal: Spacing.lg,
    paddingTop: 60,
    paddingBottom: Spacing.md,
  },
  title: { fontSize: FontSize.xxl, fontWeight: '800', color: Colors.textPrimary },
  tabs: {
    flexDirection: 'row',
    paddingHorizontal: Spacing.lg,
    gap: Spacing.sm,
    marginBottom: Spacing.md,
  },
  tab: {
    flex: 1,
    paddingVertical: Spacing.sm,
    borderRadius: BorderRadius.full,
    alignItems: 'center',
    backgroundColor: Colors.card,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  tabActive: {
    backgroundColor: Colors.primary,
    borderColor: Colors.primary,
  },
  tabText: { fontSize: FontSize.sm, color: Colors.textSecondary, fontWeight: '600' },
  tabTextActive: { color: Colors.textPrimary },
  searchContainer: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: Colors.card,
    marginHorizontal: Spacing.lg,
    borderRadius: BorderRadius.md,
    paddingHorizontal: Spacing.md,
    marginBottom: Spacing.sm,
    borderWidth: 1,
    borderColor: Colors.cardBorder,
  },
  searchIcon: { fontSize: 16, marginRight: Spacing.sm },
  searchInput: {
    flex: 1,
    paddingVertical: Spacing.sm + 2,
    fontSize: FontSize.md,
    color: Colors.textPrimary,
  },
  clearSearch: { color: Colors.textMuted, fontSize: 16, padding: 4 },
  sortRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: Spacing.lg,
    gap: Spacing.xs,
    marginBottom: Spacing.sm,
  },
  sortLabel: { fontSize: FontSize.xs, color: Colors.textMuted, marginRight: Spacing.xs },
  sortBtn: {
    paddingHorizontal: Spacing.md,
    paddingVertical: 5,
    borderRadius: BorderRadius.full,
    backgroundColor: Colors.card,
  },
  sortBtnActive: { backgroundColor: Colors.primary },
  sortBtnText: { fontSize: FontSize.xs, color: Colors.textMuted, fontWeight: '600' },
  sortBtnTextActive: { color: Colors.textPrimary },
  columnHeaders: {
    flexDirection: 'row',
    paddingHorizontal: Spacing.lg,
    paddingBottom: Spacing.xs,
    alignItems: 'center',
  },
  colHeader: { fontSize: FontSize.xs, color: Colors.textMuted, flex: 1 },
  assetRow: {
    flexDirection: 'row',
    alignItems: 'center',
    paddingHorizontal: Spacing.lg,
    paddingVertical: Spacing.md,
    borderBottomWidth: 1,
    borderBottomColor: Colors.cardBorder,
  },
  assetIcon: {
    width: 40,
    height: 40,
    borderRadius: 20,
    backgroundColor: Colors.primary + '20',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: Spacing.md,
  },
  assetIconText: { fontSize: FontSize.sm, fontWeight: '700', color: Colors.primary },
  assetInfo: { flex: 2 },
  assetSymbol: { fontSize: FontSize.md, fontWeight: '700', color: Colors.textPrimary },
  assetName: { fontSize: FontSize.xs, color: Colors.textMuted },
  sparklinePlaceholder: {
    width: 60,
    height: 30,
    backgroundColor: Colors.card,
    borderRadius: 4,
    marginRight: Spacing.sm,
  },
  assetPrices: { flex: 1.5, alignItems: 'flex-end', gap: 4 },
  assetPrice: { fontSize: FontSize.sm, fontWeight: '600', color: Colors.textPrimary },
  changeBadge: { paddingHorizontal: 6, paddingVertical: 3, borderRadius: 6 },
  changeText: { fontSize: FontSize.xs, fontWeight: '700' },
});

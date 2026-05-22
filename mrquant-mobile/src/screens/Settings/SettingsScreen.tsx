import React, { useState } from 'react';
import {
  View, Text, StyleSheet, ScrollView, TouchableOpacity,
  Switch, Alert, TextInput, Modal, ActivityIndicator,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useDispatch, useSelector } from 'react-redux';
import { AppDispatch, RootState } from '../../store';
import { logoutThunk } from '../../store/slices/authSlice';
import { brokerAPI } from '../../services/api';
import { Colors, FontSize, Spacing, BorderRadius } from '../../theme/colors';

const BROKERS = [
  { id: 'binance', name: 'Binance', logo: '₿', markets: 'Crypto', description: 'Cel mai mare exchange crypto' },
  { id: 'alpaca', name: 'Alpaca', logo: '🦙', markets: 'Stocks', description: 'Trading acțiuni US gratuit' },
  { id: 'oanda', name: 'OANDA', logo: '💱', markets: 'Forex', description: 'Forex & CFDs' },
  { id: 'interactive_brokers', name: 'IBKR', logo: '🏦', markets: 'All', description: 'Broker global universal' },
];

export default function SettingsScreen() {
  const dispatch = useDispatch<AppDispatch>();
  const { user } = useSelector((s: RootState) => s.auth);
  const [notifications, setNotifications] = useState(true);
  const [autoTrading, setAutoTrading] = useState(false);
  const [riskLevel, setRiskLevel] = useState<'low' | 'medium' | 'high'>('medium');
  const [brokerModal, setBrokerModal] = useState(false);
  const [selectedBroker, setSelectedBroker] = useState<typeof BROKERS[0] | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [apiSecret, setApiSecret] = useState('');
  const [sandbox, setSandbox] = useState(true);
  const [connecting, setConnecting] = useState(false);

  const handleLogout = () => {
    Alert.alert('Deconectare', 'Ești sigur că vrei să te deconectezi?', [
      { text: 'Anulează', style: 'cancel' },
      { text: 'Deconectează', style: 'destructive', onPress: () => dispatch(logoutThunk()) },
    ]);
  };

  const handleConnectBroker = async () => {
    if (!selectedBroker || !apiKey.trim() || !apiSecret.trim()) {
      Alert.alert('Eroare', 'Completează toate câmpurile');
      return;
    }
    setConnecting(true);
    try {
      await brokerAPI.connect(selectedBroker.id, apiKey, apiSecret, sandbox);
      Alert.alert('Succes', `${selectedBroker.name} conectat cu succes!`);
      setBrokerModal(false);
      setApiKey('');
      setApiSecret('');
    } catch (err: any) {
      Alert.alert('Eroare', err.response?.data?.message || 'Conectarea a eșuat');
    } finally {
      setConnecting(false);
    }
  };

  return (
    <View style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Setări</Text>
      </View>

      <ScrollView contentContainerStyle={styles.content} showsVerticalScrollIndicator={false}>
        {/* Profile */}
        <View style={styles.profileCard}>
          <LinearGradient colors={['#0066FF', '#0044CC']} style={styles.avatar}>
            <Text style={styles.avatarText}>{user?.name?.charAt(0)?.toUpperCase() ?? 'U'}</Text>
          </LinearGradient>
          <View style={styles.profileInfo}>
            <Text style={styles.profileName}>{user?.name ?? 'Utilizator'}</Text>
            <Text style={styles.profileEmail}>{user?.email ?? ''}</Text>
            <View style={styles.planRow}>
              <View style={[styles.planBadge, { backgroundColor: user?.plan === 'pro' ? Colors.gold + '20' : Colors.primary + '20' }]}>
                <Text style={[styles.planText, { color: user?.plan === 'pro' ? Colors.gold : Colors.primary }]}>
                  {user?.plan?.toUpperCase() ?? 'FREE'} PLAN
                </Text>
              </View>
              {user?.plan !== 'pro' && (
                <TouchableOpacity style={styles.upgradeBtn}>
                  <Text style={styles.upgradeBtnText}>Upgrade la Pro</Text>
                </TouchableOpacity>
              )}
            </View>
          </View>
        </View>

        {/* Brokers */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>🔗 Broker / Exchange</Text>
          <Text style={styles.sectionSubtitle}>Conectează-te la broker pentru auto-trading</Text>
          {BROKERS.map((broker) => (
            <TouchableOpacity
              key={broker.id}
              style={styles.brokerCard}
              onPress={() => { setSelectedBroker(broker); setBrokerModal(true); }}
            >
              <View style={styles.brokerIcon}>
                <Text style={styles.brokerIconText}>{broker.logo}</Text>
              </View>
              <View style={styles.brokerInfo}>
                <Text style={styles.brokerName}>{broker.name}</Text>
                <Text style={styles.brokerDesc}>{broker.markets} • {broker.description}</Text>
              </View>
              <Text style={styles.arrow}>›</Text>
            </TouchableOpacity>
          ))}
        </View>

        {/* Trading */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>⚙️ Trading</Text>
          <View style={styles.settingsCard}>
            <View style={styles.settingRow}>
              <View style={styles.settingLeft}>
                <Text style={styles.settingIcon}>🤖</Text>
                <View>
                  <Text style={styles.settingTitle}>Auto-Trading</Text>
                  <Text style={styles.settingSubtitle}>AI execută ordinele automat</Text>
                </View>
              </View>
              <Switch value={autoTrading} onValueChange={setAutoTrading} trackColor={{ true: Colors.primary }} thumbColor="#fff" />
            </View>
            <View style={styles.divider} />
            <View style={styles.settingRow}>
              <View style={styles.settingLeft}>
                <Text style={styles.settingIcon}>⚡</Text>
                <View>
                  <Text style={styles.settingTitle}>Nivel risc</Text>
                  <Text style={styles.settingSubtitle}>Actual: {riskLevel === 'low' ? 'Mic' : riskLevel === 'medium' ? 'Mediu' : 'Mare'}</Text>
                </View>
              </View>
              <View style={styles.riskButtons}>
                {(['low', 'medium', 'high'] as const).map((r) => (
                  <TouchableOpacity
                    key={r}
                    style={[styles.riskBtn, riskLevel === r && {
                      backgroundColor: r === 'low' ? Colors.green : r === 'medium' ? Colors.gold : Colors.red,
                    }]}
                    onPress={() => setRiskLevel(r)}
                  >
                    <Text style={styles.riskBtnText}>{r === 'low' ? 'Mic' : r === 'medium' ? 'Med' : 'Mare'}</Text>
                  </TouchableOpacity>
                ))}
              </View>
            </View>
          </View>
        </View>

        {/* Notifications */}
        <View style={styles.section}>
          <Text style={styles.sectionTitle}>🔔 Notificări</Text>
          <View style={styles.settingsCard}>
            <View style={styles.settingRow}>
              <View style={styles.settingLeft}>
                <Text style={styles.settingIcon}>📊</Text>
                <View>
                  <Text style={styles.settingTitle}>Semnale AI</Text>
                  <Text style={styles.settingSubtitle}>Primești notificări pentru semnale noi</Text>
                </View>
              </View>
              <Switch value={notifications} onValueChange={setNotifications} trackColor={{ true: Colors.primary }} thumbColor="#fff" />
            </View>
          </View>
        </View>

        {/* Logout */}
        <TouchableOpacity style={styles.logoutBtn} onPress={handleLogout}>
          <Text style={styles.logoutText}>Deconectare</Text>
        </TouchableOpacity>
        <Text style={styles.version}>Apex Trade v1.0.0</Text>
      </ScrollView>

      {/* Broker Modal */}
      <Modal visible={brokerModal} transparent animationType="slide">
        <View style={styles.modalOverlay}>
          <View style={styles.modalContainer}>
            <View style={styles.modalHeader}>
              <Text style={styles.modalTitle}>Conectare {selectedBroker?.name}</Text>
              <TouchableOpacity onPress={() => { setBrokerModal(false); setApiKey(''); setApiSecret(''); }}>
                <Text style={styles.closeBtn}>✕</Text>
              </TouchableOpacity>
            </View>
            <View style={styles.modalBody}>
              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>API Key</Text>
                <TextInput style={styles.input} value={apiKey} onChangeText={setApiKey} placeholder="Introdu API Key..." placeholderTextColor={Colors.textMuted} autoCapitalize="none" />
              </View>
              <View style={styles.inputGroup}>
                <Text style={styles.inputLabel}>API Secret</Text>
                <TextInput style={styles.input} value={apiSecret} onChangeText={setApiSecret} placeholder="Introdu API Secret..." placeholderTextColor={Colors.textMuted} secureTextEntry autoCapitalize="none" />
              </View>
              <View style={styles.sandboxRow}>
                <View>
                  <Text style={styles.sandboxTitle}>Mod Testare (Sandbox)</Text>
                  <Text style={styles.sandboxSubtitle}>Recomandat la început</Text>
                </View>
                <Switch value={sandbox} onValueChange={setSandbox} trackColor={{ true: Colors.primary }} thumbColor="#fff" />
              </View>
              <TouchableOpacity onPress={handleConnectBroker} disabled={connecting} activeOpacity={0.85}>
                <LinearGradient colors={['#0066FF', '#0044CC']} style={styles.connectBtn}>
                  {connecting ? <ActivityIndicator color="#fff" /> : <Text style={styles.connectBtnText}>Conectează</Text>}
                </LinearGradient>
              </TouchableOpacity>
              <Text style={styles.securityNote}>🔒 Cheile sunt stocate criptat și nu sunt transmise terților.</Text>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: Colors.background },
  header: { paddingHorizontal: Spacing.lg, paddingTop: 60, paddingBottom: Spacing.md },
  title: { fontSize: FontSize.xxl, fontWeight: '800', color: Colors.textPrimary },
  content: { paddingHorizontal: Spacing.lg, paddingBottom: 100, gap: Spacing.lg },
  profileCard: { backgroundColor: Colors.card, borderRadius: BorderRadius.xl, padding: Spacing.lg, flexDirection: 'row', alignItems: 'center', gap: Spacing.md, borderWidth: 1, borderColor: Colors.cardBorder },
  avatar: { width: 60, height: 60, borderRadius: 30, alignItems: 'center', justifyContent: 'center' },
  avatarText: { fontSize: FontSize.xxl, fontWeight: '800', color: Colors.textPrimary },
  profileInfo: { flex: 1, gap: 4 },
  profileName: { fontSize: FontSize.lg, fontWeight: '700', color: Colors.textPrimary },
  profileEmail: { fontSize: FontSize.sm, color: Colors.textSecondary },
  planRow: { flexDirection: 'row', alignItems: 'center', gap: Spacing.sm, marginTop: 4 },
  planBadge: { paddingHorizontal: 8, paddingVertical: 3, borderRadius: BorderRadius.full },
  planText: { fontSize: FontSize.xs, fontWeight: '800' },
  upgradeBtn: { backgroundColor: Colors.gold + '20', paddingHorizontal: 10, paddingVertical: 3, borderRadius: BorderRadius.full },
  upgradeBtnText: { color: Colors.gold, fontSize: FontSize.xs, fontWeight: '700' },
  section: { gap: Spacing.sm },
  sectionTitle: { fontSize: FontSize.lg, fontWeight: '700', color: Colors.textPrimary },
  sectionSubtitle: { fontSize: FontSize.sm, color: Colors.textMuted },
  brokerCard: { backgroundColor: Colors.card, borderRadius: BorderRadius.md, padding: Spacing.md, flexDirection: 'row', alignItems: 'center', gap: Spacing.md, borderWidth: 1, borderColor: Colors.cardBorder },
  brokerIcon: { width: 44, height: 44, borderRadius: 22, backgroundColor: Colors.primary + '20', alignItems: 'center', justifyContent: 'center' },
  brokerIconText: { fontSize: 20 },
  brokerInfo: { flex: 1 },
  brokerName: { fontSize: FontSize.md, fontWeight: '700', color: Colors.textPrimary },
  brokerDesc: { fontSize: FontSize.xs, color: Colors.textMuted },
  arrow: { fontSize: 24, color: Colors.textMuted },
  settingsCard: { backgroundColor: Colors.card, borderRadius: BorderRadius.md, borderWidth: 1, borderColor: Colors.cardBorder },
  settingRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: Spacing.md },
  settingLeft: { flexDirection: 'row', alignItems: 'center', gap: Spacing.md, flex: 1 },
  settingIcon: { fontSize: 20 },
  settingTitle: { fontSize: FontSize.md, color: Colors.textPrimary, fontWeight: '500' },
  settingSubtitle: { fontSize: FontSize.xs, color: Colors.textMuted, marginTop: 2 },
  divider: { height: 1, backgroundColor: Colors.cardBorder, marginHorizontal: Spacing.md },
  riskButtons: { flexDirection: 'row', gap: 4 },
  riskBtn: { paddingHorizontal: 8, paddingVertical: 4, borderRadius: 6, backgroundColor: Colors.surface },
  riskBtnText: { fontSize: FontSize.xs, color: Colors.textPrimary, fontWeight: '600' },
  logoutBtn: { backgroundColor: Colors.red + '15', borderRadius: BorderRadius.md, padding: Spacing.md, alignItems: 'center', borderWidth: 1, borderColor: Colors.red + '40' },
  logoutText: { color: Colors.red, fontWeight: '700', fontSize: FontSize.md },
  version: { textAlign: 'center', color: Colors.textMuted, fontSize: FontSize.xs },
  modalOverlay: { flex: 1, backgroundColor: 'rgba(0,0,0,0.8)', justifyContent: 'flex-end' },
  modalContainer: { backgroundColor: Colors.surface, borderTopLeftRadius: 24, borderTopRightRadius: 24 },
  modalHeader: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', padding: Spacing.lg, borderBottomWidth: 1, borderBottomColor: Colors.cardBorder },
  modalTitle: { fontSize: FontSize.lg, fontWeight: '700', color: Colors.textPrimary },
  closeBtn: { fontSize: 20, color: Colors.textMuted, padding: 4 },
  modalBody: { padding: Spacing.lg, gap: Spacing.md },
  inputGroup: { gap: Spacing.xs },
  inputLabel: { fontSize: FontSize.xs, color: Colors.textSecondary, fontWeight: '500' },
  input: { backgroundColor: Colors.card, borderRadius: BorderRadius.md, paddingHorizontal: Spacing.md, paddingVertical: Spacing.md, fontSize: FontSize.md, color: Colors.textPrimary, borderWidth: 1, borderColor: Colors.cardBorder },
  sandboxRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', backgroundColor: Colors.card, borderRadius: BorderRadius.md, padding: Spacing.md },
  sandboxTitle: { fontSize: FontSize.md, color: Colors.textPrimary, fontWeight: '500' },
  sandboxSubtitle: { fontSize: FontSize.xs, color: Colors.green },
  connectBtn: { paddingVertical: Spacing.md, borderRadius: BorderRadius.full, alignItems: 'center' },
  connectBtnText: { fontSize: FontSize.lg, fontWeight: '700', color: Colors.textPrimary },
  securityNote: { fontSize: FontSize.xs, color: Colors.textMuted, textAlign: 'center' },
});

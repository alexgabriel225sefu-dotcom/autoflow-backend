import React, { useState } from 'react';
import {
  View, Text, StyleSheet, TextInput, TouchableOpacity,
  KeyboardAvoidingView, Platform, ActivityIndicator, Alert, ScrollView,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { useDispatch, useSelector } from 'react-redux';
import { AppDispatch, RootState } from '../../store';
import { registerThunk } from '../../store/slices/authSlice';
import { Colors, FontSize, Spacing, BorderRadius } from '../../theme/colors';

interface Props {
  onNavigateLogin: () => void;
  onSuccess: () => void;
}

export default function RegisterScreen({ onNavigateLogin, onSuccess }: Props) {
  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const dispatch = useDispatch<AppDispatch>();
  const { loading, error } = useSelector((s: RootState) => s.auth);

  const handleRegister = async () => {
    if (!name.trim() || !email.trim() || !password) {
      Alert.alert('Eroare', 'Completează toate câmpurile');
      return;
    }
    if (password !== confirmPassword) {
      Alert.alert('Eroare', 'Parolele nu coincid');
      return;
    }
    if (password.length < 8) {
      Alert.alert('Eroare', 'Parola trebuie să aibă minim 8 caractere');
      return;
    }
    const result = await dispatch(registerThunk({ email: email.trim(), password, name: name.trim() }));
    if (registerThunk.fulfilled.match(result)) onSuccess();
  };

  return (
    <KeyboardAvoidingView
      style={{ flex: 1, backgroundColor: Colors.background }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
    >
      <ScrollView
        contentContainerStyle={styles.container}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.header}>
          <View style={styles.logoMini}>
            <Text style={styles.logoMiniText}>AT</Text>
          </View>
          <Text style={styles.title}>Creează cont</Text>
          <Text style={styles.subtitle}>14 zile gratuit • Fără card</Text>
        </View>

        <View style={styles.form}>
          {error && (
            <View style={styles.errorBox}>
              <Text style={styles.errorText}>{error}</Text>
            </View>
          )}

          <View style={styles.inputGroup}>
            <Text style={styles.label}>Nume complet</Text>
            <TextInput
              style={styles.input}
              placeholder="Ion Popescu"
              placeholderTextColor={Colors.textMuted}
              value={name}
              onChangeText={setName}
            />
          </View>

          <View style={styles.inputGroup}>
            <Text style={styles.label}>Email</Text>
            <TextInput
              style={styles.input}
              placeholder="email@exemplu.com"
              placeholderTextColor={Colors.textMuted}
              value={email}
              onChangeText={setEmail}
              keyboardType="email-address"
              autoCapitalize="none"
            />
          </View>

          <View style={styles.inputGroup}>
            <Text style={styles.label}>Parolă</Text>
            <TextInput
              style={styles.input}
              placeholder="Minim 8 caractere"
              placeholderTextColor={Colors.textMuted}
              value={password}
              onChangeText={setPassword}
              secureTextEntry
              autoCapitalize="none"
            />
          </View>

          <View style={styles.inputGroup}>
            <Text style={styles.label}>Confirmă parola</Text>
            <TextInput
              style={styles.input}
              placeholder="Repetă parola"
              placeholderTextColor={Colors.textMuted}
              value={confirmPassword}
              onChangeText={setConfirmPassword}
              secureTextEntry
              autoCapitalize="none"
            />
          </View>

          <TouchableOpacity onPress={handleRegister} disabled={loading} activeOpacity={0.85}>
            <LinearGradient
              colors={['#0066FF', '#0044CC']}
              style={styles.registerButton}
              start={{ x: 0, y: 0 }}
              end={{ x: 1, y: 0 }}
            >
              {loading ? (
                <ActivityIndicator color="#fff" />
              ) : (
                <Text style={styles.registerButtonText}>Creează cont gratuit</Text>
              )}
            </LinearGradient>
          </TouchableOpacity>

          <Text style={styles.terms}>
            Prin înregistrare, ești de acord cu{' '}
            <Text style={styles.termsLink}>Termenii și Condițiile</Text>{' '}
            și{' '}
            <Text style={styles.termsLink}>Politica de Confidențialitate</Text>.
          </Text>

          <TouchableOpacity style={styles.loginBtn} onPress={onNavigateLogin}>
            <Text style={styles.loginText}>
              Ai deja cont?{' '}
              <Text style={styles.loginLink}>Autentifică-te</Text>
            </Text>
          </TouchableOpacity>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flexGrow: 1,
    paddingHorizontal: Spacing.xl,
    paddingVertical: Spacing.xxl,
    justifyContent: 'center',
  },
  header: { alignItems: 'center', marginBottom: Spacing.xl },
  logoMini: {
    width: 64,
    height: 64,
    borderRadius: 18,
    backgroundColor: Colors.primary,
    alignItems: 'center',
    justifyContent: 'center',
    marginBottom: Spacing.lg,
  },
  logoMiniText: { fontSize: 24, fontWeight: '800', color: Colors.textPrimary },
  title: { fontSize: FontSize.xxl, fontWeight: '700', color: Colors.textPrimary, marginBottom: Spacing.xs },
  subtitle: { fontSize: FontSize.md, color: Colors.green, fontWeight: '600' },
  form: { gap: Spacing.md },
  errorBox: {
    backgroundColor: 'rgba(255,61,61,0.15)',
    borderRadius: BorderRadius.md,
    padding: Spacing.md,
    borderWidth: 1,
    borderColor: Colors.red,
  },
  errorText: { color: Colors.red, fontSize: FontSize.sm, textAlign: 'center' },
  inputGroup: { gap: Spacing.xs },
  label: { fontSize: FontSize.sm, color: Colors.textSecondary, fontWeight: '500' },
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
  registerButton: {
    paddingVertical: Spacing.md + 2,
    borderRadius: BorderRadius.full,
    alignItems: 'center',
    marginTop: Spacing.xs,
  },
  registerButtonText: { fontSize: FontSize.lg, color: Colors.textPrimary, fontWeight: '700' },
  terms: { fontSize: FontSize.xs, color: Colors.textMuted, textAlign: 'center', lineHeight: 18 },
  termsLink: { color: Colors.primary },
  loginBtn: { alignItems: 'center' },
  loginText: { color: Colors.textSecondary, fontSize: FontSize.sm },
  loginLink: { color: Colors.primary, fontWeight: '700' },
});

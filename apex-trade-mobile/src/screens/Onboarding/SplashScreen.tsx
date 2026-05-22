import React, { useEffect, useRef } from 'react';
import {
  View,
  Text,
  StyleSheet,
  Animated,
  Dimensions,
  TouchableOpacity,
} from 'react-native';
import { LinearGradient } from 'expo-linear-gradient';
import { Colors, FontSize, Spacing, BorderRadius } from '../../theme/colors';

const { width, height } = Dimensions.get('window');

interface Props {
  onComplete: () => void;
}

export default function SplashScreen({ onComplete }: Props) {
  const logoScale = useRef(new Animated.Value(0.3)).current;
  const logoOpacity = useRef(new Animated.Value(0)).current;
  const contentOpacity = useRef(new Animated.Value(0)).current;
  const glowAnim = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    Animated.sequence([
      Animated.parallel([
        Animated.spring(logoScale, { toValue: 1, tension: 60, friction: 8, useNativeDriver: true }),
        Animated.timing(logoOpacity, { toValue: 1, duration: 600, useNativeDriver: true }),
      ]),
      Animated.timing(glowAnim, { toValue: 1, duration: 800, useNativeDriver: false }),
      Animated.timing(contentOpacity, { toValue: 1, duration: 700, useNativeDriver: true }),
    ]).start();
  }, []);

  const glowColor = glowAnim.interpolate({
    inputRange: [0, 1],
    outputRange: ['rgba(0,102,255,0)', 'rgba(0,102,255,0.4)'],
  });

  return (
    <View style={styles.container}>
      <View style={styles.center}>
        {/* Logo */}
        <Animated.View
          style={[
            styles.logoWrapper,
            { transform: [{ scale: logoScale }], opacity: logoOpacity },
          ]}
        >
          <Animated.View style={[styles.glow, { shadowColor: glowColor as any }]} />
          <LinearGradient
            colors={['#1A1A2E', '#16213E', '#0F3460']}
            style={styles.logoContainer}
          >
            <Text style={styles.logoText}>AT</Text>
          </LinearGradient>
        </Animated.View>

        {/* Content */}
        <Animated.View style={[styles.content, { opacity: contentOpacity }]}>
          <Text style={styles.launchText}>
            Apex Trade se lansează la începutul lunii viitoare.
          </Text>

          <Text style={styles.descriptionText}>
            Un AI de tranzacționare construit pe baza conceptelor de quant trading și conectat în
            timp real la toate evenimentele macroeconomice globale.
          </Text>

          <Text style={styles.descriptionText}>
            Apex Trade poate executa milioane de backtesting-uri și analiza simultan milioane de
            strategii pentru a identifica cele mai eficiente modele de execuție în funcție de
            condițiile actuale din piață.
          </Text>

          <Text style={styles.descriptionText}>
            În timp ce tu tranzacționezi, el urmărește constant știrile, volatilitatea și
            evenimentele globale care pot influența piața, susținându-te pe tot parcursul tranzacției.
          </Text>

          <Text style={styles.descriptionText}>
            De la validarea unei strategii până la execuția și managementul acesteia, Apex Trade este
            construit pentru o nouă eră a tradingului.
          </Text>

          <Text style={styles.tagline}>
            Quant trading-ul nu mai este viitorul.{'\n'}A devenit prezentul.
          </Text>
        </Animated.View>
      </View>

      {/* CTA Button */}
      <Animated.View style={[styles.buttonContainer, { opacity: contentOpacity }]}>
        <TouchableOpacity onPress={onComplete} activeOpacity={0.85}>
          <LinearGradient
            colors={['#0066FF', '#0044CC']}
            style={styles.button}
            start={{ x: 0, y: 0 }}
            end={{ x: 1, y: 0 }}
          >
            <Text style={styles.buttonText}>Începe acum</Text>
          </LinearGradient>
        </TouchableOpacity>
        <Text style={styles.footerText}>Gratuit 14 zile • Fără card necesar</Text>
      </Animated.View>
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: Colors.background,
    justifyContent: 'space-between',
    paddingBottom: Spacing.xxl,
  },
  center: {
    flex: 1,
    alignItems: 'center',
    paddingTop: height * 0.1,
    paddingHorizontal: Spacing.xl,
  },
  logoWrapper: {
    marginBottom: Spacing.xl,
    alignItems: 'center',
    justifyContent: 'center',
  },
  glow: {
    position: 'absolute',
    width: 160,
    height: 160,
    borderRadius: 80,
    shadowOffset: { width: 0, height: 0 },
    shadowRadius: 40,
    shadowOpacity: 1,
    elevation: 20,
  },
  logoContainer: {
    width: 140,
    height: 140,
    borderRadius: 36,
    alignItems: 'center',
    justifyContent: 'center',
    borderWidth: 1,
    borderColor: 'rgba(0,102,255,0.3)',
  },
  logoText: {
    fontSize: 54,
    fontWeight: '800',
    color: Colors.textPrimary,
    letterSpacing: -2,
  },
  content: {
    alignItems: 'center',
    gap: Spacing.md,
  },
  launchText: {
    fontSize: FontSize.lg,
    color: Colors.textPrimary,
    textAlign: 'center',
    fontWeight: '500',
    marginBottom: Spacing.sm,
  },
  descriptionText: {
    fontSize: FontSize.md,
    color: Colors.textSecondary,
    textAlign: 'center',
    lineHeight: 24,
  },
  tagline: {
    fontSize: FontSize.md,
    color: Colors.textPrimary,
    textAlign: 'center',
    fontWeight: '600',
    marginTop: Spacing.md,
    lineHeight: 24,
  },
  buttonContainer: {
    paddingHorizontal: Spacing.xl,
    alignItems: 'center',
    gap: Spacing.md,
  },
  button: {
    width: width - Spacing.xl * 2,
    paddingVertical: Spacing.md + 2,
    borderRadius: BorderRadius.full,
    alignItems: 'center',
  },
  buttonText: {
    fontSize: FontSize.lg,
    color: Colors.textPrimary,
    fontWeight: '700',
  },
  footerText: {
    fontSize: FontSize.sm,
    color: Colors.textMuted,
    textAlign: 'center',
  },
});

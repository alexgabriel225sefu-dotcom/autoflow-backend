import React, { useEffect, useState } from 'react';
import { View, ActivityIndicator } from 'react-native';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';
import { useDispatch, useSelector } from 'react-redux';
import { AppDispatch, RootState } from '../store';
import { loadUserThunk } from '../store/slices/authSlice';
import { Colors } from '../theme/colors';

// Screens
import SplashScreen from '../screens/Onboarding/SplashScreen';
import LoginScreen from '../screens/Auth/LoginScreen';
import RegisterScreen from '../screens/Auth/RegisterScreen';
import DashboardScreen from '../screens/Dashboard/DashboardScreen';
import MarketsScreen from '../screens/Markets/MarketsScreen';
import SignalsScreen from '../screens/Signals/SignalsScreen';
import BacktestScreen from '../screens/Backtest/BacktestScreen';
import PortfolioScreen from '../screens/Portfolio/PortfolioScreen';
import SettingsScreen from '../screens/Settings/SettingsScreen';

const Stack = createNativeStackNavigator();
const Tab = createBottomTabNavigator();

const TAB_ICONS: Record<string, { active: string; inactive: string }> = {
  Dashboard: { active: '🏠', inactive: '🏠' },
  Markets: { active: '📈', inactive: '📈' },
  Signals: { active: '🤖', inactive: '🤖' },
  Backtest: { active: '⚡', inactive: '⚡' },
  Portfolio: { active: '💼', inactive: '💼' },
  Settings: { active: '⚙️', inactive: '⚙️' },
};

function MainTabs() {
  return (
    <Tab.Navigator
      screenOptions={({ route }) => ({
        headerShown: false,
        tabBarStyle: {
          backgroundColor: '#0D0D0D',
          borderTopColor: '#1A1A1A',
          borderTopWidth: 1,
          paddingTop: 8,
          paddingBottom: 30,
          height: 80,
        },
        tabBarActiveTintColor: Colors.primary,
        tabBarInactiveTintColor: Colors.textMuted,
        tabBarLabelStyle: { fontSize: 10, fontWeight: '600', marginBottom: 2 },
        tabBarIcon: ({ focused, size }) => {
          const icons = TAB_ICONS[route.name];
          return (
            <View style={{ opacity: focused ? 1 : 0.5, alignItems: 'center' }}>
              <View style={[
                focused && {
                  backgroundColor: Colors.primary + '20',
                  borderRadius: 12,
                  paddingHorizontal: 12,
                  paddingVertical: 4,
                },
              ]}>
              </View>
            </View>
          );
        },
      })}
    >
      <Tab.Screen name="Dashboard" component={DashboardScreen} options={{ title: 'Acasă' }} />
      <Tab.Screen name="Markets" component={MarketsScreen} options={{ title: 'Piețe' }} />
      <Tab.Screen name="Signals" component={SignalsScreen} options={{ title: 'Semnale' }} />
      <Tab.Screen name="Backtest" component={BacktestScreen} options={{ title: 'Backtest' }} />
      <Tab.Screen name="Portfolio" component={PortfolioScreen} options={{ title: 'Portofoliu' }} />
      <Tab.Screen name="Settings" component={SettingsScreen} options={{ title: 'Setări' }} />
    </Tab.Navigator>
  );
}

function AuthStack({ onSplashComplete }: { onSplashComplete: () => void }) {
  const [splashDone, setSplashDone] = useState(false);
  const Stack2 = createNativeStackNavigator();

  if (!splashDone) {
    return <SplashScreen onComplete={() => setSplashDone(true)} />;
  }

  return (
    <Stack2.Navigator screenOptions={{ headerShown: false }}>
      <Stack2.Screen name="Login">
        {(props) => (
          <LoginScreen
            {...props}
            onNavigateRegister={() => props.navigation.navigate('Register')}
            onSuccess={onSplashComplete}
          />
        )}
      </Stack2.Screen>
      <Stack2.Screen name="Register">
        {(props) => (
          <RegisterScreen
            {...props}
            onNavigateLogin={() => props.navigation.goBack()}
            onSuccess={onSplashComplete}
          />
        )}
      </Stack2.Screen>
    </Stack2.Navigator>
  );
}

export default function AppNavigator() {
  const dispatch = useDispatch<AppDispatch>();
  const { user, token } = useSelector((s: RootState) => s.auth);
  const [bootstrapped, setBootstrapped] = useState(false);

  useEffect(() => {
    dispatch(loadUserThunk()).finally(() => setBootstrapped(true));
  }, []);

  if (!bootstrapped) {
    return (
      <View style={{ flex: 1, backgroundColor: Colors.background, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator color={Colors.primary} size="large" />
      </View>
    );
  }

  return (
    <NavigationContainer>
      {user && token ? (
        <Stack.Navigator screenOptions={{ headerShown: false }}>
          <Stack.Screen name="Main" component={MainTabs} />
        </Stack.Navigator>
      ) : (
        <AuthStack onSplashComplete={() => {}} />
      )}
    </NavigationContainer>
  );
}

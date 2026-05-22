import { io, Socket } from 'socket.io-client';
import * as SecureStore from 'expo-secure-store';

const WS_URL = process.env.EXPO_PUBLIC_WS_URL || 'wss://apextrade-api.railway.app';

class WebSocketService {
  private socket: Socket | null = null;
  private listeners: Map<string, Set<Function>> = new Map();

  async connect() {
    const token = await SecureStore.getItemAsync('apextrade_token');
    this.socket = io(WS_URL, {
      auth: { token },
      transports: ['websocket'],
      reconnection: true,
      reconnectionAttempts: 10,
      reconnectionDelay: 2000,
    });

    this.socket.on('connect', () => {
      console.log('[WS] Connected');
    });

    this.socket.on('disconnect', (reason) => {
      console.log('[WS] Disconnected:', reason);
    });

    this.socket.on('price_update', (data) => {
      this.emit('price_update', data);
    });

    this.socket.on('signal', (data) => {
      this.emit('signal', data);
    });

    this.socket.on('news', (data) => {
      this.emit('news', data);
    });
  }

  subscribe(symbols: string[], market: string) {
    this.socket?.emit('subscribe', { symbols, market });
  }

  unsubscribe(symbols: string[], market: string) {
    this.socket?.emit('unsubscribe', { symbols, market });
  }

  on(event: string, callback: Function) {
    if (!this.listeners.has(event)) {
      this.listeners.set(event, new Set());
    }
    this.listeners.get(event)!.add(callback);
    return () => this.off(event, callback);
  }

  off(event: string, callback: Function) {
    this.listeners.get(event)?.delete(callback);
  }

  private emit(event: string, data: any) {
    this.listeners.get(event)?.forEach((cb) => cb(data));
  }

  disconnect() {
    this.socket?.disconnect();
    this.socket = null;
    this.listeners.clear();
  }
}

export const wsService = new WebSocketService();

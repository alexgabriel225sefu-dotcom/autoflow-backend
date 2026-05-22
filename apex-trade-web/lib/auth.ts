export interface User {
  id: string;
  email: string;
  name: string;
  plan: string;
  brokerConnected: boolean;
}

export function getToken(): string | null {
  if (typeof window === 'undefined') return null;
  return localStorage.getItem('apex_token');
}

export function getUser(): User | null {
  if (typeof window === 'undefined') return null;
  const raw = localStorage.getItem('apex_user');
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

export function setAuth(token: string, user: User) {
  localStorage.setItem('apex_token', token);
  localStorage.setItem('apex_user', JSON.stringify(user));
}

export function clearAuth() {
  localStorage.removeItem('apex_token');
  localStorage.removeItem('apex_user');
}

export function isLoggedIn(): boolean {
  return !!getToken();
}

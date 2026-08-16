import { createContext, useContext } from 'react';

export interface AuthState {
  mode: 'access_token' | 'accounts';
  email: string | null;
  username: string | null;
  logout: () => Promise<void>;
}

export const AuthContext = createContext<AuthState | null>(null);

export function useAuth(): AuthState {
  const value = useContext(AuthContext);
  if (!value) throw new Error('useAuth must be used inside AuthProvider');
  return value;
}

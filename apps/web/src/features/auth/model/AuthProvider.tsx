import type { ReactNode } from 'react';
import { AuthContext, type AuthState } from './authContext';

export function AuthProvider({ value, children }: { value: AuthState; children: ReactNode }) {
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

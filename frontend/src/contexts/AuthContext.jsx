/**
 * AuthContext — local edition.
 * No Firebase, no login. Every session is admin.
 */
import { createContext, useContext } from 'react';

const LOCAL_USER = {
  uid:         'local',
  email:       'local@localhost',
  displayName: 'Local User',
};

export const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const value = {
    user:    LOCAL_USER,
    role:    'admin',
    isAdmin: true,
    loading: false,
    signOut: () => {},
  };
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}

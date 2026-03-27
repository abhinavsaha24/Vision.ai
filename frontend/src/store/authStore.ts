"use client";

import { create } from "zustand";

interface UserProfile {
  email: string;
  role: string;
}

interface AuthState {
  token: string | null;
  user: UserProfile | null;
  hydrated: boolean;
  loginPending: boolean;
  hydrate: () => void;
  setSession: (token: string, user?: UserProfile | null) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>((set) => ({
  token: null,
  user: null,
  hydrated: false,
  loginPending: false,
  hydrate: () => {
    set({ hydrated: true });
  },
  setSession: (token, user = null) => {
    set({ token, user, loginPending: false });
  },
  logout: () => {
    set({ token: null, user: null, loginPending: false });
  },
}));

function isLikelyJwtToken(token: string | null): token is string {
  if (!token) return false;
  const parts = token.split(".");
  return parts.length === 3 && parts.every((part) => part.length > 0);
}

export function getAuthToken(): string | null {
  const token = useAuthStore.getState().token;
  return isLikelyJwtToken(token) ? token : null;
}

export function bindAuthExpiryListener() {
  if (typeof window === "undefined") return () => undefined;

  const onExpired = () => {
    useAuthStore.getState().logout();
  };

  window.addEventListener("vision-ai-auth-expired", onExpired);
  return () => window.removeEventListener("vision-ai-auth-expired", onExpired);
}

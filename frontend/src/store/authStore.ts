"use client";

import { create } from "zustand";

const TOKEN_KEY = "vision_ai_token";
const TOKEN_COOKIE = "vision_ai_token";
const TOKEN_MAX_AGE_SECONDS = 60 * 60 * 24 * 7;

function setTokenCookie(token: string) {
  if (typeof document === "undefined") return;
  document.cookie = `${TOKEN_COOKIE}=${encodeURIComponent(token)}; path=/; max-age=${TOKEN_MAX_AGE_SECONDS}; samesite=lax`;
}

function clearTokenCookie() {
  if (typeof document === "undefined") return;
  document.cookie = `${TOKEN_COOKIE}=; path=/; max-age=0; samesite=lax`;
}

function readStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

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
    try {
      const token = readStoredToken();
      set({ token, hydrated: true });
    } catch {
      set({ token: null, hydrated: true });
    }
  },
  setSession: (token, user = null) => {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(TOKEN_KEY, token);
    }
    setTokenCookie(token);
    set({ token, user, loginPending: false });
  },
  logout: () => {
    if (typeof window !== "undefined") {
      window.localStorage.removeItem(TOKEN_KEY);
    }
    clearTokenCookie();
    set({ token: null, user: null, loginPending: false });
  },
}));

export function getAuthToken(): string | null {
  return readStoredToken();
}

export function bindAuthExpiryListener() {
  if (typeof window === "undefined") return () => undefined;

  const onExpired = () => {
    useAuthStore.getState().logout();
  };

  window.addEventListener("vision-ai-auth-expired", onExpired);
  return () => window.removeEventListener("vision-ai-auth-expired", onExpired);
}

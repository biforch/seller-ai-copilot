import { TOKEN_KEY, USER_KEY } from '@/lib/constants';
import type { User } from '@/types';

export type AuthSnapshot = {
  user: User | null;
  isLoading: boolean;
};

/** Same-tab notification. Carries no token, user, or response payload. */
export const AUTH_CHANGED_EVENT = 'sellerai-auth-changed';

const SERVER_SNAPSHOT: AuthSnapshot = Object.freeze({
  user: null,
  isLoading: true,
});

const ACCESS_ERROR_KEY = '\0access-error';

let cachedKey: string | null = null;
let cachedSnapshot: AuthSnapshot | null = null;

function readStoragePair(): { tokenRaw: string | null; userRaw: string | null } | 'error' {
  if (typeof window === 'undefined') {
    return { tokenRaw: null, userRaw: null };
  }
  try {
    return {
      tokenRaw: window.localStorage.getItem(TOKEN_KEY),
      userRaw: window.localStorage.getItem(USER_KEY),
    };
  } catch {
    return 'error';
  }
}

function snapshotKey(tokenRaw: string | null, userRaw: string | null, errored: boolean): string {
  if (errored) {
    return ACCESS_ERROR_KEY;
  }
  return JSON.stringify([tokenRaw, userRaw]);
}

function buildSnapshot(tokenRaw: string | null, userRaw: string | null, errored: boolean): AuthSnapshot {
  if (errored || !tokenRaw || !userRaw) {
    return Object.freeze({ user: null, isLoading: false });
  }
  try {
    const parsed: unknown = JSON.parse(userRaw);
    if (!parsed || typeof parsed !== 'object') {
      return Object.freeze({ user: null, isLoading: false });
    }
    return Object.freeze({ user: parsed as User, isLoading: false });
  } catch {
    return Object.freeze({ user: null, isLoading: false });
  }
}

export function getServerSnapshot(): AuthSnapshot {
  return SERVER_SNAPSHOT;
}

export function getClientSnapshot(): AuthSnapshot {
  if (typeof window === 'undefined') {
    return getServerSnapshot();
  }
  const pair = readStoragePair();
  const errored = pair === 'error';
  const tokenRaw = errored ? null : pair.tokenRaw;
  const userRaw = errored ? null : pair.userRaw;
  const key = snapshotKey(tokenRaw, userRaw, errored);
  if (cachedKey === key && cachedSnapshot) {
    return cachedSnapshot;
  }
  const snapshot = buildSnapshot(tokenRaw, userRaw, errored);
  cachedKey = key;
  cachedSnapshot = snapshot;
  return snapshot;
}

export function subscribeAuth(onStoreChange: () => void): () => void {
  const onStorage = (event: StorageEvent) => {
    if (event.key !== null && event.key !== TOKEN_KEY && event.key !== USER_KEY) {
      return;
    }
    onStoreChange();
  };
  const onLocal = () => {
    onStoreChange();
  };
  window.addEventListener('storage', onStorage);
  window.addEventListener(AUTH_CHANGED_EVENT, onLocal);
  return () => {
    window.removeEventListener('storage', onStorage);
    window.removeEventListener(AUTH_CHANGED_EVENT, onLocal);
  };
}

function notifySameTab(): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
}

export function persistAuthSession(token: string, user: User): void {
  window.localStorage.setItem(TOKEN_KEY, token);
  window.localStorage.setItem(USER_KEY, JSON.stringify(user));
  notifySameTab();
}

export function clearAuthSession(): void {
  window.localStorage.removeItem(TOKEN_KEY);
  window.localStorage.removeItem(USER_KEY);
  notifySameTab();
}

export function hasAuthToken(): boolean {
  try {
    if (typeof window === 'undefined') {
      return false;
    }
    return Boolean(window.localStorage.getItem(TOKEN_KEY));
  } catch {
    return false;
  }
}

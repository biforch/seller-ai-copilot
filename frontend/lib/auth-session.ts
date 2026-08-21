import { registerSessionInvalidHandler } from '@/lib/auth-invalidation';
import type { User } from '@/types';

export type AuthSnapshot = {
  user: User | null;
  isLoading: boolean;
};

export type AuthBroadcastType = 'authenticated' | 'logged_out' | 'session_invalid';

/** Same-tab notification. Carries no token, user, or response payload. */
export const AUTH_CHANGED_EVENT = 'sellerai-auth-changed';

export const AUTH_BROADCAST_CHANNEL = 'sellerai-auth';
const SERVER_SNAPSHOT: AuthSnapshot = Object.freeze({
  user: null,
  isLoading: true,
});

const ALLOWED_BROADCAST_TYPES = new Set<AuthBroadcastType>([
  'authenticated',
  'logged_out',
  'session_invalid',
]);

let memorySnapshot: AuthSnapshot = Object.freeze({
  user: null,
  isLoading: true,
});

let bootstrapPromise: Promise<void> | null = null;
let bootstrapGeneration = 0;
let hasBootstrapped = false;
let broadcastChannel: BroadcastChannel | null | undefined;
let listeners = 0;

function emitSameTabChange(): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.dispatchEvent(new Event(AUTH_CHANGED_EVENT));
}

function invalidateInFlightBootstrap(): void {
  bootstrapGeneration += 1;
  bootstrapPromise = null;
}

function applySnapshot(next: AuthSnapshot): void {
  memorySnapshot = Object.freeze({
    user: next.user,
    isLoading: next.isLoading,
  });
  emitSameTabChange();
}

function handleBroadcastMessage(event: MessageEvent): void {
  const payload = event.data;
  if (!payload || typeof payload !== 'object') {
    return;
  }
  const type = (payload as { type?: unknown }).type;
  if (typeof type !== 'string' || !ALLOWED_BROADCAST_TYPES.has(type as AuthBroadcastType)) {
    return;
  }
  if (type === 'authenticated') {
    void bootstrapAuth();
    return;
  }
  invalidateInFlightBootstrap();
  applySnapshot({ user: null, isLoading: false });
}

function getBroadcastChannel(): BroadcastChannel | null {
  if (typeof window === 'undefined') {
    return null;
  }
  if (broadcastChannel === undefined) {
    if (typeof BroadcastChannel === 'undefined') {
      broadcastChannel = null;
    } else {
      try {
        const channel = new BroadcastChannel(AUTH_BROADCAST_CHANNEL);
        channel.onmessage = handleBroadcastMessage;
        broadcastChannel = channel;
      } catch {
        broadcastChannel = null;
      }
    }
  }
  return broadcastChannel;
}

function postBroadcast(type: AuthBroadcastType): void {
  try {
    getBroadcastChannel()?.postMessage({ type });
  } catch {
    // Ignore channel failures; same-tab state still updates.
  }
}

export function getServerSnapshot(): AuthSnapshot {
  return SERVER_SNAPSHOT;
}

export function getClientSnapshot(): AuthSnapshot {
  if (typeof window === 'undefined') {
    return getServerSnapshot();
  }
  return memorySnapshot;
}

export async function bootstrapAuth(): Promise<void> {
  if (typeof window === 'undefined') {
    return;
  }
  if (bootstrapPromise) {
    return bootstrapPromise;
  }

  const generation = ++bootstrapGeneration;
  bootstrapPromise = (async () => {
    applySnapshot({ user: memorySnapshot.user, isLoading: true });
    try {
      const { apiClient } = await import('@/app/api/client');
      const user = await apiClient.get<User>('/auth/me');
      if (generation !== bootstrapGeneration) {
        return;
      }
      applySnapshot({ user, isLoading: false });
    } catch {
      if (generation !== bootstrapGeneration) {
        return;
      }
      applySnapshot({ user: null, isLoading: false });
    }
  })().finally(() => {
    bootstrapPromise = null;
  });

  return bootstrapPromise;
}

export function markAuthenticated(user: User): void {
  invalidateInFlightBootstrap();
  applySnapshot({ user, isLoading: false });
  postBroadcast('authenticated');
}

export function markLoggedOut(): void {
  invalidateInFlightBootstrap();
  applySnapshot({ user: null, isLoading: false });
  postBroadcast('logged_out');
}

export function markSessionInvalid(): void {
  invalidateInFlightBootstrap();
  applySnapshot({ user: null, isLoading: false });
  postBroadcast('session_invalid');
}

export function subscribeAuth(onStoreChange: () => void): () => void {
  if (typeof window === 'undefined') {
    return () => {};
  }

  // Create the receive channel in this browsing context. Do not wait for a
  // local markAuthenticated / markLoggedOut / markSessionInvalid.
  // Keep the singleton open for the store lifetime so StrictMode
  // unsubscribe/resubscribe does not permanently drop the channel.
  getBroadcastChannel();

  listeners += 1;
  if (!hasBootstrapped) {
    hasBootstrapped = true;
    void bootstrapAuth();
  }

  const onLocal = () => {
    onStoreChange();
  };

  window.addEventListener(AUTH_CHANGED_EVENT, onLocal);

  return () => {
    window.removeEventListener(AUTH_CHANGED_EVENT, onLocal);
    listeners = Math.max(0, listeners - 1);
  };
}

export function isAuthenticated(): boolean {
  return memorySnapshot.user !== null;
}

if (typeof window !== 'undefined') {
  registerSessionInvalidHandler(() => {
    markSessionInvalid();
  });
}

export function __resetAuthStoreForTests(): void {
  invalidateInFlightBootstrap();
  memorySnapshot = Object.freeze({ user: null, isLoading: true });
  hasBootstrapped = false;
  listeners = 0;
  if (broadcastChannel) {
    broadcastChannel.onmessage = null;
    broadcastChannel.close();
  }
  broadcastChannel = undefined;
}

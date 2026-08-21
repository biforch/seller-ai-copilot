import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';

type BroadcastHandler = ((event: MessageEvent) => void) | null;

class IsolatedBroadcastChannel {
  static #groups = new Map<string, Set<IsolatedBroadcastChannel>>();

  onmessage: BroadcastHandler = null;
  readonly name: string;

  constructor(name: string) {
    this.name = name;
    const group = IsolatedBroadcastChannel.#groups.get(name) ?? new Set();
    group.add(this);
    IsolatedBroadcastChannel.#groups.set(name, group);
  }

  postMessage(data: unknown): void {
    const group = IsolatedBroadcastChannel.#groups.get(this.name);
    if (!group) {
      return;
    }
    for (const peer of group) {
      if (peer === this || typeof peer.onmessage !== 'function') {
        continue;
      }
      peer.onmessage({ data } as MessageEvent);
    }
  }

  close(): void {
    this.onmessage = null;
    const group = IsolatedBroadcastChannel.#groups.get(this.name);
    group?.delete(this);
  }

  static reset(): void {
    for (const group of IsolatedBroadcastChannel.#groups.values()) {
      for (const channel of group) {
        channel.onmessage = null;
      }
      group.clear();
    }
    IsolatedBroadcastChannel.#groups.clear();
  }
}

const IsolatedBroadcastChannelGlobal = IsolatedBroadcastChannel as unknown as typeof BroadcastChannel;

Object.defineProperty(window, 'BroadcastChannel', {
  configurable: true,
  writable: true,
  value: IsolatedBroadcastChannelGlobal,
});
Object.defineProperty(globalThis, 'BroadcastChannel', {
  configurable: true,
  writable: true,
  value: IsolatedBroadcastChannelGlobal,
});

afterEach(() => {
  IsolatedBroadcastChannel.reset();
});

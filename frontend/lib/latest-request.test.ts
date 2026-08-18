import { describe, expect, it } from 'vitest';

import { GateDisposedError, LatestRequestGate } from '@/lib/latest-request';

describe('LatestRequestGate', () => {
  it('begin aborts the previous lease and marks it stale', () => {
    const gate = new LatestRequestGate();
    const first = gate.begin();
    const second = gate.begin();

    expect(first.signal.aborted).toBe(true);
    expect(first.isCurrent()).toBe(false);
    expect(second.isCurrent()).toBe(true);
    expect(second.generation).toBeGreaterThan(first.generation);
  });

  it('invalidate marks the active lease stale and prevents it from becoming current again', () => {
    const gate = new LatestRequestGate();
    const lease = gate.begin();

    gate.invalidate();

    expect(lease.signal.aborted).toBe(true);
    expect(lease.isCurrent()).toBe(false);

    const next = gate.begin();
    expect(lease.isCurrent()).toBe(false);
    expect(next.isCurrent()).toBe(true);
    expect(next.generation).toBeGreaterThan(lease.generation);
  });

  it('dispose marks the active lease stale', () => {
    const gate = new LatestRequestGate();
    const lease = gate.begin();

    gate.dispose();

    expect(lease.signal.aborted).toBe(true);
    expect(lease.isCurrent()).toBe(false);
  });

  it('throws a stable error when begin is called after dispose', () => {
    const gate = new LatestRequestGate();
    gate.dispose();

    expect(() => gate.begin()).toThrow(GateDisposedError);
    expect(() => gate.begin()).toThrow('LatestRequestGate is disposed');
  });

  it('tolerates repeated invalidate and dispose calls', () => {
    const gate = new LatestRequestGate();
    gate.begin();

    expect(() => {
      gate.invalidate();
      gate.invalidate();
      gate.dispose();
      gate.dispose();
    }).not.toThrow();
  });

  it('keeps generation monotonic', () => {
    const gate = new LatestRequestGate();
    const first = gate.begin();
    gate.invalidate();
    const second = gate.begin();
    gate.dispose();

    expect(second.generation).toBeGreaterThan(first.generation);
    expect(() => gate.begin()).toThrow(GateDisposedError);
  });
});

export class GateDisposedError extends Error {
  constructor() {
    super('LatestRequestGate is disposed');
    this.name = 'GateDisposedError';
  }
}

export type RequestLease = {
  generation: number;
  signal: AbortSignal;
  isCurrent(): boolean;
};

/** Serializes async reads so only the latest lease may commit results. */
export class LatestRequestGate {
  private generation = 0;

  private controller: AbortController | null = null;

  private disposed = false;

  begin(): RequestLease {
    if (this.disposed) {
      throw new GateDisposedError();
    }
    this.controller?.abort();
    this.generation += 1;
    const generation = this.generation;
    const controller = new AbortController();
    this.controller = controller;
    const gate = this;

    return {
      generation,
      signal: controller.signal,
      isCurrent() {
        return (
          !gate.disposed
          && gate.generation === generation
          && !controller.signal.aborted
        );
      },
    };
  }

  invalidate(): void {
    if (this.disposed) {
      return;
    }
    this.controller?.abort();
    this.controller = null;
    this.generation += 1;
  }

  dispose(): void {
    if (this.disposed) {
      return;
    }
    this.disposed = true;
    this.controller?.abort();
    this.controller = null;
    this.generation += 1;
  }
}

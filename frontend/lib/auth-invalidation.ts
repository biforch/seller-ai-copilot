type SessionInvalidHandler = () => void;

let sessionInvalidHandler: SessionInvalidHandler | null = null;

export function registerSessionInvalidHandler(handler: SessionInvalidHandler): void {
  sessionInvalidHandler = handler;
}

export function notifySessionInvalid(): void {
  sessionInvalidHandler?.();
}

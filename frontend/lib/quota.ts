/** Clamp displayed remaining quota so UI never shows negative values after overage. */
export function displayRemainingTokens(remaining: number): number {
  return Math.max(remaining, 0);
}

/** Compute remaining from usage payload; clamps to zero for display. */
export function remainingFromUsage(usage: {
  monthly_tokens: number;
  used_tokens: number;
  reserved_tokens?: number;
}): number {
  const reserved = usage.reserved_tokens ?? 0;
  return displayRemainingTokens(usage.monthly_tokens - usage.used_tokens - reserved);
}

import { CSRF_COOKIE_NAME } from '@/lib/constants';

export function readCsrfTokenFromCookie(): string | null {
  if (typeof document === 'undefined') {
    return null;
  }

  const segments = document.cookie.split(';');
  for (const segment of segments) {
    const trimmed = segment.trim();
    if (!trimmed.startsWith(`${CSRF_COOKIE_NAME}=`)) {
      continue;
    }
    const rawValue = trimmed.slice(CSRF_COOKIE_NAME.length + 1);
    if (!rawValue) {
      return null;
    }
    try {
      return decodeURIComponent(rawValue);
    } catch {
      return null;
    }
  }

  return null;
}

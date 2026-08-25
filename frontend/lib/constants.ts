export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || 'SellerAI Copilot';

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export const PLATFORMS = ['Amazon', 'Shopify', 'eBay', 'Walmart'] as const;

export const MARKETS = ['USA', 'UK', 'DE', 'JP', 'CA', 'AU'] as const;

export const CSRF_COOKIE_NAME = 'sellerai_csrf';
export const CSRF_HEADER_NAME = 'X-CSRF-Token';

export const CSRF_EXEMPT_API_PATHS = ['/auth/login', '/auth/register'] as const;

export const PASSWORD_MIN_LENGTH = 12;
export const PASSWORD_MAX_LENGTH = 128;

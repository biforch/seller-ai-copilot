export const APP_NAME = process.env.NEXT_PUBLIC_APP_NAME || 'SellerAI Copilot';

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api/v1';

export const PLATFORMS = ['Amazon', 'Shopify', 'eBay', 'Walmart'] as const;

export const MARKETS = ['USA', 'UK', 'DE', 'JP', 'CA', 'AU'] as const;

export const TOKEN_KEY = 'access_token';
export const USER_KEY = 'user';

export const PASSWORD_MIN_LENGTH = 8;

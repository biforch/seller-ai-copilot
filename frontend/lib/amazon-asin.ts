export interface ParsedAmazonReference {
  asin: string;
  marketplaceCode: string | null;
}

const MARKETPLACE_BY_HOST: Record<string, string> = {
  'amazon.com': 'US',
  'amazon.ca': 'CA',
  'amazon.com.mx': 'MX',
  'amazon.co.uk': 'UK',
  'amazon.de': 'DE',
  'amazon.fr': 'FR',
  'amazon.it': 'IT',
  'amazon.es': 'ES',
  'amazon.co.jp': 'JP',
  'amazon.com.au': 'AU',
};

export function parseAmazonReference(rawValue: string): ParsedAmazonReference | null {
  const value = rawValue.trim();
  if (/^[A-Za-z0-9]{10}$/.test(value)) return { asin: value.toUpperCase(), marketplaceCode: null };

  let url: URL;
  try {
    url = new URL(/^https?:\/\//i.test(value) ? value : `https://${value}`);
  } catch {
    return null;
  }
  const host = url.hostname.toLowerCase().replace(/^(www|smile)\./, '');
  const marketplaceCode = MARKETPLACE_BY_HOST[host];
  if (!marketplaceCode) return null;
  const match = url.pathname.match(/\/(?:dp|gp\/product|product|ASIN)\/([A-Za-z0-9]{10})(?:[/?]|$)/i);
  return match ? { asin: match[1].toUpperCase(), marketplaceCode } : null;
}

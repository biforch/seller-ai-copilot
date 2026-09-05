import { describe, expect, it } from 'vitest';

import { parseAmazonReference } from '@/lib/amazon-asin';

describe('parseAmazonReference', () => {
  it('accepts a bare ASIN', () => {
    expect(parseAmazonReference(' b0abc12345 ')).toEqual({ asin: 'B0ABC12345', marketplaceCode: null });
  });

  it('extracts ASIN and marketplace from common Amazon links', () => {
    expect(parseAmazonReference('https://www.amazon.com/dp/B0ABC12345?tag=test')).toEqual({ asin: 'B0ABC12345', marketplaceCode: 'US' });
    expect(parseAmazonReference('amazon.co.uk/gp/product/B0XYZ98765/')).toEqual({ asin: 'B0XYZ98765', marketplaceCode: 'UK' });
  });

  it('rejects non-Amazon hosts and malformed references', () => {
    expect(parseAmazonReference('https://evilamazon.com/dp/B0ABC12345')).toBeNull();
    expect(parseAmazonReference('not-an-asin')).toBeNull();
  });
});

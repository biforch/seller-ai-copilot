import { describe, expect, it } from 'vitest';

import { metadata } from './layout';

describe('Listnara brand metadata', () => {
  it('uses the public product name and listing-audit positioning', () => {
    expect(metadata.title).toBe('Amazon Listing Audit Tool | Listnara');
    expect(metadata.description).toContain('Audit your Amazon listing');
  });
});

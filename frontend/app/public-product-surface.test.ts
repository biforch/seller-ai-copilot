import { readFileSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const frontendRoot = process.cwd();
const read = (path: string) => readFileSync(join(frontendRoot, path), 'utf8');

describe('public Listnara product surface', () => {
  it('keeps every indexed marketing and policy route in the app and sitemap', () => {
    const routes = [
      'about',
      'amazon-integration',
      'amazon-listing-audit',
      'contact',
      'methodology',
      'pricing',
      'privacy',
      'refund',
      'sample-report',
      'terms',
    ];
    const sitemap = read('app/sitemap.ts');
    for (const route of routes) {
      expect(read(`app/${route}/page.tsx`).length).toBeGreaterThan(100);
      expect(sitemap).toContain(`'/${route}'`);
    }
  });

  it('publishes legal and merchant-review navigation without claiming billing is live', () => {
    const footer = read('components/common/Footer.tsx');
    for (const route of ['about', 'contact', 'pricing', 'privacy', 'terms', 'refund']) {
      expect(footer).toContain(`href="/${route}"`);
    }
    expect(read('app/pricing/page.tsx')).toContain('Coming soon');
    expect(read('app/refund/page.tsx')).toContain('paid plans');
  });

  it('preserves manual ASIN submission and the pending SP-API entry', () => {
    const auditPage = read('app/(dashboard)/audits/new/page.tsx');
    expect(read('lib/amazon-asin.ts')).toContain('parseAmazonReference');
    expect(auditPage).toContain('Start with ASIN or URL');
    expect(auditPage).toContain('Verified product context supplied by the seller');
    expect(auditPage).not.toContain('type="file"');
    expect(read('app/amazon-integration/page.tsx')).toContain('approval is pending');
    expect(read('components/common/Header.tsx')).toContain('Amazon SP-API');
  });

  it('keeps private application routes out of search indexes', () => {
    const config = read('next.config.js');
    expect(config).toContain('X-Robots-Tag');
    expect(config).toContain('noindex, nofollow, noarchive');
  });
});

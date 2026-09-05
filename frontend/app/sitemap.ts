import type { MetadataRoute } from 'next';

import { PUBLIC_SITE_URL } from '@/lib/site-url';

const publicPaths = [
  '',
  '/amazon-listing-audit',
  '/amazon-integration',
  '/methodology',
  '/sample-report',
  '/about',
  '/pricing',
  '/contact',
  '/privacy',
  '/terms',
  '/refund',
];

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date('2026-08-31T00:00:00Z');
  return publicPaths.map((path) => ({
    url: `${PUBLIC_SITE_URL}${path}`,
    lastModified,
    changeFrequency: path === '' || path === '/pricing' ? 'weekly' : 'monthly',
    priority: path === '' ? 1 : path === '/amazon-listing-audit' || path === '/sample-report' ? 0.9 : 0.7,
  }));
}


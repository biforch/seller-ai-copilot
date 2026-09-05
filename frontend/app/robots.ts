import type { MetadataRoute } from 'next';

import { PUBLIC_SITE_URL } from '@/lib/site-url';

export default function robots(): MetadataRoute.Robots {
  return {
    rules: {
      userAgent: '*',
      allow: '/',
      disallow: [
        '/analytics',
        '/amazon',
        '/audits',
        '/billing',
        '/dashboard',
        '/generate',
        '/login',
        '/products',
        '/projects',
        '/register',
      ],
    },
    sitemap: `${PUBLIC_SITE_URL}/sitemap.xml`,
    host: PUBLIC_SITE_URL,
  };
}

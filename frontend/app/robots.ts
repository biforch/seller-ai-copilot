import type { MetadataRoute } from 'next';

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
    sitemap: 'https://listnara.com/sitemap.xml',
    host: 'https://listnara.com',
  };
}

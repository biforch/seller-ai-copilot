export const PUBLIC_SITE_URL = 'https://app.listnara.com';

export function publicAbsoluteUrl(path: string): string {
  if (!path.startsWith('/')) {
    return `${PUBLIC_SITE_URL}/${path}`;
  }
  return `${PUBLIC_SITE_URL}${path}`;
}

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import {
  AMAZON_WORKSPACE_VISIBLE,
  ANALYSIS_PUBLIC_ENABLED,
  LEGACY_GENERATION_VISIBLE,
} from '@/lib/feature-flags';

const readSource = (path: string) => readFileSync(resolve(process.cwd(), path), 'utf8');

describe('frozen product capabilities', () => {
  it('keeps every frozen/public surface off at the code level', () => {
    expect(AMAZON_WORKSPACE_VISIBLE).toBe(false);
    expect(LEGACY_GENERATION_VISIBLE).toBe(false);
    expect(ANALYSIS_PUBLIC_ENABLED).toBe(false);
  });

  it('does not expose Amazon or legacy Generate navigation', () => {
    const entrySources = [
      'components/common/Header.tsx',
      'app/(dashboard)/dashboard/page.tsx',
      'app/(dashboard)/projects/[id]/page.tsx',
      'app/(dashboard)/products/page.tsx',
    ].map(readSource);

    for (const source of entrySources) {
      expect(source).not.toContain("router.push('/amazon')");
      expect(source).not.toContain("router.push('/generate')");
      expect(source).not.toContain('router.push(`/generate?');
    }
  });

  it('returns not-found for direct frozen workspace routes', () => {
    const amazonLayout = readSource('app/(dashboard)/amazon/layout.tsx');
    const generatePage = readSource('app/(dashboard)/generate/page.tsx');

    expect(amazonLayout).toContain('if (!AMAZON_WORKSPACE_VISIBLE)');
    expect(amazonLayout).toContain('notFound()');
    expect(generatePage).toContain('if (!LEGACY_GENERATION_VISIBLE)');
    expect(generatePage).toContain('notFound()');
  });
});

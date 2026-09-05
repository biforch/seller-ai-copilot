import { describe, expect, it } from 'vitest';

import { metadata as loginMetadata } from '@/app/(auth)/login/layout';
import { metadata as registerMetadata } from '@/app/(auth)/register/layout';

describe('auth page metadata', () => {
  it('sets distinct titles for login and register', () => {
    expect(loginMetadata.title).toBe('Sign In — Listnara');
    expect(registerMetadata.title).toBe('Create Account — Listnara');
  });

  it('keeps auth routes out of search indexes', () => {
    expect(loginMetadata.robots).toEqual({ index: false, follow: true });
    expect(registerMetadata.robots).toEqual({ index: false, follow: true });
  });
});

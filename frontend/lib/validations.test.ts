import { describe, expect, it } from 'vitest';

import { validatePassword } from './validations';

describe('password validation', () => {
  it('accepts the shared backend password policy', () => {
    expect(validatePassword('Password1!abc')).toEqual({ valid: true });
  });

  it.each([
    ['Short1!', 'at least 12'],
    ['lowercase123!', 'uppercase'],
    ['UPPERCASE123!', 'lowercase'],
    ['NoNumbersHere!', 'number'],
    ['NoSpecial1234', 'special'],
    [`Aa1!${'x'.repeat(125)}`, 'at most 128'],
  ])('rejects %s', (password, message) => {
    const result = validatePassword(password);
    expect(result.valid).toBe(false);
    expect(result.message).toContain(message);
  });
});

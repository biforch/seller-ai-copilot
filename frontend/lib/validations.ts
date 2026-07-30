import { PASSWORD_MIN_LENGTH } from './constants';

export interface ValidationResult {
  valid: boolean;
  message?: string;
}

export function validateEmail(email: string): ValidationResult {
  const pattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  if (!pattern.test(email)) {
    return { valid: false, message: 'Please enter a valid email address' };
  }
  return { valid: true };
}

export function validatePassword(password: string): ValidationResult {
  if (password.length < PASSWORD_MIN_LENGTH) {
    return {
      valid: false,
      message: `Password must be at least ${PASSWORD_MIN_LENGTH} characters`,
    };
  }
  if (!/[A-Za-z]/.test(password)) {
    return { valid: false, message: 'Password must contain letters' };
  }
  if (!/\d/.test(password)) {
    return { valid: false, message: 'Password must contain numbers' };
  }
  return { valid: true };
}

export function validatePasswordMatch(
  password: string,
  confirmPassword: string
): ValidationResult {
  if (password !== confirmPassword) {
    return { valid: false, message: 'Passwords do not match' };
  }
  return { valid: true };
}

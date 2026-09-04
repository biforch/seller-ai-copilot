'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { Eye, EyeOff, Loader2 } from 'lucide-react';

import { useAuth } from '@/hooks/useAuth';
import { apiClient } from '@/app/api/client';
import { markAuthenticated } from '@/lib/auth-session';
import type { MfaCompletionResponse, MfaSetupResponse } from '@/types';

type LoginStep = 'password' | 'enroll' | 'verify' | 'recovery';

export default function LoginPage() {
  const router = useRouter();
  const { login, user, isLoading: authLoading } = useAuth();

  useEffect(() => {
    if (!authLoading && user) {
      router.push('/dashboard');
    }
  }, [user, authLoading, router]);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [step, setStep] = useState<LoginStep>('password');
  const [mfaCode, setMfaCode] = useState('');
  const [mfaSetup, setMfaSetup] = useState<MfaSetupResponse | null>(null);
  const [recoveryCodes, setRecoveryCodes] = useState<string[]>([]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsSubmitting(true);
    setError('');

    try {
      const result = await login(email, password);
      if (result.mfa_enrollment_required) {
        const setup = await apiClient.post<MfaSetupResponse>('/auth/mfa/setup');
        setMfaSetup(setup);
        setStep('enroll');
      } else {
        setStep('verify');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Something went wrong');
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleMfa = async (event: React.FormEvent) => {
    event.preventDefault();
    setIsSubmitting(true);
    setError('');
    try {
      const endpoint = step === 'enroll' ? '/auth/mfa/confirm' : '/auth/mfa/verify';
      const result = await apiClient.post<MfaCompletionResponse>(endpoint, {
        code: mfaCode,
      });
      if (result.recovery_codes?.length) {
        setRecoveryCodes(result.recovery_codes);
        setStep('recovery');
        return;
      }
      markAuthenticated(result.user);
      router.push('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'MFA verification failed');
    } finally {
      setIsSubmitting(false);
    }
  };

  const finishEnrollment = async () => {
    setIsSubmitting(true);
    setError('');
    try {
      const account = await apiClient.get<MfaCompletionResponse['user']>('/auth/me');
      markAuthenticated(account);
      router.push('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unable to continue');
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-b from-slate-50 to-white px-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
            Listnara
          </h1>
          <p className="text-gray-600 mt-2">Sign in to your account</p>
        </div>

        <div className="bg-white rounded-2xl shadow-lg border p-8">
          {error && (
            <div className="bg-red-50 text-red-600 p-3 rounded-lg text-sm mb-4">
              {error}
            </div>
          )}

          {step === 'password' && <form onSubmit={handleSubmit} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Email Address
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
                placeholder="you@example.com"
                required
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Password
              </label>
              <div className="relative">
                <input
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none pr-10"
                  placeholder="••••••••"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-500 hover:text-gray-700"
                >
                  {showPassword ? (
                    <EyeOff className="w-4 h-4" />
                  ) : (
                    <Eye className="w-4 h-4" />
                  )}
                </button>
              </div>
            </div>

            <button
              type="submit"
              disabled={isSubmitting}
              className="w-full py-2.5 bg-blue-600 text-white font-medium rounded-lg hover:bg-blue-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
            >
              {isSubmitting ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" />
                  Signing in...
                </>
              ) : (
                'Sign In'
              )}
            </button>
          </form>}

          {(step === 'enroll' || step === 'verify') && (
            <form onSubmit={handleMfa} className="space-y-4">
              {step === 'enroll' && mfaSetup && (
                <div className="space-y-3 text-sm text-gray-700">
                  <h2 className="text-lg font-semibold text-gray-900">Set up multi-factor authentication</h2>
                  <p>Add this key to your authenticator app, then enter the current 6-digit code.</p>
                  <code className="block break-all rounded bg-slate-100 p-3 select-all">{mfaSetup.secret}</code>
                </div>
              )}
              {step === 'verify' && (
                <h2 className="text-lg font-semibold text-gray-900">Enter your authentication code</h2>
              )}
              <input
                value={mfaCode}
                onChange={(event) => setMfaCode(event.target.value)}
                autoComplete="one-time-code"
                inputMode={step === 'verify' ? 'text' : 'numeric'}
                className="w-full px-4 py-2 border rounded-lg focus:ring-2 focus:ring-blue-500 outline-none"
                placeholder="6-digit code or recovery code"
                required
              />
              <button disabled={isSubmitting} className="w-full py-2.5 bg-blue-600 text-white font-medium rounded-lg disabled:opacity-50">
                {isSubmitting ? 'Verifying…' : 'Verify'}
              </button>
            </form>
          )}

          {step === 'recovery' && (
            <div className="space-y-4">
              <h2 className="text-lg font-semibold">Save your recovery codes</h2>
              <p className="text-sm text-gray-600">Store these one-time codes securely. They will not be shown again.</p>
              <pre className="rounded bg-slate-100 p-4 text-sm whitespace-pre-wrap select-all">{recoveryCodes.join('\n')}</pre>
              <button disabled={isSubmitting} onClick={() => void finishEnrollment()} className="w-full py-2.5 bg-blue-600 text-white font-medium rounded-lg disabled:opacity-50">I saved these codes</button>
            </div>
          )}

          {step === 'password' && <p className="text-center text-sm text-gray-600 mt-6">
            Don&apos;t have an account?{' '}
            <Link href="/register" className="text-blue-600 hover:underline font-medium">
              Create one now
            </Link>
          </p>}
        </div>
      </div>
    </div>
  );
}

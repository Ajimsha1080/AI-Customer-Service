'use client';
import React, { useState, useEffect, Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';
import { Bot, CheckCircle, AlertCircle, Loader2, ArrowRight } from 'lucide-react';
import { API_BASE } from '@/lib/api';

function VerifyEmailForm() {
  const searchParams = useSearchParams();
  const token = searchParams.get('token') || '';

  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      setError('No verification token provided. Please check your verification email link.');
      return;
    }

    const verify = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`${API_BASE}/api/v1/auth/verify-email`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ token })
        });

        const data = await res.json();
        if (!res.ok) {
          throw new Error(data.detail || 'Email verification failed. The link may have expired.');
        }

        setSuccess(true);
      } catch (err: any) {
        setError(err.message || 'Verification failed.');
      } finally {
        setLoading(false);
      }
    };

    verify();
  }, [token]);

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col justify-center py-12 sm:px-6 lg:px-8 text-slate-100">
      <div className="sm:mx-auto sm:w-full sm:max-w-md">
        <div className="flex justify-center items-center gap-2 mb-2">
          <div className="p-2.5 rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-500 text-white shadow-lg shadow-indigo-500/25">
            <Bot className="w-8 h-8" />
          </div>
        </div>
        <h2 className="text-center text-3xl font-bold tracking-tight text-white">
          Email Verification
        </h2>
      </div>

      <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md px-4 sm:px-0">
        <div className="bg-slate-900 border border-slate-800 py-8 px-6 shadow-xl rounded-2xl sm:px-10 text-center">
          {loading && (
            <div className="py-8 space-y-4">
              <Loader2 className="w-10 h-10 animate-spin text-indigo-500 mx-auto" />
              <p className="text-slate-300">Verifying your email address...</p>
            </div>
          )}

          {!loading && success && (
            <div className="space-y-4">
              <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-emerald-500/10 text-emerald-400">
                <CheckCircle className="h-6 w-6" />
              </div>
              <h3 className="text-lg font-medium text-white">Email verified successfully!</h3>
              <p className="text-sm text-slate-400">
                Thank you for verifying your email address. Your account is fully active.
              </p>
              <div className="pt-4">
                <Link
                  href="/login"
                  className="w-full inline-flex justify-center items-center py-2.5 px-4 border border-transparent rounded-lg shadow-sm text-sm font-medium text-white bg-indigo-600 hover:bg-indigo-500 focus:outline-none transition"
                >
                  Continue to Sign In
                  <ArrowRight className="ml-2 h-4 w-4" />
                </Link>
              </div>
            </div>
          )}

          {!loading && error && (
            <div className="space-y-4">
              <div className="mx-auto flex items-center justify-center h-12 w-12 rounded-full bg-rose-500/10 text-rose-400">
                <AlertCircle className="h-6 w-6" />
              </div>
              <h3 className="text-lg font-medium text-white">Verification Failed</h3>
              <p className="text-sm text-rose-400">{error}</p>
              <div className="pt-4">
                <Link
                  href="/login"
                  className="inline-flex items-center text-sm font-medium text-indigo-400 hover:text-indigo-300"
                >
                  Back to Sign In
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense fallback={
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <Loader2 className="w-8 h-8 animate-spin text-white" />
      </div>
    }>
      <VerifyEmailForm />
    </Suspense>
  );
}

'use client';
import React, { useEffect, useState } from 'react';
import { Key, ShieldCheck, RefreshCw, AlertCircle } from 'lucide-react';

interface PlatformCredentials {
  sarvam_api_key_configured: boolean;
  sarvam_api_key_masked: string;
  openai_api_key_configured: boolean;
  openai_api_key_masked: string;
  anthropic_api_key_configured: boolean;
  anthropic_api_key_masked: string;
}

export default function PlatformSettingsPage() {
  const [credentials, setCredentials] = useState<PlatformCredentials | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function loadSettings() {
      try {
        setLoading(true);
        const res = await fetch('/api/v1/platform/settings', {
          headers: {
            'Content-Type': 'application/json',
          },
          credentials: 'include',
        });
        if (!res.ok) {
          if (res.status === 401 || res.status === 403) {
            setError('Super Admin privileges required to view platform infrastructure settings.');
          } else {
            setError(`Failed to load credentials (${res.status})`);
          }
          return;
        }
        const data = await res.json();
        setCredentials(data);
      } catch (err: any) {
        setError(err.message || 'Error fetching platform settings');
      } finally {
        setLoading(false);
      }
    }
    loadSettings();
  }, []);

  return (
    <div className="max-w-4xl mx-auto space-y-8 font-sans">
      <div className="border-b border-zinc-200 pb-6">
        <h1 className="text-2xl font-bold text-zinc-900">Platform Infrastructure Settings</h1>
        <p className="text-xs text-zinc-500 mt-1">
          Managed provider keys and multi-tenant security policies. Secrets are loaded from secure KMS / environment config and masked.
        </p>
      </div>

      <div className="yc-card p-6 space-y-6">
        <h2 className="text-sm font-bold text-zinc-900 flex items-center gap-2">
          <Key className="w-4 h-4 text-zinc-700" /> Managed Provider API Keys (Sarvam AI + LiteLLM Layer)
        </h2>

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-xs flex items-center gap-2">
            <AlertCircle className="w-4 h-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {loading ? (
          <div className="flex items-center gap-2 text-xs text-zinc-500 py-4">
            <RefreshCw className="w-4 h-4 animate-spin" /> Loading masked configuration...
          </div>
        ) : (
          <div className="space-y-4 text-xs font-mono">
            <div>
              <div className="flex justify-between items-center mb-1">
                <label className="text-zinc-700 font-semibold">Sarvam AI API Key (Indic LLM & Voice)</label>
                <span className={`text-[10px] font-sans px-2 py-0.5 rounded ${credentials?.sarvam_api_key_configured ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-amber-50 text-amber-700 border border-amber-200'}`}>
                  {credentials?.sarvam_api_key_configured ? 'Configured' : 'Not Set'}
                </span>
              </div>
              <input 
                type="text" 
                value={credentials?.sarvam_api_key_masked || '••••••••••••••••'} 
                readOnly
                className="w-full bg-zinc-50 border border-zinc-200 rounded-lg px-3.5 py-2 text-zinc-700 font-mono"
              />
            </div>

            <div>
              <div className="flex justify-between items-center mb-1">
                <label className="text-zinc-700 font-semibold">OpenAI API Secret Key</label>
                <span className={`text-[10px] font-sans px-2 py-0.5 rounded ${credentials?.openai_api_key_configured ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-amber-50 text-amber-700 border border-amber-200'}`}>
                  {credentials?.openai_api_key_configured ? 'Configured' : 'Not Set'}
                </span>
              </div>
              <input 
                type="text" 
                value={credentials?.openai_api_key_masked || '••••••••••••••••'} 
                readOnly
                className="w-full bg-zinc-50 border border-zinc-200 rounded-lg px-3.5 py-2 text-zinc-700 font-mono"
              />
            </div>

            <div>
              <div className="flex justify-between items-center mb-1">
                <label className="text-zinc-700 font-semibold">Anthropic API Secret Key</label>
                <span className={`text-[10px] font-sans px-2 py-0.5 rounded ${credentials?.anthropic_api_key_configured ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-amber-50 text-amber-700 border border-amber-200'}`}>
                  {credentials?.anthropic_api_key_configured ? 'Configured' : 'Not Set'}
                </span>
              </div>
              <input 
                type="text" 
                value={credentials?.anthropic_api_key_masked || '••••••••••••••••'} 
                readOnly
                className="w-full bg-zinc-50 border border-zinc-200 rounded-lg px-3.5 py-2 text-zinc-700 font-mono"
              />
            </div>
          </div>
        )}

        <div className="border-t border-zinc-100 pt-4 flex items-center justify-between text-xs text-zinc-500">
          <span className="flex items-center gap-1">
            <ShieldCheck className="w-4 h-4 text-emerald-600" />
            Keys must be rotated via AWS Secrets Manager or secure runtime environment variables.
          </span>
        </div>
      </div>
    </div>
  );
}

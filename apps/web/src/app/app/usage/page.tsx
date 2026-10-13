'use client';
import React, { useState, useEffect } from 'react';
import { Cpu, Zap, TrendingUp, DollarSign, Loader2 } from 'lucide-react';
import { authFetch, getCurrentSession } from '@/lib/api';

export default function AppUsagePage() {
  const [usage, setUsage] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadUsage() {
      setLoading(true);
      try {
        const sess = await getCurrentSession();
        if (sess?.organization_id) {
          const res = await authFetch(`/api/v1/usage?organization_id=${sess.organization_id}`);
          if (res.ok) {
            const data = await res.json();
            setUsage(data);
          }
        }
      } catch (err) {
        console.error("Error loading usage:", err);
      } finally {
        setLoading(false);
      }
    }
    loadUsage();
  }, []);

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="border-b border-zinc-200 pb-6">
        <h1 className="text-2xl font-bold text-zinc-900">Organization Usage Metering</h1>
        <p className="text-xs text-zinc-500 mt-1">Track token consumption, voice gateway minutes, and dynamic tool calls per property and agent.</p>
      </div>

      {loading ? (
        <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
          <Loader2 className="w-8 h-8 animate-spin text-zinc-700" />
          <p className="text-xs">Loading usage metrics...</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono">
          <div className="yc-card p-5">
            <div className="flex items-center justify-between text-zinc-500 mb-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider">Total LLM Tokens Consumed</span>
              <Cpu className="w-4 h-4 text-zinc-600" />
            </div>
            <div className="text-2xl font-bold text-zinc-900">{(usage?.total_tokens || 0).toLocaleString()} Tokens</div>
            <p className="text-xs text-emerald-600 mt-1.5 font-semibold font-sans">Live Metered Usage</p>
          </div>

          <div className="yc-card p-5">
            <div className="flex items-center justify-between text-zinc-500 mb-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider">Voice Gateway</span>
              <Zap className="w-4 h-4 text-zinc-600" />
            </div>
            <div className="text-2xl font-bold text-zinc-900">{usage?.voice_minutes || 0} Mins</div>
            <p className="text-xs text-zinc-500 mt-1.5 font-sans">STT / TTS Synthesis</p>
          </div>

          <div className="yc-card p-5">
            <div className="flex items-center justify-between text-zinc-500 mb-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider">Estimated AI Cost</span>
              <DollarSign className="w-4 h-4 text-zinc-600" />
            </div>
            <div className="text-2xl font-bold text-zinc-900">${(usage?.estimated_cost || 0).toFixed(4)}</div>
            <p className="text-xs text-zinc-500 mt-1.5 font-sans">Metered infrastructure cost</p>
          </div>
        </div>
      )}
    </div>
  );
}

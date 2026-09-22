'use client';
import React, { useState, useEffect } from 'react';
import { Cpu, Zap, TrendingUp, DollarSign } from 'lucide-react';
import { API_BASE } from '@/lib/api';

export default function AppUsagePage() {
  const [usage, setUsage] = useState<any>({ total_tokens: 0, estimated_cost: 0 });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadUsage() {
      try {
        const res = await fetch(`${API_BASE}/api/v1/usage?organization_id=org_azure_group`);
        if (res.ok) {
          const data = await res.json();
          setUsage(data);
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
        <div className="py-12 text-center text-xs text-zinc-400">Loading usage metering...</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 font-mono">
          <div className="yc-card p-5">
            <div className="flex items-center justify-between text-zinc-500 mb-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider">Total LLM Tokens Consumed</span>
              <Cpu className="w-4 h-4 text-zinc-600" />
            </div>
            <div className="text-2xl font-bold text-zinc-900">{usage.total_tokens || 0} Tokens</div>
            <p className="text-xs text-emerald-600 mt-1.5 font-semibold">Live Billing Metering</p>
          </div>

          <div className="yc-card p-5">
            <div className="flex items-center justify-between text-zinc-500 mb-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider">Voice Minutes Consumed</span>
              <Zap className="w-4 h-4 text-zinc-600" />
            </div>
            <div className="text-2xl font-bold text-zinc-900">Sarvam STT/TTS</div>
            <p className="text-xs text-zinc-500 mt-1.5">Malayalam, Hindi, Tamil, Telugu, Kannada</p>
          </div>

          <div className="yc-card p-5">
            <div className="flex items-center justify-between text-zinc-500 mb-2">
              <span className="text-[11px] font-semibold uppercase tracking-wider">Estimated AI Cost</span>
              <DollarSign className="w-4 h-4 text-zinc-600" />
            </div>
            <div className="text-2xl font-bold text-zinc-900">${(usage.estimated_cost || 0).toFixed(4)}</div>
            <p className="text-xs text-zinc-500 mt-1.5">Included in Business Plan</p>
          </div>
        </div>
      )}
    </div>
  );
}

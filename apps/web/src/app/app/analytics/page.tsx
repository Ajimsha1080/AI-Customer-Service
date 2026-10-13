'use client';
import React, { useState, useEffect } from 'react';
import { BarChart3, TrendingUp, DollarSign, MessageSquare, ShieldCheck, UserCheck, Loader2 } from 'lucide-react';
import { authFetch, getCurrentSession } from '@/lib/api';

export default function AppAnalyticsPage() {
  const [analytics, setAnalytics] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadAnalytics() {
      setLoading(true);
      try {
        const sess = await getCurrentSession();
        if (sess?.organization_id) {
          const res = await authFetch(`/api/v1/analytics?organization_id=${sess.organization_id}`);
          if (res.ok) {
            const data = await res.json();
            setAnalytics(data);
          }
        }
      } catch (err) {
        console.error("Error loading analytics:", err);
      } finally {
        setLoading(false);
      }
    }
    loadAnalytics();
  }, []);

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="flex items-center justify-between border-b border-zinc-200 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Operational Analytics & Outcomes</h1>
          <p className="text-xs text-zinc-500 mt-1">Real-time automation support volume, guest resolution rates, and metered cost telemetry.</p>
        </div>

        <div className="flex gap-2 text-xs font-mono">
          <span className="px-3 py-1.5 bg-zinc-50 border border-zinc-200 rounded-lg text-zinc-700 font-semibold">
            Live Database Metrics
          </span>
        </div>
      </div>

      {loading ? (
        <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
          <Loader2 className="w-8 h-8 animate-spin text-zinc-700" />
          <p className="text-xs">Computing real operational analytics...</p>
        </div>
      ) : !analytics ? (
        <div className="yc-card p-12 text-center text-xs text-zinc-500">
          No analytics data available for this tenant.
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div className="yc-card p-5">
              <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider block mb-2 font-mono">Total Conversations</span>
              <div className="text-2xl font-bold text-zinc-900 font-mono">{analytics.total_conversations || 0}</div>
              <p className="text-xs text-zinc-500 mt-1 font-medium">Recorded in session database</p>
            </div>

            <div className="yc-card p-5">
              <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider block mb-2 font-mono">AI Resolution Rate</span>
              <div className="text-2xl font-bold text-zinc-900 font-mono">{analytics.ai_resolution_rate || '0.0%'}</div>
              <p className="text-xs text-zinc-500 mt-1">{analytics.human_escalation_rate || '0.0%'} Human Escalations</p>
            </div>

            <div className="yc-card p-5">
              <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider block mb-2 font-mono">Avg Response Latency</span>
              <div className="text-2xl font-bold text-zinc-900 font-mono">{analytics.average_response_time_ms || 0} ms</div>
              <p className="text-xs text-zinc-500 mt-1">End-to-end turn latency</p>
            </div>

            <div className="yc-card p-5">
              <span className="text-[11px] font-semibold text-zinc-500 uppercase tracking-wider block mb-2 font-mono">Estimated Inference Cost</span>
              <div className="text-2xl font-bold text-zinc-900 font-mono">${(analytics.total_cost_usd || 0).toFixed(4)}</div>
              <p className="text-xs text-zinc-500 mt-1">{analytics.total_usage_events || 0} usage events recorded</p>
            </div>
          </div>

          {/* Channel Breakdown */}
          {analytics.top_channels && Object.keys(analytics.top_channels).length > 0 && (
            <div className="yc-card p-6">
              <h2 className="text-sm font-bold text-zinc-900 mb-4">Traffic Channel Split</h2>
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                {Object.entries(analytics.top_channels).map(([ch, pct]) => (
                  <div key={ch} className="p-4 bg-zinc-50 rounded-xl border border-zinc-200">
                    <span className="text-[10px] font-mono font-bold uppercase text-zinc-500">{ch}</span>
                    <div className="text-xl font-bold font-mono text-zinc-900 mt-1">{String(pct)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

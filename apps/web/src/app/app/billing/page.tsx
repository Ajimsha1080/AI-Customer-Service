'use client';
import React, { useState, useEffect } from 'react';
import { CreditCard, CheckCircle2, DollarSign, Loader2, Sparkles } from 'lucide-react';
import { authFetch, getCurrentSession } from '@/lib/api';

export default function AppBillingPage() {
  const [loading, setLoading] = useState(true);
  const [upgrading, setUpgrading] = useState(false);
  const [subscription, setSubscription] = useState<any>(null);
  const [usage, setUsage] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchSubscriptionData() {
      setLoading(true);
      try {
        const res = await authFetch('/api/v1/billing/subscription');
        if (res.ok) {
          const data = await res.json();
          if (data.subscription) setSubscription(data.subscription);
          if (data.usage_summary) setUsage(data.usage_summary);
        } else {
          setError('Failed to fetch subscription data');
        }
      } catch (err: any) {
        setError(err.message || 'Billing service unreachable');
      } finally {
        setLoading(false);
      }
    }
    fetchSubscriptionData();
  }, []);

  const handleStripeCheckout = async (targetPlan: string) => {
    setUpgrading(true);
    try {
      const res = await authFetch('/api/v1/billing/checkout-session', {
        method: 'POST',
        body: JSON.stringify({
          plan_name: targetPlan,
          success_url: window.location.href + '?session=success',
          cancel_url: window.location.href + '?session=cancel'
        })
      });

      if (res.ok) {
        const data = await res.json();
        if (data.checkout_url) {
          window.location.href = data.checkout_url;
        }
      }
    } catch (err) {
      console.error('Checkout error:', err);
    } finally {
      setUpgrading(false);
    }
  };

  const planName = subscription?.plan_name || 'FREE';
  const monthlyPrice = subscription?.monthly_price !== undefined ? subscription.monthly_price : 0;
  const maxConvs = subscription?.max_conversations_per_month || 100;
  const maxAgents = subscription?.max_agents || 1;
  const totalConvs = usage?.total_conversations || 0;
  const activeAgents = usage?.active_agents || 0;

  return (
    <div className="max-w-4xl mx-auto space-y-8 font-sans">
      <div className="border-b border-zinc-200 pb-6">
        <h1 className="text-2xl font-bold text-zinc-900">Subscription & Metered Billing</h1>
        <p className="text-xs text-zinc-500 mt-1">Manage your enterprise tier, limits, and real-time usage telemetry.</p>
      </div>

      {loading ? (
        <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
          <Loader2 className="w-8 h-8 animate-spin text-zinc-700" />
          <p className="text-xs">Loading subscription details...</p>
        </div>
      ) : (
        <>
          {/* Active Plan Card */}
          <div className="yc-card p-6 border-l-4 border-l-zinc-900 space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <span className="text-[10px] font-mono font-bold tracking-wider text-zinc-400 uppercase">ACTIVE SUBSCRIPTION</span>
                <h2 className="text-xl font-bold text-zinc-900 mt-0.5">{planName} TIER</h2>
              </div>
              <div className="text-right">
                <div className="text-2xl font-bold text-zinc-900 font-mono">${monthlyPrice}</div>
                <span className="text-[10px] text-zinc-400">/ month billing</span>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-4 pt-4 border-t border-zinc-100">
              <div>
                <span className="text-[11px] text-zinc-500 block">Conversations Limit</span>
                <span className="text-sm font-bold text-zinc-900 font-mono">
                  {totalConvs} / {maxConvs} used
                </span>
                <div className="w-full bg-zinc-100 h-1.5 rounded-full mt-2 overflow-hidden">
                  <div 
                    className="bg-zinc-900 h-full rounded-full transition-all" 
                    style={{ width: `${Math.min(100, Math.round((totalConvs / Math.max(1, maxConvs)) * 100))}%` }} 
                  />
                </div>
              </div>
              <div>
                <span className="text-[11px] text-zinc-500 block">AI Concierges Provisioned</span>
                <span className="text-sm font-bold text-zinc-900 font-mono">
                  {activeAgents} / {maxAgents}
                </span>
                <div className="w-full bg-zinc-100 h-1.5 rounded-full mt-2 overflow-hidden">
                  <div 
                    className="bg-zinc-900 h-full rounded-full transition-all" 
                    style={{ width: `${Math.min(100, Math.round((activeAgents / Math.max(1, maxAgents)) * 100))}%` }} 
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Upgrade Options */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 pt-2">
            {[
              { name: 'STARTER', price: 99, convs: '1,000 turns', agents: '2 Agents' },
              { name: 'PROFESSIONAL', price: 249, convs: '10,000 turns', agents: '5 Agents' },
              { name: 'BUSINESS', price: 499, convs: '50,000 turns', agents: '15 Agents' }
            ].map((p) => {
              const isCurrent = planName.toUpperCase() === p.name;
              return (
                <div key={p.name} className={`yc-card p-5 space-y-4 flex flex-col justify-between ${isCurrent ? 'ring-2 ring-zinc-900' : ''}`}>
                  <div>
                    <div className="flex items-center justify-between mb-2">
                      <h3 className="font-bold text-sm text-zinc-900">{p.name}</h3>
                      {isCurrent && <span className="text-[10px] font-bold text-emerald-600">● Current</span>}
                    </div>
                    <div className="text-xl font-bold font-mono text-zinc-900">${p.price}<span className="text-xs text-zinc-400 font-normal">/mo</span></div>
                    <ul className="mt-3 space-y-1.5 text-xs text-zinc-600">
                      <li className="flex items-center gap-1.5">✓ {p.convs}</li>
                      <li className="flex items-center gap-1.5">✓ {p.agents}</li>
                      <li className="flex items-center gap-1.5">✓ Real-time RAG & PGVector</li>
                    </ul>
                  </div>

                  <button
                    disabled={isCurrent || upgrading}
                    onClick={() => handleStripeCheckout(p.name)}
                    className={`w-full py-2 rounded-lg text-xs font-semibold transition ${
                      isCurrent 
                        ? 'bg-zinc-100 text-zinc-400 cursor-default' 
                        : 'bg-zinc-900 hover:bg-zinc-800 text-white'
                    }`}
                  >
                    {isCurrent ? 'Current Plan' : upgrading ? 'Redirecting...' : `Upgrade to ${p.name}`}
                  </button>
                </div>
              );
            })}
          </div>
        </>
      )}
    </div>
  );
}

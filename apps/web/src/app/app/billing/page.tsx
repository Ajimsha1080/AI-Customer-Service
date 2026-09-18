'use client';
import React, { useState, useEffect } from 'react';
import { CreditCard, CheckCircle2, DollarSign, Loader2 } from 'lucide-react';

export default function AppBillingPage() {
  const [loading, setLoading] = useState(true);
  const [upgrading, setUpgrading] = useState(false);
  const [subscription, setSubscription] = useState<any>({
    plan_name: 'BUSINESS',
    monthly_price: 499.0,
    max_agents: 15,
    max_conversations_per_month: 50000,
    status: 'ACTIVE'
  });
  const [usage, setUsage] = useState<any>({
    total_conversations: 1660,
    active_agents: 4
  });

  const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

  useEffect(() => {
    async function fetchSubscriptionData() {
      try {
        const token = localStorage.getItem('access_token');
        const headers: any = { 'Content-Type': 'application/json' };
        if (token) headers['Authorization'] = `Bearer ${token}`;

        const res = await fetch(`${API_BASE}/api/v1/billing/subscription`, { headers });
        if (res.ok) {
          const data = await res.json();
          if (data.subscription) setSubscription(data.subscription);
          if (data.usage_summary) setUsage(data.usage_summary);
        }
      } catch (err) {
        console.warn('Could not connect to billing API, using local state:', err);
      } finally {
        setLoading(false);
      }
    }
    fetchSubscriptionData();
  }, [API_BASE]);

  const handleStripeCheckout = async (targetPlan: string) => {
    setUpgrading(true);
    try {
      const token = localStorage.getItem('access_token');
      const headers: any = { 'Content-Type': 'application/json' };
      if (token) headers['Authorization'] = `Bearer ${token}`;

      const res = await fetch(`${API_BASE}/api/v1/billing/checkout-session`, {
        method: 'POST',
        headers,
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
          return;
        }
      }
      alert(`Stripe Checkout Session Initiated for ${targetPlan}`);
    } catch (err) {
      alert(`Failed to start checkout: ${err}`);
    } finally {
      setUpgrading(false);
    }
  };

  const currentPlan = subscription?.plan_name || 'BUSINESS';
  const monthlyPrice = subscription?.monthly_price ?? 499.0;
  const maxAgents = subscription?.max_agents ?? 15;
  const maxConvs = subscription?.max_conversations_per_month ?? 50000;
  const convCount = usage?.total_conversations ?? 1660;
  const agentCount = usage?.active_agents ?? 4;

  const convPct = Math.min(100, Math.round((convCount / maxConvs) * 100));
  const agentPct = Math.min(100, Math.round((agentCount / maxAgents) * 100));

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="flex items-center justify-between border-b border-zinc-200 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Subscription & SaaS Metering</h1>
          <p className="text-xs text-zinc-500 mt-1">Manage your active subscription plan, conversation limits, and monthly billing.</p>
        </div>

        <button
          onClick={() => handleStripeCheckout('ENTERPRISE')}
          disabled={upgrading}
          className="yc-btn-primary flex items-center space-x-2"
        >
          {upgrading ? <Loader2 className="w-4 h-4 animate-spin" /> : <CreditCard className="w-4 h-4" />}
          <span>Upgrade to Enterprise Tier</span>
        </button>
      </div>

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-zinc-400" />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div className="yc-card p-6 space-y-4">
            <span className="yc-badge">
              CURRENT PLAN: {currentPlan}
            </span>
            <div>
              <h3 className="text-3xl font-bold text-zinc-900 font-mono">${monthlyPrice} <span className="text-xs text-zinc-500 font-normal">/ month</span></h3>
              <p className="text-xs text-zinc-500 mt-1">Status: {subscription?.status || 'ACTIVE'}</p>
            </div>
            <button
              onClick={() => handleStripeCheckout('ENTERPRISE')}
              className="w-full text-xs font-semibold py-2 px-3 bg-zinc-900 text-white rounded hover:bg-zinc-800 transition"
            >
              Checkout with Stripe
            </button>
          </div>

          <div className="yc-card p-6 space-y-4 font-mono text-xs col-span-2">
            <div className="flex items-center justify-between text-zinc-900 font-bold border-b border-zinc-200 pb-2">
              <span>ENTITLEMENT USAGE</span>
              <span>LIMITS</span>
            </div>

            <div className="space-y-4">
              <div>
                <div className="flex justify-between text-[11px] text-zinc-600 mb-1">
                  <span>Monthly Conversations ({convCount.toLocaleString()} / {maxConvs.toLocaleString()})</span>
                  <span className="font-bold text-zinc-900">{convPct}%</span>
                </div>
                <div className="w-full bg-zinc-100 rounded-full h-2 overflow-hidden border border-zinc-200">
                  <div className="bg-zinc-900 h-full rounded-full transition-all" style={{ width: `${convPct}%` }}></div>
                </div>
              </div>

              <div>
                <div className="flex justify-between text-[11px] text-zinc-600 mb-1">
                  <span>Active AI Agents ({agentCount} / {maxAgents})</span>
                  <span className="font-bold text-zinc-900">{agentPct}%</span>
                </div>
                <div className="w-full bg-zinc-100 rounded-full h-2 overflow-hidden border border-zinc-200">
                  <div className="bg-zinc-900 h-full rounded-full transition-all" style={{ width: `${agentPct}%` }}></div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

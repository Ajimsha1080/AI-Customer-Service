'use client';
import React from 'react';
import { CheckCircle2 } from 'lucide-react';

export default function PlatformSubscriptionsPage() {
  const plans = [
    { name: 'FREE', price: '$0/mo', agents: 1, properties: 1, convs: '100/mo', voice: 'Disabled' },
    { name: 'STARTER', price: '$49/mo', agents: 2, properties: 1, convs: '1,000/mo', voice: 'Disabled' },
    { name: 'PROFESSIONAL', price: '$199/mo', agents: 5, properties: 2, convs: '10,000/mo', voice: 'Enabled' },
    { name: 'BUSINESS', price: '$499/mo', agents: 15, properties: 5, convs: '50,000/mo', voice: 'Enabled' },
    { name: 'ENTERPRISE', price: '$1,999/mo', agents: 'Unlimited', properties: 'Unlimited', convs: 'Unlimited', voice: 'Enabled' }
  ];

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="border-b border-zinc-200 pb-6">
        <h1 className="text-2xl font-bold text-zinc-900">SaaS Subscription Plans & Entitlements</h1>
        <p className="text-xs text-zinc-500 mt-1">Global subscription tiers, conversation caps, agent limits, and pricing synced with backend PLAN_LIMITS.</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-5 gap-4">
        {plans.map(p => (
          <div key={p.name} className="yc-card p-5 flex flex-col justify-between">
            <div>
              <span className="yc-badge">
                {p.name}
              </span>
              <h3 className="text-2xl font-bold text-zinc-900 mt-4 font-mono">{p.price}</h3>
              <ul className="mt-5 space-y-2 text-xs text-zinc-700 font-medium">
                <li className="flex items-center gap-2"><CheckCircle2 className="w-3.5 h-3.5 text-zinc-600" /> Max {p.agents} Agents</li>
                <li className="flex items-center gap-2"><CheckCircle2 className="w-3.5 h-3.5 text-zinc-600" /> Max {p.properties} Properties</li>
                <li className="flex items-center gap-2"><CheckCircle2 className="w-3.5 h-3.5 text-zinc-600" /> {p.convs} Conversations</li>
                <li className="flex items-center gap-2"><CheckCircle2 className="w-3.5 h-3.5 text-zinc-600" /> Voice Gateway: {p.voice}</li>
              </ul>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

'use client';
import React from 'react';
import Link from 'next/link';
import { ArrowLeft, FileText, CheckCircle2, ShieldAlert, Scale } from 'lucide-react';

export default function TermsOfServicePage() {
  return (
    <div className="min-h-screen bg-zinc-50 text-zinc-900 font-sans selection:bg-zinc-200">
      <header className="border-b border-zinc-200 bg-white sticky top-0 z-40 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Link href="/" className="flex items-center gap-2 text-zinc-500 hover:text-zinc-900 transition-colors text-xs font-medium mr-2">
              <ArrowLeft className="w-3.5 h-3.5" />
              <span>Back</span>
            </Link>
            <div className="w-8 h-8 rounded-lg bg-zinc-900 flex items-center justify-center font-bold text-white text-sm">
              H
            </div>
            <div>
              <h1 className="font-bold text-sm text-zinc-900 leading-none">Hospitality Agent Cloud</h1>
              <p className="text-[11px] text-zinc-500 font-mono mt-0.5">SaaS Terms of Service</p>
            </div>
          </div>
          <div className="flex items-center gap-4 text-xs font-medium text-zinc-600">
            <Link href="/privacy" className="hover:text-zinc-900">Privacy</Link>
            <Link href="/status" className="hover:text-zinc-900">Status</Link>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-12 space-y-10">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-zinc-100 border border-zinc-200 text-zinc-800 text-xs font-medium">
            <Scale className="w-3.5 h-3.5" />
            <span>Customer Agreement</span>
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-zinc-900">
            Terms of Service
          </h1>
          <p className="text-xs text-zinc-500 font-mono">
            Last Updated: September 18, 2026 • Version 1.0.0
          </p>
        </div>

        <div className="space-y-8 bg-white p-8 rounded-2xl border border-zinc-200 shadow-xs leading-relaxed text-sm text-zinc-700">
          <section className="space-y-3">
            <p>
              Welcome to <strong>Hospitality Agent Cloud</strong> ("Platform", "we", "us", or "our"). By creating an account, subscribing to our services, or deploying AI digital concierges, you ("Customer", "Subscriber") agree to be bound by these Terms of Service ("Terms").
            </p>
          </section>

          <hr className="border-zinc-200" />

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-zinc-900 flex items-center gap-2">
              <FileText className="w-4 h-4 text-zinc-700" />
              1. Description of Service
            </h2>
            <p>
              Hospitality Agent Cloud provides multi-tenant Agent-as-a-Service (AaaS) software enabling hospitality businesses (resorts, hotels, hostels, serviced apartments) to deploy AI digital concierges, booking assistants, and guest communication tools across web, WhatsApp, and voice channels.
            </p>
          </section>

          <hr className="border-zinc-200" />

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-zinc-900 flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-zinc-700" />
              2. Subscription, Billing & Quotas
            </h2>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-600">
              <li><strong>Tiers & Usage Limits:</strong> Subscriptions are billed on a recurring monthly or annual basis (<code className="bg-zinc-100 px-1 py-0.5 rounded text-xs font-mono">FREE</code>, <code className="bg-zinc-100 px-1 py-0.5 rounded text-xs font-mono">STARTER</code>, <code className="bg-zinc-100 px-1 py-0.5 rounded text-xs font-mono">PROFESSIONAL</code>, <code className="bg-zinc-100 px-1 py-0.5 rounded text-xs font-mono">BUSINESS</code>, <code className="bg-zinc-100 px-1 py-0.5 rounded text-xs font-mono">ENTERPRISE</code>). Entitlements for active agents, monthly conversation turns, and document uploads are strictly enforced. Exceeding tier quotas returns <code className="bg-zinc-100 px-1 py-0.5 rounded text-xs font-mono">HTTP 402 Payment Required</code>.</li>
              <li><strong>Payment Processing:</strong> Payments are processed securely via Stripe. Failure to pay after a 7-day grace period results in account suspension and tier downgrade.</li>
            </ul>
          </section>

          <hr className="border-zinc-200" />

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-zinc-900 flex items-center gap-2">
              <ShieldAlert className="w-4 h-4 text-zinc-700" />
              3. Customer Data & Acceptable Use
            </h2>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-600">
              <li><strong>Ownership:</strong> Customer retains all rights and ownership of uploaded property data, guest guides, menus, and reservation records.</li>
              <li><strong>Prohibited Conduct:</strong> Customer shall not upload malicious code, prompt injection attacks, unlawful content, or use AI agents to impersonate human staff without mandatory disclosure under applicable law.</li>
            </ul>
          </section>

          <hr className="border-zinc-200" />

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-zinc-900">
              4. Limitation of Liability
            </h2>
            <p>
              Hospitality Agent Cloud is provided "AS IS" without warranties of uninterrupted operation. Maximum aggregate liability is capped at the total fees paid by Customer in the 12 months preceding the claim.
            </p>
          </section>
        </div>
      </main>
    </div>
  );
}

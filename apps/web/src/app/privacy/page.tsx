'use client';
import React from 'react';
import Link from 'next/link';
import { ArrowLeft, Shield, Globe, Lock, FileText } from 'lucide-react';

export default function PrivacyPolicyPage() {
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
              <p className="text-[11px] text-zinc-500 font-mono mt-0.5">Privacy Policy & Compliance</p>
            </div>
          </div>
          <div className="flex items-center gap-4 text-xs font-medium text-zinc-600">
            <Link href="/terms" className="hover:text-zinc-900">Terms</Link>
            <Link href="/status" className="hover:text-zinc-900">Status</Link>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-6 py-12 space-y-10">
        <div className="space-y-3">
          <div className="inline-flex items-center gap-2 px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-emerald-800 text-xs font-medium">
            <Shield className="w-3.5 h-3.5" />
            <span>DPDP Act 2023 & GDPR Compliant</span>
          </div>
          <h1 className="text-3xl font-extrabold tracking-tight text-zinc-900">
            Privacy Policy & Data Protection Compliance
          </h1>
          <p className="text-xs text-zinc-500 font-mono">
            Last Updated: September 18, 2026 • Effective Date: Immediately
          </p>
        </div>

        <div className="space-y-8 bg-white p-8 rounded-2xl border border-zinc-200 shadow-xs leading-relaxed text-sm text-zinc-700">
          <section className="space-y-3">
            <h2 className="text-lg font-bold text-zinc-900 flex items-center gap-2">
              <Globe className="w-4 h-4 text-zinc-700" />
              1. Global Data Protection Overview
            </h2>
            <p>
              Hospitality Agent Cloud respects the privacy of our subscribers and guest end-users. This policy details our processing of Personally Identifiable Information (PII) under international regulations, specifically the <strong>Digital Personal Data Protection (DPDP) Act, 2023 (India)</strong> and the <strong>General Data Protection Regulation (GDPR - EU)</strong>.
            </p>
          </section>

          <hr className="border-zinc-200" />

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-zinc-900">
              2. DPDP Act 2023 (India) Compliance
            </h2>
            <p>
              Because Hospitality Agent Cloud processes Indic-language guest data (Malayalam, Hindi, Tamil, Telugu, Kannada) for hospitality properties operating in India:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-600">
              <li><strong>Data Fiduciary & Processor Roles:</strong> Hospitality properties act as Data Fiduciaries; Hospitality Agent Cloud acts as Data Processor.</li>
              <li><strong>Consent & Purpose Limitation:</strong> Guest data (name, phone number, chat transcripts, voice audio) is processed solely for assisting guest stays, bookings, and customer service.</li>
              <li><strong>Data Principal Rights:</strong> Guests retain rights to access, correction, and erasure of personal data upon request to the property.</li>
            </ul>
          </section>

          <hr className="border-zinc-200" />

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-zinc-900">
              3. GDPR (EU) Compliance
            </h2>
            <p>
              For European hospitality properties and EU guests:
            </p>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-600">
              <li><strong>Lawful Basis for Processing:</strong> Processing is necessary for the performance of hospitality booking contracts and legitimate business operations.</li>
              <li><strong>Data Export & Deletion:</strong> Tenant administrators can invoke <code className="bg-zinc-100 px-1 py-0.5 rounded text-xs font-mono">GET /api/v1/organizations/:id/export-data</code> and <code className="bg-zinc-100 px-1 py-0.5 rounded text-xs font-mono">DELETE /api/v1/organizations/:id/purge-data</code> at any time.</li>
              <li><strong>Sub-processors:</strong> Infrastructure sub-processors include AWS (Cloud hosting/RDS), Stripe (Payment processing), and Sarvam AI / OpenAI (AI model execution).</li>
            </ul>
          </section>

          <hr className="border-zinc-200" />

          <section className="space-y-3">
            <h2 className="text-lg font-bold text-zinc-900 flex items-center gap-2">
              <Lock className="w-4 h-4 text-zinc-700" />
              4. Security Standards & Safeguards
            </h2>
            <ul className="list-disc pl-5 space-y-1.5 text-zinc-600">
              <li><strong>Encryption in Transit:</strong> TLS 1.3 across all REST APIs, SSE streams, and webhooks.</li>
              <li><strong>Encryption at Rest:</strong> AES-256 for PostgreSQL database volumes and vector stores; Fernet AES-128-CBC for third-party integration secrets.</li>
              <li><strong>Tenant Isolation:</strong> PostgreSQL Row-Level Security (RLS) guarantees strictly partitioned multi-tenant memory and storage isolation.</li>
            </ul>
          </section>
        </div>
      </main>
    </div>
  );
}

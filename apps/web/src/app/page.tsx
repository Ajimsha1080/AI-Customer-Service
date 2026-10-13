'use client';
import React from 'react';
import Link from 'next/link';

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-white text-zinc-900 flex flex-col font-sans selection:bg-zinc-200">
      {/* Header Navigation */}
      <header className="border-b border-zinc-200 bg-white/90 backdrop-blur-md sticky top-0 z-50 px-8 py-4 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-zinc-900 flex items-center justify-center font-bold text-white text-xl shadow-xs">
            H
          </div>
          <div>
            <h1 className="font-bold text-lg text-zinc-900 tracking-tight">
              Hospitality Agent Cloud
            </h1>
            <p className="text-xs text-zinc-500 font-mono font-medium">Enterprise Agent-as-a-Service (AaaS)</p>
          </div>
        </div>
        <div className="flex items-center gap-6 text-sm font-medium text-zinc-600">
          <Link href="/app/dashboard" className="hover:text-zinc-900 transition-colors">SaaS Portal</Link>
          <Link href="/platform/dashboard" className="hover:text-zinc-900 transition-colors">Super Admin</Link>
          <Link href="/status" className="hover:text-zinc-900 transition-colors">Status</Link>
          <Link href="/guest/agt_concierge_01" className="hover:text-zinc-900 transition-colors">Guest Concierge</Link>
          <Link href="/app/dashboard" className="yc-btn-primary">
            Launch Main Portal →
          </Link>
        </div>
      </header>

      {/* Hero Section */}
      <main className="flex-1 max-w-7xl mx-auto px-8 py-20 flex flex-col items-center text-center">
        <div className="yc-badge mb-8">
          <span>✨ Enterprise Hospitality AI Runtimes</span>
          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
        </div>

        <h1 className="text-5xl md:text-6xl font-extrabold tracking-tight max-w-4xl leading-tight text-zinc-900">
          Deploy AI Hospitality Agents in Minutes.{' '}
          <span className="text-zinc-600 underline decoration-zinc-300 decoration-wavy">
            Zero Infrastructure Code.
          </span>
        </h1>

        <p className="mt-6 text-lg text-zinc-600 max-w-2xl leading-relaxed">
          The all-in-one Agent-as-a-Service SaaS platform for resorts, hotels, hostels, and vacation rentals. Fully managed RAG, Sarvam AI Indic voice receptionists, and dynamic live updates.
        </p>

        <div className="mt-10 flex items-center gap-4">
          <Link href="/app/agents" className="yc-btn-primary px-8 py-3.5 text-sm">
            Explore Predefined Agents
          </Link>
          <Link href="/guest/agt_concierge_01" className="yc-btn-secondary px-8 py-3.5 text-sm">
            Try Guest Concierge
          </Link>
        </div>

        {/* Feature Cards Grid */}
        <div className="mt-24 grid grid-cols-1 md:grid-cols-3 gap-8 text-left w-full">
          <div className="yc-card p-8">
            <div className="w-12 h-12 rounded-xl bg-zinc-100 border border-zinc-200 text-zinc-900 flex items-center justify-center text-2xl mb-6">
              🏨
            </div>
            <h3 className="text-xl font-bold text-zinc-900 mb-2">Multi-Tenant AaaS Architecture</h3>
            <p className="text-sm text-zinc-600 leading-relaxed">
              Create multiple organizations, properties, and specialized agents (Concierge, Booking, Support) with strict tenant isolation.
            </p>
          </div>

          <div className="yc-card p-8">
            <div className="w-12 h-12 rounded-xl bg-zinc-100 border border-zinc-200 text-zinc-900 flex items-center justify-center text-2xl mb-6">
              ⚡
            </div>
            <h3 className="text-xl font-bold text-zinc-900 mb-2">Real-Time Data Routing</h3>
            <p className="text-sm text-zinc-600 leading-relaxed">
              Dynamic tool routing for live pool status, current room pricing, today's activities, and instant property announcements to eliminate hallucinations.
            </p>
          </div>

          <div className="yc-card p-8">
            <div className="w-12 h-12 rounded-xl bg-zinc-100 border border-zinc-200 text-zinc-900 flex items-center justify-center text-2xl mb-6">
              🎙️
            </div>
            <h3 className="text-xl font-bold text-zinc-900 mb-2">Sarvam AI Indic Voice & Chat</h3>
            <p className="text-sm text-zinc-600 leading-relaxed">
              Multi-lingual browser voice (Malayalam, Hindi, Tamil, Telugu), embeddable web chat widgets connected to a real-time agent runtime engine.
            </p>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer className="border-t border-zinc-200 py-8 px-8 text-center text-xs text-zinc-500 font-mono">
        © 2026 Hospitality Agent Cloud Inc. Enterprise Agent-as-a-Service Platform. All rights reserved.
      </footer>
    </div>
  );
}

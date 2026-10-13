'use client';
import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Building2, Bot, Users, BarChart3, ArrowUpRight, TrendingUp, CheckCircle2,
  Clock, ShieldCheck, Zap, Plus, Sparkles, AlertCircle, Play, ChevronRight, BookOpen, Radio, MessageSquare, Wrench, Bell, Database
} from 'lucide-react';

export default function SaaSUserDashboard() {
  const [metrics, setMetrics] = useState<any>({ active_agents: 1, total_conversations: 42 });
  const [loading, setLoading] = useState(false);

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      {/* Top Banner / Welcome Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-zinc-200 pb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="yc-badge">HOSTEL: AZURE PALM HOSTEL & RESIDENCE</span>
            <span className="yc-badge-emerald">● REAL-TIME OPERATIONAL</span>
          </div>
          <h1 className="text-2xl font-bold text-zinc-900 tracking-tight">Hostel SaaS Admin Dashboard</h1>
          <p className="text-xs text-zinc-600 mt-1">Overview of AI assistant status, active residents, live information sync, open maintenance requests, and recent notices.</p>
        </div>

        <div className="flex items-center gap-3">
          <Link href="/app/live-updates" className="yc-btn-secondary flex items-center gap-1.5 text-xs">
            <Radio className="w-3.5 h-3.5 text-zinc-700" /> Live Information
          </Link>
          <Link href="/app/agents" className="yc-btn-primary flex items-center gap-1.5 text-xs">
            <Bot className="w-3.5 h-3.5" /> Hostel AI Assistant
          </Link>
        </div>
      </div>

      {/* Main 4 Metric Overview Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* 1. AI Assistant Status */}
        <div className="yc-card p-5 space-y-3">
          <div className="flex items-center justify-between text-zinc-500">
            <span className="text-[11px] font-semibold uppercase tracking-wider">AI Assistant Status</span>
            <Bot className="w-4 h-4 text-emerald-600" />
          </div>
          <div>
            <div className="text-xl font-bold text-zinc-900 flex items-center gap-2">
              Hostel AI Agent <span className="w-2.5 h-2.5 rounded-full bg-emerald-500 animate-pulse"></span>
            </div>
            <p className="text-[11px] text-emerald-600 font-medium mt-1">● Active & Online (4-Step Loop)</p>
          </div>
        </div>

        {/* 2. Active Residents */}
        <div className="yc-card p-5 space-y-3">
          <div className="flex items-center justify-between text-zinc-500">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Active Residents</span>
            <Users className="w-4 h-4 text-zinc-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-zinc-900 font-mono">148 Residents</div>
            <p className="text-[11px] text-zinc-500 mt-1">Registered across Blocks A, B & C</p>
          </div>
        </div>

        {/* 3. Knowledge Sources */}
        <div className="yc-card p-5 space-y-3">
          <div className="flex items-center justify-between text-zinc-500">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Knowledge Sources</span>
            <BookOpen className="w-4 h-4 text-zinc-400" />
          </div>
          <div>
            <div className="text-2xl font-bold text-zinc-900 font-mono">4 Indexed Docs</div>
            <p className="text-[11px] text-zinc-500 mt-1">Rules, FAQs, Policies & Guides</p>
          </div>
        </div>

        {/* 4. Live Information Status */}
        <div className="yc-card p-5 space-y-3">
          <div className="flex items-center justify-between text-zinc-500">
            <span className="text-[11px] font-semibold uppercase tracking-wider">Live Information Status</span>
            <Radio className="w-4 h-4 text-emerald-600" />
          </div>
          <div>
            <div className="text-lg font-bold text-zinc-900 font-mono">Mess Menu & Gate Synced</div>
            <p className="text-[11px] text-emerald-600 font-medium mt-1">● Campus ERP Sync Active</p>
          </div>
        </div>
      </div>

      {/* 2-Column Operational Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Open Requests Summary */}
        <div className="yc-card p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
            <h2 className="text-sm font-bold text-zinc-900 flex items-center gap-2">
              <Wrench className="w-4 h-4 text-amber-600" /> Open Maintenance & Complaints
            </h2>
            <Link href="/app/requests" className="text-xs font-semibold text-zinc-600 hover:text-zinc-900 flex items-center gap-1">
              View All <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="space-y-3 font-sans text-xs">
            <div className="p-3 bg-zinc-50 rounded-xl border border-zinc-200 flex items-center justify-between">
              <div>
                <div className="font-bold text-zinc-900">MNT-10492: Room Ceiling Fan Noise</div>
                <div className="text-[11px] text-zinc-500">Room 304 (Alex Johnson) • Dispatched to Electrical Staff</div>
              </div>
              <span className="px-2.5 py-1 rounded bg-amber-100 text-amber-800 text-[10px] font-mono font-bold">IN_PROGRESS</span>
            </div>

            <div className="p-3 bg-zinc-50 rounded-xl border border-zinc-200 flex items-center justify-between">
              <div>
                <div className="font-bold text-zinc-900">MNT-10493: Bathroom Tap Leakage</div>
                <div className="text-[11px] text-zinc-500">Room 212 (Rahul Verma) • Assigned to Plumbing Staff</div>
              </div>
              <span className="px-2.5 py-1 rounded bg-zinc-100 text-zinc-800 text-[10px] font-mono font-bold">DISPATCHED</span>
            </div>
          </div>
        </div>

        {/* Recent Notices Summary */}
        <div className="yc-card p-6 space-y-4">
          <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
            <h2 className="text-sm font-bold text-zinc-900 flex items-center gap-2">
              <Bell className="w-4 h-4 text-emerald-600" /> Recent Notices
            </h2>
            <Link href="/app/live-updates" className="text-xs font-semibold text-zinc-600 hover:text-zinc-900 flex items-center gap-1">
              Manage Notices <ChevronRight className="w-3.5 h-3.5" />
            </Link>
          </div>

          <div className="space-y-3 font-sans text-xs">
            <div className="p-3 bg-zinc-50 rounded-xl border border-zinc-200 space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-bold text-zinc-900">Main Gate Night Entry Timings Update</span>
                <span className="px-2 py-0.5 rounded bg-red-100 text-red-800 text-[10px] font-mono font-bold">IMPORTANT</span>
              </div>
              <p className="text-[11px] text-zinc-600">Hostel main gate will close strictly at 10:00 PM starting tonight.</p>
            </div>

            <div className="p-3 bg-zinc-50 rounded-xl border border-zinc-200 space-y-1">
              <div className="flex items-center justify-between">
                <span className="font-bold text-zinc-900">Bi-Weekly Elevator Inspection Block A</span>
                <span className="yc-badge-emerald text-[10px]">ACTIVE</span>
              </div>
              <p className="text-[11px] text-zinc-600">Elevator 2 in Block A routine safety check tomorrow 2 PM - 4 PM.</p>
            </div>
          </div>
        </div>
      </div>

      {/* Recent Agent Activity Log */}
      <div className="yc-card p-6 space-y-4">
        <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
          <h2 className="text-sm font-bold text-zinc-900 flex items-center gap-2">
            <Bot className="w-4 h-4 text-zinc-700" /> Recent Hostel AI Agent Activity
          </h2>
          <span className="text-xs font-mono text-zinc-400">Live Telemetry</span>
        </div>

        <div className="space-y-2 text-xs font-mono">
          <div className="p-3 bg-zinc-50 rounded-xl border border-zinc-200 flex items-center justify-between">
            <span className="text-zinc-700 font-bold">Resident asked: &quot;What&apos;s for dinner today?&quot;</span>
            <span className="text-emerald-600 font-semibold">→ Queried Live Data (Menu &amp; Timings)</span>
            <span className="text-zinc-400 text-[11px]">2 mins ago</span>
          </div>

          <div className="p-3 bg-zinc-50 rounded-xl border border-zinc-200 flex items-center justify-between">
            <span className="text-zinc-700 font-bold">Resident asked: &quot;The fan in my room isn&apos;t working.&quot;</span>
            <span className="text-amber-600 font-semibold">→ Created Ticket MNT-10492</span>
            <span className="text-zinc-400 text-[11px]">15 mins ago</span>
          </div>

          <div className="p-3 bg-zinc-50 rounded-xl border border-zinc-200 flex items-center justify-between">
            <span className="text-zinc-700 font-bold">Resident asked: &quot;What are the visitor rules?&quot;</span>
            <span className="text-blue-600 font-semibold">→ Queried Knowledge RAG (Rules Doc)</span>
            <span className="text-zinc-400 text-[11px]">45 mins ago</span>
          </div>
        </div>
      </div>
    </div>
  );
}

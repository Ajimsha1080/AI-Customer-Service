'use client';
import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { 
  Building2, Bot, Users, BarChart3, ArrowUpRight, TrendingUp, CheckCircle2,
  Clock, ShieldCheck, Zap, Plus, Sparkles, AlertCircle, Play, ChevronRight, BookOpen, Radio, MessageSquare, Wrench, Bell, Database, Loader2
} from 'lucide-react';
import { authFetch, getCurrentSession } from '@/lib/api';

export default function SaaSUserDashboard() {
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<any>(null);
  const [counts, setCounts] = useState({
    agents: 0,
    residents: 0,
    documents: 0,
    tickets: 0,
    liveUpdates: 0
  });
  const [recentTickets, setRecentTickets] = useState<any[]>([]);
  const [recentNotices, setRecentNotices] = useState<any[]>([]);

  useEffect(() => {
    async function loadDashboard() {
      setLoading(true);
      try {
        const sess = await getCurrentSession();
        setSession(sess);
        const orgId = sess?.organization_id;

        if (orgId) {
          const [agentRes, docRes, ticketRes, noticeRes, resRes] = await Promise.all([
            authFetch(`/api/v1/agents?organization_id=${orgId}`).then(r => r.ok ? r.json() : []).catch(() => []),
            authFetch(`/api/v1/knowledge/documents?organization_id=${orgId}`).then(r => r.ok ? r.json() : []).catch(() => []),
            authFetch(`/api/v1/support-tickets?organization_id=${orgId}`).then(r => r.ok ? r.json() : []).catch(() => []),
            authFetch(`/api/v1/live-updates?organization_id=${orgId}`).then(r => r.ok ? r.json() : []).catch(() => []),
            authFetch(`/api/v1/residents?organization_id=${orgId}`).then(r => r.ok ? r.json() : []).catch(() => [])
          ]);

          setCounts({
            agents: Array.isArray(agentRes) ? agentRes.length : 0,
            documents: Array.isArray(docRes) ? docRes.length : 0,
            tickets: Array.isArray(ticketRes) ? ticketRes.length : 0,
            liveUpdates: Array.isArray(noticeRes) ? noticeRes.length : 0,
            residents: Array.isArray(resRes) ? resRes.length : 0
          });

          setRecentTickets(Array.isArray(ticketRes) ? ticketRes.slice(0, 5) : []);
          setRecentNotices(Array.isArray(noticeRes) ? noticeRes.slice(0, 5) : []);
        }
      } catch (err) {
        console.error('Failed to load dashboard:', err);
      } finally {
        setLoading(false);
      }
    }

    loadDashboard();
  }, []);

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      {/* Top Banner / Welcome Bar */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-zinc-200 pb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="yc-badge">ORG: {session?.organization_slug || session?.organization_id || 'WORKSPACE'}</span>
            <span className="yc-badge-emerald">● REAL-TIME OPERATIONAL</span>
          </div>
          <h1 className="text-2xl font-bold text-zinc-900 tracking-tight">Hospitality Operations Dashboard</h1>
          <p className="text-xs text-zinc-600 mt-1">Live overview of AI concierge agents, documents, residents, active tickets, and operational updates.</p>
        </div>

        <div className="flex items-center gap-3">
          <Link href="/app/live-updates" className="yc-btn-secondary flex items-center gap-1.5 text-xs">
            <Radio className="w-3.5 h-3.5 text-zinc-700" /> Live Updates
          </Link>
          <Link href="/app/agents" className="yc-btn-primary flex items-center gap-1.5 text-xs">
            <Bot className="w-3.5 h-3.5" /> AI Concierge
          </Link>
        </div>
      </div>

      {loading ? (
        <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
          <Loader2 className="w-8 h-8 animate-spin text-zinc-700" />
          <p className="text-xs">Loading operational workspace...</p>
        </div>
      ) : (
        <>
          {/* Main 4 Metric Overview Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {/* 1. AI Agents */}
            <div className="yc-card p-5 space-y-3">
              <div className="flex items-center justify-between text-zinc-500">
                <span className="text-[11px] font-semibold uppercase tracking-wider">AI Agents</span>
                <Bot className="w-4 h-4 text-emerald-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-zinc-900 font-mono">
                  {counts.agents} {counts.agents === 1 ? 'Agent' : 'Agents'}
                </div>
                <p className="text-[11px] text-emerald-600 font-medium mt-1">
                  {counts.agents > 0 ? '● Active & Ready' : '○ No agents created'}
                </p>
              </div>
            </div>

            {/* 2. Registered Guests / Residents */}
            <div className="yc-card p-5 space-y-3">
              <div className="flex items-center justify-between text-zinc-500">
                <span className="text-[11px] font-semibold uppercase tracking-wider">Guests / Residents</span>
                <Users className="w-4 h-4 text-zinc-400" />
              </div>
              <div>
                <div className="text-2xl font-bold text-zinc-900 font-mono">{counts.residents}</div>
                <p className="text-[11px] text-zinc-500 mt-1">Recorded in property database</p>
              </div>
            </div>

            {/* 3. Knowledge Base Documents */}
            <div className="yc-card p-5 space-y-3">
              <div className="flex items-center justify-between text-zinc-500">
                <span className="text-[11px] font-semibold uppercase tracking-wider">Knowledge Base</span>
                <BookOpen className="w-4 h-4 text-zinc-400" />
              </div>
              <div>
                <div className="text-2xl font-bold text-zinc-900 font-mono">{counts.documents} Docs</div>
                <p className="text-[11px] text-zinc-500 mt-1">Vectorized & available for RAG</p>
              </div>
            </div>

            {/* 4. Open Tickets */}
            <div className="yc-card p-5 space-y-3">
              <div className="flex items-center justify-between text-zinc-500">
                <span className="text-[11px] font-semibold uppercase tracking-wider">Support Tickets</span>
                <MessageSquare className="w-4 h-4 text-amber-600" />
              </div>
              <div>
                <div className="text-2xl font-bold text-zinc-900 font-mono">{counts.tickets}</div>
                <p className="text-[11px] text-amber-600 font-medium mt-1">Logged requests</p>
              </div>
            </div>
          </div>

          {/* 2-Column Operational Cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Open Requests Summary */}
            <div className="yc-card p-6 space-y-4">
              <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
                <h2 className="text-sm font-bold text-zinc-900 flex items-center gap-2">
                  <Wrench className="w-4 h-4 text-amber-600" /> Active Maintenance & Requests
                </h2>
                <Link href="/app/requests" className="text-xs font-semibold text-zinc-600 hover:text-zinc-900 flex items-center gap-1">
                  View All <ChevronRight className="w-3.5 h-3.5" />
                </Link>
              </div>

              {recentTickets.length === 0 ? (
                <div className="py-8 text-center text-xs text-zinc-500">
                  No active support tickets found.
                </div>
              ) : (
                <div className="space-y-3 font-sans text-xs">
                  {recentTickets.map((t) => (
                    <div key={t.id} className="p-3 bg-zinc-50 rounded-xl border border-zinc-200 flex items-center justify-between">
                      <div>
                        <div className="font-bold text-zinc-900">{t.id}: {t.issue_summary || t.category}</div>
                        <div className="text-[11px] text-zinc-500">
                          {t.room_number ? `Room ${t.room_number}` : 'General'} • {t.priority || 'NORMAL'}
                        </div>
                      </div>
                      <span className="px-2.5 py-1 rounded bg-amber-100 text-amber-800 text-[10px] font-mono font-bold">
                        {t.status || 'OPEN'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Recent Notices Summary */}
            <div className="yc-card p-6 space-y-4">
              <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
                <h2 className="text-sm font-bold text-zinc-900 flex items-center gap-2">
                  <Bell className="w-4 h-4 text-emerald-600" /> Live Notices & Announcements
                </h2>
                <Link href="/app/live-updates" className="text-xs font-semibold text-zinc-600 hover:text-zinc-900 flex items-center gap-1">
                  Manage Notices <ChevronRight className="w-3.5 h-3.5" />
                </Link>
              </div>

              {recentNotices.length === 0 ? (
                <div className="py-8 text-center text-xs text-zinc-500">
                  No live announcements posted.
                </div>
              ) : (
                <div className="space-y-3 font-sans text-xs">
                  {recentNotices.map((n) => (
                    <div key={n.id} className="p-3 bg-zinc-50 rounded-xl border border-zinc-200 flex items-center justify-between">
                      <div>
                        <div className="font-bold text-zinc-900">{n.title}</div>
                        <div className="text-[11px] text-zinc-500 line-clamp-1">{n.content}</div>
                      </div>
                      <span className="px-2.5 py-1 rounded bg-emerald-100 text-emerald-800 text-[10px] font-mono font-bold">
                        {n.priority || 'ACTIVE'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}

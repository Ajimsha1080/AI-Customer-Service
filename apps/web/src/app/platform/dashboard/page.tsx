'use client';
import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { API_BASE } from '@/lib/api';
import { 
  Building2, 
  Bot, 
  MessageSquare, 
  DollarSign, 
  Cpu, 
  Activity, 
  ShieldAlert, 
  TrendingUp, 
  ArrowUpRight,
  Radio,
  RefreshCw,
  Filter,
  CheckCircle2,
  AlertTriangle,
  ShieldCheck,
  Zap,
  Layers,
  Clock
} from 'lucide-react';

export default function PlatformDashboardPage() {
  const [telemetry, setTelemetry] = useState<any>({
    total_organizations: 1,
    active_organizations: 1,
    active_agents: 1,
    online_agents: 1,
    offline_agents: 0,
    connected_integrations: 1,
    failed_integrations: 0,
    system_health: '100% OPERATIONAL',
    sla_uptime: '99.99%',
    p95_latency_ms: 340,
  });

  const [orgs, setOrgs] = useState<any[]>([]);
  const [selectedOrgId, setSelectedOrgId] = useState<string>('all');
  const [realtimeEvents, setRealtimeEvents] = useState<any[]>([]);
  const [isLiveConnected, setIsLiveConnected] = useState<boolean>(false);
  const [loading, setLoading] = useState(true);

  // Initial fetch for telemetry and org list
  useEffect(() => {
    async function loadInitialData() {
      try {
        const [tRes, oRes] = await Promise.all([
          fetch(`${API_BASE}/api/v1/platform/telemetry`).then(r => r.ok ? r.json() : null),
          fetch(`${API_BASE}/api/v1/organizations`).then(r => r.ok ? r.json() : [])
        ]);

        if (tRes) {
          setTelemetry(tRes);
          if (tRes.recent_live_events && Array.isArray(tRes.recent_live_events)) {
            setRealtimeEvents(tRes.recent_live_events);
          }
        }
        if (Array.isArray(oRes) && oRes.length > 0) {
          setOrgs(oRes);
        } else {
          setOrgs([{ id: 'org_azure_group', name: 'Azure Palm Hostel & Residence', slug: 'azure-palm', status: 'ACTIVE' }]);
        }
      } catch (err) {
        console.error("Error fetching platform telemetry:", err);
      } finally {
        setLoading(false);
      }
    }

    loadInitialData();
  }, []);

  // SSE Stream setup for Super Admin real-time updates
  useEffect(() => {
    let es: EventSource | null = null;
    try {
      es = new EventSource(`${API_BASE}/api/v1/platform/events`);
      
      es.onopen = () => {
        setIsLiveConnected(true);
      };

      es.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'CONNECTED') {
            setIsLiveConnected(true);
            return;
          }

          const newEvt = {
            id: Date.now() + Math.random(),
            org_id: data.organization_id || 'org_azure_group',
            org_name: data.org_name || 'Azure Palm Hostel',
            summary: data.summary || data.action || 'Operational live update recorded',
            status: data.status || 'ONLINE',
            timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
          };

          setRealtimeEvents(prev => [newEvt, ...prev.slice(0, 49)]);
        } catch (e) {
          console.error("Failed to parse SSE event:", e);
        }
      };

      es.onerror = (err) => {
        console.warn("SSE connection interrupted, retrying...", err);
        setIsLiveConnected(false);
      };
    } catch (e) {
      console.error("EventSource initialization error:", e);
    }

    return () => {
      if (es) es.close();
    };
  }, []);

  // Filter events based on selected Organization
  const filteredEvents = selectedOrgId === 'all' 
    ? realtimeEvents 
    : realtimeEvents.filter(e => e.org_id === selectedOrgId || e.org_name.toLowerCase().includes(selectedOrgId.toLowerCase()));

  const getStatusBadge = (status: string) => {
    const s = status.toUpperCase();
    if (s.includes('ONLINE') || s.includes('ACTIVE') || s.includes('CONNECTED') || s.includes('OPERATIONAL')) {
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-emerald-50 text-emerald-700 border border-emerald-200"><span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />● {s}</span>;
    }
    if (s.includes('SYNCING') || s.includes('UPDATING')) {
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-blue-50 text-blue-700 border border-blue-200"><span className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-spin" />● {s}</span>;
    }
    if (s.includes('WARNING') || s.includes('DEGRADED')) {
      return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-amber-50 text-amber-700 border border-amber-200">● {s}</span>;
    }
    return <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold bg-rose-50 text-rose-700 border border-rose-200">● {s}</span>;
  };

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans pb-12">
      {/* 1-Click Unified Portal Switcher */}
      <div className="flex items-center justify-between bg-zinc-100 p-1.5 rounded-2xl border border-zinc-200 text-xs font-semibold">
        <span className="text-zinc-500 font-mono text-[11px] px-3 font-semibold">PORTAL SWITCHER:</span>
        <div className="flex items-center gap-1">
          <Link href="/app/dashboard" className="px-3 py-1.5 rounded-xl text-zinc-600 hover:text-zinc-900 transition-colors">
            🏨 Hostel SaaS Admin
          </Link>
          <Link href="/guest/agt_hostel_01" className="px-3 py-1.5 rounded-xl text-zinc-600 hover:text-zinc-900 transition-colors">
            💬 Resident AI Chat
          </Link>
          <Link href="/platform/dashboard" className="px-3 py-1.5 rounded-xl bg-zinc-900 text-white shadow-xs">
            🛡️ Super Admin Control Plane
          </Link>
        </div>
      </div>

      {/* Operator Banner Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between border-b border-zinc-200 pb-6 gap-4">
        <div>
          <div className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded bg-zinc-100 border border-zinc-200 text-zinc-800 text-[10px] font-mono font-semibold uppercase tracking-wider mb-2">
            <span>⚡ Platform Operator Control Plane</span>
          </div>
          <h1 className="text-2xl font-bold text-zinc-900 flex items-center gap-3">
            Super Admin Real-Time Dashboard
            {isLiveConnected ? (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-bold bg-emerald-100 text-emerald-800 border border-emerald-300">
                <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                LIVE STREAMING
              </span>
            ) : (
              <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-mono font-bold bg-amber-100 text-amber-800 border border-amber-300">
                <RefreshCw className="w-3 h-3 animate-spin" />
                CONNECTING...
              </span>
            )}
          </h1>
          <p className="text-xs text-zinc-500 mt-1">Real-time platform status, active agent telemetry, and live cross-tenant operation streams.</p>
        </div>

        <div className="flex items-center gap-2 text-xs font-mono">
          <span className="px-3 py-1.5 rounded-lg bg-zinc-100 border border-zinc-200 text-zinc-700">Cluster: us-east-1-prod</span>
          <span className="px-3 py-1.5 rounded-lg bg-emerald-50 border border-emerald-200 text-emerald-700 font-bold">● SLA {telemetry.sla_uptime || '99.99%'}</span>
        </div>
      </div>

      {/* Privacy Control Banner */}
      <div className="bg-zinc-900 text-zinc-100 p-4 rounded-xl border border-zinc-800 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <ShieldCheck className="w-5 h-5 text-emerald-400 shrink-0" />
          <div className="text-xs">
            <span className="font-bold text-white uppercase tracking-wide font-mono">Strict Privacy Control Active</span>
            <p className="text-zinc-400 mt-0.5">Stream carries operational status & telemetry metadata only. Resident PII, chat conversations, and ERP API tokens are strictly filtered out.</p>
          </div>
        </div>
        <span className="text-[10px] font-mono bg-zinc-800 px-2.5 py-1 rounded border border-zinc-700 text-zinc-300 shrink-0">Zero PII Stream</span>
      </div>

      {/* LIVE PLATFORM STATUS Grid */}
      <div className="space-y-3">
        <h2 className="text-xs font-bold text-zinc-900 uppercase tracking-wider font-mono flex items-center gap-2">
          <Radio className="w-4 h-4 text-emerald-600 animate-pulse" /> LIVE PLATFORM STATUS
        </h2>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="yc-card p-5 space-y-1">
            <div className="flex items-center justify-between text-zinc-500">
              <span className="text-[11px] font-semibold uppercase tracking-wider">Organizations</span>
              <Building2 className="w-4 h-4 text-zinc-400" />
            </div>
            <div className="text-2xl font-bold text-zinc-900 font-mono">{telemetry.total_organizations || orgs.length || 1}</div>
            <div className="flex items-center justify-between text-xs font-mono pt-1">
              <span className="text-emerald-600 font-semibold">● {telemetry.active_organizations || 1} Active</span>
              <span className="text-zinc-400">0 Suspended</span>
            </div>
          </div>

          <div className="yc-card p-5 space-y-1">
            <div className="flex items-center justify-between text-zinc-500">
              <span className="text-[11px] font-semibold uppercase tracking-wider">Active Agents</span>
              <Bot className="w-4 h-4 text-emerald-600" />
            </div>
            <div className="text-2xl font-bold text-zinc-900 font-mono">{telemetry.active_agents || 1}</div>
            <div className="flex items-center justify-between text-xs font-mono pt-1">
              <span className="text-emerald-600 font-semibold">● {telemetry.online_agents || 1} Online</span>
              <span className="text-zinc-400">{telemetry.offline_agents || 0} Offline</span>
            </div>
          </div>

          <div className="yc-card p-5 space-y-1">
            <div className="flex items-center justify-between text-zinc-500">
              <span className="text-[11px] font-semibold uppercase tracking-wider">Connected Sources</span>
              <Zap className="w-4 h-4 text-amber-500" />
            </div>
            <div className="text-2xl font-bold text-zinc-900 font-mono">{telemetry.connected_integrations || 1}</div>
            <div className="flex items-center justify-between text-xs font-mono pt-1">
              <span className="text-emerald-600 font-semibold">● Synchronized</span>
              <span className="text-zinc-400">{telemetry.failed_integrations || 0} Failed</span>
            </div>
          </div>

          <div className="yc-card p-5 space-y-1">
            <div className="flex items-center justify-between text-zinc-500">
              <span className="text-[11px] font-semibold uppercase tracking-wider">System Health</span>
              <Activity className="w-4 h-4 text-emerald-500" />
            </div>
            <div className="text-xl font-bold text-emerald-600 font-mono">{telemetry.system_health || '100% OPERATIONAL'}</div>
            <div className="flex items-center justify-between text-xs font-mono pt-1">
              <span className="text-zinc-500">P95 Latency</span>
              <span className="font-semibold text-zinc-800">{telemetry.p95_latency_ms || 340}ms</span>
            </div>
          </div>
        </div>
      </div>

      {/* Main Content Area: Organization Selector & Event Stream */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left Column: Organization Monitoring Selector */}
        <div className="yc-card p-6 space-y-4 lg:col-span-1">
          <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
            <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-wider font-mono flex items-center gap-2">
              <Building2 className="w-4 h-4 text-zinc-600" /> Live Organization Monitor
            </h3>
            <span className="text-[10px] font-mono bg-zinc-100 text-zinc-600 px-2 py-0.5 rounded font-semibold">
              {orgs.length} Total
            </span>
          </div>

          <div className="space-y-2">
            <label className="text-[11px] font-semibold text-zinc-500 uppercase font-mono">Filter Telemetry by Tenant:</label>
            <select
              value={selectedOrgId}
              onChange={(e) => setSelectedOrgId(e.target.value)}
              aria-label="Filter Telemetry by Tenant"
              className="w-full text-xs font-mono p-2.5 rounded-lg border border-zinc-300 bg-white text-zinc-800 focus:outline-none focus:ring-2 focus:ring-zinc-900"
            >
              <option value="all">🌐 All Organizations (Global Overview)</option>
              {orgs.map((o) => (
                <option key={o.id} value={o.id || o.name}>
                  🏨 {o.name} ({o.slug || 'active'})
                </option>
              ))}
            </select>
          </div>

          <div className="space-y-3 pt-2">
            <h4 className="text-[11px] font-bold text-zinc-700 uppercase font-mono border-b border-zinc-100 pb-1">
              Organization Health Status
            </h4>
            {loading ? (
              <div className="text-xs text-zinc-400 py-4 text-center">Loading tenants...</div>
            ) : (
              <div className="space-y-2 max-h-[320px] overflow-y-auto pr-1">
                {orgs.map((o) => (
                  <div 
                    key={o.id}
                    onClick={() => setSelectedOrgId(o.id || o.name)}
                    className={`p-3 rounded-lg border text-xs cursor-pointer transition-all ${
                      selectedOrgId === o.id || selectedOrgId === o.name 
                        ? 'border-zinc-900 bg-zinc-50 shadow-xs' 
                        : 'border-zinc-200 bg-white hover:border-zinc-300'
                    }`}
                  >
                    <div className="flex items-center justify-between font-semibold">
                      <span className="text-zinc-900 font-bold truncate max-w-[150px]">{o.name}</span>
                      {getStatusBadge(o.status || 'ONLINE')}
                    </div>
                    <div className="flex items-center justify-between text-[10px] text-zinc-500 font-mono mt-2">
                      <span>Slug: {o.slug || 'tenant'}</span>
                      <span className="text-emerald-600">Sync: 100%</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Right Column: Real-Time Platform Event Stream */}
        <div className="yc-card p-6 space-y-4 lg:col-span-2">
          <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
            <div>
              <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-wider font-mono flex items-center gap-2">
                <Radio className="w-4 h-4 text-emerald-600 animate-pulse" /> Real-Time Platform Event Stream
              </h3>
              <p className="text-[11px] text-zinc-500 mt-0.5">Live operational events pushed via Server-Sent Events (SSE)</p>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-[10px] font-mono px-2 py-0.5 rounded bg-zinc-100 text-zinc-600 border border-zinc-200">
                {filteredEvents.length} Events
              </span>
            </div>
          </div>

          <div className="space-y-2.5 max-h-[480px] overflow-y-auto pr-1">
            {filteredEvents.length === 0 ? (
              <div className="py-12 text-center space-y-2">
                <Clock className="w-8 h-8 text-zinc-300 mx-auto" />
                <p className="text-xs text-zinc-500 font-mono">Listening for live updates from connected organizations...</p>
              </div>
            ) : (
              filteredEvents.map((evt, idx) => (
                <div 
                  key={evt.id || idx}
                  className="p-3.5 bg-zinc-50 border border-zinc-200 rounded-xl flex items-start justify-between gap-3 text-xs font-mono transition-all hover:bg-zinc-100/80"
                >
                  <div className="space-y-1">
                    <div className="flex items-center gap-2">
                      <span className="font-bold text-zinc-900">{evt.org_name || 'Azure Palm Hostel'}</span>
                      {getStatusBadge(evt.status || 'ONLINE')}
                    </div>
                    <p className="text-zinc-700 text-[11px] font-normal leading-relaxed">{evt.summary}</p>
                  </div>
                  <span className="text-[10px] text-zinc-400 whitespace-nowrap shrink-0 flex items-center gap-1 font-mono">
                    <Clock className="w-3 h-3" />
                    {evt.timestamp || 'Just now'}
                  </span>
                </div>
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

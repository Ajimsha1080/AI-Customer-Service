'use client';
import React, { useState, useEffect } from 'react';
import { Bot } from 'lucide-react';
import { API_BASE } from '@/lib/api';

export default function PlatformAgentsPage() {
  const [agents, setAgents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadGlobalAgents() {
      try {
        const res = await fetch(`${API_BASE}/api/v1/agents?organization_id=org_azure_group`);
        if (res.ok) {
          const data = await res.json();
          setAgents(data);
        }
      } catch (err) {
        console.error("Error loading global agents:", err);
      } finally {
        setLoading(false);
      }
    }
    loadGlobalAgents();
  }, []);

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="border-b border-zinc-200 pb-6">
        <h1 className="text-2xl font-bold text-zinc-900">Platform Agent Runtimes</h1>
        <p className="text-xs text-zinc-500 mt-1">All stateful AI agent runtimes executed on the Shared Multi-Tenant Cluster.</p>
      </div>

      <div className="yc-card p-6 space-y-4">
        {loading ? (
          <div className="py-8 text-center text-xs text-zinc-400">Loading active agent runtimes...</div>
        ) : agents.length === 0 ? (
          <div className="py-8 text-center text-xs text-zinc-500">No active agent runtimes found.</div>
        ) : (
          <table className="w-full text-left text-xs font-mono">
            <thead className="text-zinc-500 border-b border-zinc-200">
              <tr>
                <th className="pb-3">AGENT RUNTIME NAME</th>
                <th className="pb-3">ORGANIZATION ID</th>
                <th className="pb-3">TYPE</th>
                <th className="pb-3">MODEL</th>
                <th className="pb-3">AGENT ID</th>
                <th className="pb-3">STATUS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 text-zinc-800">
              {agents.map(a => (
                <tr key={a.id}>
                  <td className="py-3 font-bold text-zinc-900 flex items-center gap-2">
                    <Bot className="w-4 h-4 text-zinc-600" /> {a.name}
                  </td>
                  <td className="text-zinc-700 font-semibold">{a.organization_id}</td>
                  <td><span className="yc-badge">{a.agent_type || 'CONCIERGE'}</span></td>
                  <td className="text-zinc-900 font-bold">{a.model || 'sarvam-2b'}</td>
                  <td className="text-zinc-500 font-mono">{a.id}</td>
                  <td><span className="yc-badge-emerald">● {a.status || 'ACTIVE'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

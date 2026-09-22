'use client';
import React, { useState, useEffect } from 'react';
import { Building2, Plus, Search, Edit, Trash2 } from 'lucide-react';
import { API_BASE } from '@/lib/api';

export default function PlatformOrganizationsPage() {
  const [orgs, setOrgs] = useState<any[]>([]);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadOrgs() {
      try {
        const res = await fetch(`${API_BASE}/api/v1/organizations`);
        if (res.ok) {
          const data = await res.json();
          setOrgs(data);
        }
      } catch (err) {
        console.error("Error loading organizations:", err);
      } finally {
        setLoading(false);
      }
    }
    loadOrgs();
  }, []);

  const filtered = orgs.filter(o => (o.name || '').toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="flex items-center justify-between border-b border-zinc-200 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Tenant Organizations Registry</h1>
          <p className="text-xs text-zinc-500 mt-1">Manage paying SaaS customer accounts, subscriptions, properties count, and status.</p>
        </div>

        <button className="yc-btn-primary flex items-center gap-1.5">
          <Plus className="w-3.5 h-3.5" /> Provision Organization
        </button>
      </div>

      <div className="yc-card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-wider font-mono">Customer Accounts ({filtered.length})</h3>
          <div className="relative w-64">
            <Search className="w-3.5 h-3.5 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input 
              type="text" 
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter organizations..."
              className="w-full bg-zinc-50 border border-zinc-200 rounded-lg pl-8 pr-3 py-1.5 text-xs text-zinc-900 focus:outline-none font-mono"
            />
          </div>
        </div>

        {loading ? (
          <div className="py-8 text-center text-xs text-zinc-400">Loading customer organizations...</div>
        ) : filtered.length === 0 ? (
          <div className="py-8 text-center text-xs text-zinc-500">No organizations found in database.</div>
        ) : (
          <table className="w-full text-left text-xs font-mono">
            <thead className="text-zinc-500 border-b border-zinc-200">
              <tr>
                <th className="pb-3">ORGANIZATION NAME</th>
                <th className="pb-3">SLUG</th>
                <th className="pb-3">ID</th>
                <th className="pb-3">STATUS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 text-zinc-800">
              {filtered.map(o => (
                <tr key={o.id}>
                  <td className="py-3 font-bold text-zinc-900">
                    {o.name}
                  </td>
                  <td><span className="yc-badge">{o.slug}</span></td>
                  <td className="text-zinc-500 font-mono">{o.id}</td>
                  <td className="text-emerald-600 font-bold">● {o.status || 'ACTIVE'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

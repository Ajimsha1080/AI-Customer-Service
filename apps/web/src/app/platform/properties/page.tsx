'use client';
import React, { useState, useEffect } from 'react';
import { API_BASE } from '@/lib/api';

export default function PlatformPropertiesPage() {
  const [properties, setProperties] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadGlobalProperties() {
      try {
        const res = await fetch(`${API_BASE}/api/v1/properties?organization_id=org_azure_group`);
        if (res.ok) {
          const data = await res.json();
          setProperties(data);
        }
      } catch (err) {
        console.error("Error loading global properties:", err);
      } finally {
        setLoading(false);
      }
    }
    loadGlobalProperties();
  }, []);

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="border-b border-zinc-200 pb-6">
        <h1 className="text-2xl font-bold text-zinc-900">Global Properties Registry</h1>
        <p className="text-xs text-zinc-500 mt-1">All registered resorts, hotels, and hostels across active tenant accounts.</p>
      </div>

      <div className="yc-card p-6 space-y-4">
        {loading ? (
          <div className="py-8 text-center text-xs text-zinc-400">Loading properties registry...</div>
        ) : properties.length === 0 ? (
          <div className="py-8 text-center text-xs text-zinc-500">No properties found in database.</div>
        ) : (
          <table className="w-full text-left text-xs font-mono">
            <thead className="text-zinc-500 border-b border-zinc-200">
              <tr>
                <th className="pb-3">PROPERTY NAME</th>
                <th className="pb-3">ORGANIZATION ID</th>
                <th className="pb-3">TYPE</th>
                <th className="pb-3">PROPERTY ID</th>
                <th className="pb-3">STATUS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 text-zinc-800">
              {properties.map(p => (
                <tr key={p.id}>
                  <td className="py-3 font-bold text-zinc-900">{p.name}</td>
                  <td className="text-zinc-700 font-semibold">{p.organization_id}</td>
                  <td><span className="yc-badge">{p.property_type || 'Resort'}</span></td>
                  <td className="text-zinc-500">{p.id}</td>
                  <td className="text-emerald-600 font-bold">● {p.status || 'ACTIVE'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

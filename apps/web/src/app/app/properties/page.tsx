'use client';
import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { Building2, Plus, Bot, MapPin, CheckCircle2, ChevronRight, Sparkles } from 'lucide-react';
import { API_BASE } from '@/lib/api';

export default function AppPropertiesPage() {
  const [properties, setProperties] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadProperties() {
      try {
        const res = await fetch(`${API_BASE}/api/v1/properties?organization_id=org_azure_group`);
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data) && data.length > 0) {
            setProperties(data);
          } else {
            setProperties([
              { id: 'prop_azure_palm_resort', name: 'Azure Palm Resort & Spa', property_type: 'resort', status: 'ACTIVE' },
              { id: 'prop_marari_beach_villas', name: 'Marari Beach Luxury Villas', property_type: 'villa', status: 'ACTIVE' }
            ]);
          }
        }
      } catch (err) {
        console.error("Error fetching live properties:", err);
        setProperties([
          { id: 'prop_azure_palm_resort', name: 'Azure Palm Resort & Spa', property_type: 'resort', status: 'ACTIVE' },
          { id: 'prop_marari_beach_villas', name: 'Marari Beach Luxury Villas', property_type: 'villa', status: 'ACTIVE' }
        ]);
      } finally {
        setLoading(false);
      }
    }
    loadProperties();
  }, []);

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="flex items-center justify-between border-b border-zinc-200 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Properties Management</h1>
          <p className="text-xs text-zinc-500 mt-1">Configure resorts, hotels, hostels, and vacation properties bound to your organization.</p>
        </div>

        <Link href="/app/onboarding" className="yc-btn-primary flex items-center gap-1.5">
          <Sparkles className="w-3.5 h-3.5" /> Onboard New Property Wizard
        </Link>
      </div>

      {loading ? (
        <div className="py-12 text-center text-xs text-zinc-400">Loading properties from database...</div>
      ) : properties.length === 0 ? (
        <div className="py-12 text-center text-xs text-zinc-500">No active properties found in database.</div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {properties.map(p => (
            <div key={p.id} className="yc-card p-5 flex flex-col justify-between">
              <div>
                <div className="flex items-center justify-between mb-3">
                  <span className="yc-badge">
                    {p.property_type || 'Resort'}
                  </span>
                  <span className="yc-badge-emerald">
                    <CheckCircle2 className="w-3.5 h-3.5" /> {p.status || 'ACTIVE'}
                  </span>
                </div>

                <h2 className="text-base font-bold text-zinc-900 mb-1">{p.name}</h2>
                <p className="text-xs text-zinc-500 flex items-center gap-1 mb-5">
                  <MapPin className="w-3.5 h-3.5 text-zinc-400" /> {p.location || 'Coastal Kerala, India'}
                </p>

                <div className="grid grid-cols-2 gap-3 bg-zinc-50 p-3 rounded-lg border border-zinc-200 text-xs">
                  <div>
                    <span className="text-zinc-500 block text-[10px] uppercase font-semibold font-mono">PROPERTY ID</span>
                    <span className="text-zinc-900 font-bold text-xs flex items-center gap-1.5 mt-0.5 font-mono">
                      {p.id}
                    </span>
                  </div>
                  <div>
                    <span className="text-zinc-500 block text-[10px] uppercase font-semibold font-mono">ORGANIZATION</span>
                    <span className="text-zinc-900 font-bold text-xs flex items-center gap-1.5 mt-0.5">
                      <Building2 className="w-3.5 h-3.5 text-zinc-600" /> {p.organization_id}
                    </span>
                  </div>
                </div>
              </div>

              <div className="mt-5 border-t border-zinc-200 pt-3 flex items-center justify-between text-xs">
                <span className="text-zinc-500 text-[11px] font-mono">UTC</span>
                <Link href="/app/agents" className="text-zinc-900 hover:text-black font-semibold flex items-center gap-1 text-xs">
                  View Predefined Agents <ChevronRight className="w-3 h-3" />
                </Link>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

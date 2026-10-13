'use client';
import React, { useState, useEffect } from 'react';
import { Users, Building2, Search, CheckCircle2, ShieldCheck, UserPlus, Loader2 } from 'lucide-react';
import { authFetch, getCurrentSession } from '@/lib/api';

export default function HostelResidentsPage() {
  const [residents, setResidents] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [session, setSession] = useState<any>(null);

  // New resident modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [name, setName] = useState('');
  const [roomNumber, setRoomNumber] = useState('');
  const [block, setBlock] = useState('Block A');
  const [phone, setPhone] = useState('');
  const [email, setEmail] = useState('');
  const [creating, setCreating] = useState(false);

  const fetchResidents = async () => {
    setLoading(true);
    try {
      const sess = await getCurrentSession();
      setSession(sess);
      const orgId = sess?.organization_id;
      if (orgId) {
        const res = await authFetch(`/api/v1/residents?organization_id=${orgId}`);
        if (res.ok) {
          const data = await res.json();
          setResidents(Array.isArray(data) ? data : []);
        } else {
          throw new Error('Failed to fetch residents directory');
        }
      }
    } catch (err: any) {
      setError(err.message || 'Error fetching residents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchResidents();
  }, []);

  const handleCreateResident = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session?.organization_id) return;
    setCreating(true);

    try {
      const propRes = await authFetch(`/api/v1/properties?organization_id=${session.organization_id}`);
      let propId = 'prop_default';
      if (propRes.ok) {
        const props = await propRes.json();
        if (Array.isArray(props) && props.length > 0) {
          propId = props[0].id;
        }
      }

      const res = await authFetch('/api/v1/residents', {
        method: 'POST',
        body: JSON.stringify({
          organization_id: session.organization_id,
          property_id: propId,
          name,
          room_number: roomNumber,
          block,
          phone: phone || undefined,
          email: email || undefined,
          status: 'ACTIVE',
          fee_status: 'PAID'
        })
      });

      if (res.ok) {
        setIsModalOpen(false);
        setName('');
        setRoomNumber('');
        setPhone('');
        setEmail('');
        fetchResidents();
      }
    } catch (err) {
      console.error('Failed to create resident:', err);
    } finally {
      setCreating(false);
    }
  };

  const filteredResidents = residents.filter(r => 
    (r.name || '').toLowerCase().includes(searchTerm.toLowerCase()) || 
    (r.room_number || '').includes(searchTerm) ||
    (r.block || '').toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="flex items-center justify-between border-b border-zinc-200 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Resident & Guest Directory</h1>
          <p className="text-xs text-zinc-500 mt-1">Manage hospitality guests, room allocations, fee statuses, and contact profiles.</p>
        </div>

        <div className="flex items-center gap-3">
          <span className="yc-badge-emerald font-mono text-xs px-3.5 py-1 font-semibold">
            ● {residents.length} Registered Guests
          </span>
          <button
            onClick={() => setIsModalOpen(true)}
            className="yc-btn-primary flex items-center gap-1.5 text-xs"
          >
            <UserPlus className="w-4 h-4" /> Register Guest
          </button>
        </div>
      </div>

      {/* Search & Actions Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search by name, room number, or block..."
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
            className="w-full bg-zinc-50 border border-zinc-200 rounded-xl pl-9 pr-4 py-2 text-xs text-zinc-800 focus:outline-none focus:border-zinc-400"
          />
        </div>
      </div>

      {loading ? (
        <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
          <Loader2 className="w-8 h-8 animate-spin text-zinc-700" />
          <p className="text-xs">Loading residents...</p>
        </div>
      ) : residents.length === 0 ? (
        <div className="yc-card p-12 text-center space-y-3">
          <Users className="w-10 h-10 text-zinc-400 mx-auto" />
          <h3 className="text-sm font-bold text-zinc-900">No Guests Registered</h3>
          <p className="text-xs text-zinc-500 max-w-sm mx-auto">No resident or guest records found for this property. Click &quot;Register Guest&quot; to add your first guest record.</p>
        </div>
      ) : (
        <div className="yc-card p-6 space-y-4">
          <h2 className="text-sm font-bold text-zinc-900">Guest Roster</h2>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-sans">
              <thead className="text-zinc-500 border-b border-zinc-200 font-mono text-[11px]">
                <tr>
                  <th className="pb-3 font-semibold">NAME</th>
                  <th className="pb-3 font-semibold">ROOM & BLOCK</th>
                  <th className="pb-3 font-semibold">CONTACT</th>
                  <th className="pb-3 font-semibold">STATUS</th>
                  <th className="pb-3 font-semibold text-right">FEES</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-100">
                {filteredResidents.map((r) => (
                  <tr key={r.id} className="hover:bg-zinc-50/50 transition">
                    <td className="py-3 font-semibold text-zinc-900">{r.name}</td>
                    <td className="py-3 text-zinc-600 font-mono">{r.room_number} ({r.block})</td>
                    <td className="py-3 text-zinc-500">{r.email || r.phone || '—'}</td>
                    <td className="py-3">
                      <span className="px-2 py-0.5 rounded-md bg-emerald-100 text-emerald-800 font-mono text-[10px] font-bold">
                        {r.status || 'ACTIVE'}
                      </span>
                    </td>
                    <td className="py-3 text-right">
                      <span className={`px-2 py-0.5 rounded-md font-mono text-[10px] font-bold ${
                        r.fee_status === 'PAID' ? 'bg-zinc-100 text-zinc-700' : 'bg-amber-100 text-amber-800'
                      }`}>
                        {r.fee_status || 'PAID'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Register Guest Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-zinc-200">
            <h3 className="text-base font-bold text-zinc-900 mb-4">Register New Guest</h3>
            <form onSubmit={handleCreateResident} className="space-y-4 text-xs">
              <div>
                <label className="block font-medium text-zinc-700 mb-1">Full Name</label>
                <input
                  type="text"
                  required
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                  placeholder="e.g. Maya Lin"
                  className="w-full border border-zinc-200 rounded-lg p-2"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block font-medium text-zinc-700 mb-1">Room Number</label>
                  <input
                    type="text"
                    required
                    value={roomNumber}
                    onChange={(e) => setRoomNumber(e.target.value)}
                    placeholder="e.g. 101"
                    className="w-full border border-zinc-200 rounded-lg p-2"
                  />
                </div>
                <div>
                  <label className="block font-medium text-zinc-700 mb-1">Block / Wing</label>
                  <input
                    type="text"
                    value={block}
                    onChange={(e) => setBlock(e.target.value)}
                    placeholder="e.g. Wing A"
                    className="w-full border border-zinc-200 rounded-lg p-2"
                  />
                </div>
              </div>

              <div>
                <label className="block font-medium text-zinc-700 mb-1">Contact Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  placeholder="guest@example.com"
                  className="w-full border border-zinc-200 rounded-lg p-2"
                />
              </div>

              <div>
                <label className="block font-medium text-zinc-700 mb-1">Phone Number</label>
                <input
                  type="tel"
                  value={phone}
                  onChange={(e) => setPhone(e.target.value)}
                  placeholder="+1 (555) 000-0000"
                  className="w-full border border-zinc-200 rounded-lg p-2"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsModalOpen(false)}
                  className="px-4 py-2 rounded-lg border border-zinc-200 text-zinc-600 hover:bg-zinc-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creating}
                  className="px-4 py-2 rounded-lg bg-zinc-900 text-white hover:bg-zinc-800 disabled:opacity-50"
                >
                  {creating ? 'Saving...' : 'Register'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

'use client';
import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { Wrench, CheckCircle2, Clock, AlertTriangle, Plus, Filter, UserCheck, Loader2 } from 'lucide-react';
import { authFetch, getCurrentSession } from '@/lib/api';

export default function HostelRequestsPage() {
  const [requests, setRequests] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [session, setSession] = useState<any>(null);

  // New ticket modal state
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [newRoom, setNewRoom] = useState('');
  const [newSummary, setNewSummary] = useState('');
  const [newCategory, setNewCategory] = useState('Maintenance');
  const [creating, setCreating] = useState(false);

  const fetchTickets = async () => {
    setLoading(true);
    try {
      const sess = await getCurrentSession();
      setSession(sess);
      const orgId = sess?.organization_id;
      if (orgId) {
        const res = await authFetch(`/api/v1/support-tickets?organization_id=${orgId}`);
        if (res.ok) {
          const data = await res.json();
          setRequests(Array.isArray(data) ? data : []);
        } else {
          throw new Error('Failed to fetch support tickets');
        }
      }
    } catch (err: any) {
      setError(err.message || 'Error fetching support tickets');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTickets();
  }, []);

  const updateStatus = async (id: string, newStatus: string) => {
    try {
      const res = await authFetch(`/api/v1/support-tickets/${id}`, {
        method: 'PUT',
        body: JSON.stringify({ status: newStatus })
      });
      if (res.ok) {
        setRequests(prev => prev.map(r => r.id === id ? { ...r, status: newStatus } : r));
      }
    } catch (err) {
      console.error('Failed to update ticket status:', err);
    }
  };

  const handleCreateTicket = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session?.organization_id) return;
    setCreating(true);

    try {
      // Find default property
      const propRes = await authFetch(`/api/v1/properties?organization_id=${session.organization_id}`);
      let propId = 'prop_default';
      if (propRes.ok) {
        const props = await propRes.json();
        if (Array.isArray(props) && props.length > 0) {
          propId = props[0].id;
        }
      }

      const res = await authFetch('/api/v1/support-tickets', {
        method: 'POST',
        body: JSON.stringify({
          organization_id: session.organization_id,
          property_id: propId,
          room_number: newRoom || undefined,
          issue_summary: newSummary,
          category: newCategory,
          priority: 'HIGH'
        })
      });

      if (res.ok) {
        setIsModalOpen(false);
        setNewRoom('');
        setNewSummary('');
        fetchTickets();
      }
    } catch (err) {
      console.error('Failed to create ticket:', err);
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="flex items-center justify-between border-b border-zinc-200 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Maintenance & Service Requests</h1>
          <p className="text-xs text-zinc-500 mt-1">Track and manage resident maintenance requests, complaints, and staff assignments.</p>
        </div>

        <div className="flex items-center gap-3">
          <span className="yc-badge-emerald font-mono text-xs px-3.5 py-1 font-semibold">
            ● {requests.filter(r => r.status !== 'RESOLVED' && r.status !== 'CLOSED').length} Active Requests
          </span>
          <button
            onClick={() => setIsModalOpen(true)}
            className="yc-btn-primary flex items-center gap-1.5 text-xs"
          >
            <Plus className="w-4 h-4" /> New Ticket
          </button>
        </div>
      </div>

      {loading ? (
        <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
          <Loader2 className="w-8 h-8 animate-spin text-zinc-700" />
          <p className="text-xs">Loading support tickets...</p>
        </div>
      ) : requests.length === 0 ? (
        <div className="yc-card p-12 text-center space-y-3">
          <CheckCircle2 className="w-10 h-10 text-emerald-500 mx-auto" />
          <h3 className="text-sm font-bold text-zinc-900">No Open Tickets</h3>
          <p className="text-xs text-zinc-500 max-w-sm mx-auto">All guest requests and maintenance issues have been resolved. New requests from the guest widget or staff will appear here.</p>
        </div>
      ) : (
        <div className="space-y-4">
          {requests.map((r) => (
            <div key={r.id} className="yc-card p-5 space-y-3">
              <div className="flex items-start justify-between">
                <div className="space-y-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs font-bold text-zinc-900">{r.id}</span>
                    <span className="text-xs font-semibold px-2 py-0.5 rounded-md bg-zinc-100 text-zinc-700">
                      {r.category || 'General'}
                    </span>
                    {r.room_number && (
                      <span className="text-xs text-zinc-500">Room {r.room_number}</span>
                    )}
                  </div>
                  <p className="text-sm text-zinc-800">{r.issue_summary || r.description}</p>
                </div>

                <div className="flex items-center gap-2">
                  <select
                    value={r.status || 'OPEN'}
                    onChange={(e) => updateStatus(r.id, e.target.value)}
                    className="text-xs font-mono font-bold rounded-lg px-2.5 py-1 border border-zinc-200 bg-white text-zinc-800"
                  >
                    <option value="OPEN">OPEN</option>
                    <option value="IN_PROGRESS">IN_PROGRESS</option>
                    <option value="RESOLVED">RESOLVED</option>
                    <option value="CLOSED">CLOSED</option>
                  </select>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Create Ticket Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-zinc-200">
            <h3 className="text-base font-bold text-zinc-900 mb-4">Create Service Request</h3>
            <form onSubmit={handleCreateTicket} className="space-y-4 text-xs">
              <div>
                <label className="block font-medium text-zinc-700 mb-1">Category</label>
                <select
                  value={newCategory}
                  onChange={(e) => setNewCategory(e.target.value)}
                  className="w-full border border-zinc-200 rounded-lg p-2"
                >
                  <option value="Maintenance">Maintenance & Repairs</option>
                  <option value="Housekeeping">Housekeeping & Amenities</option>
                  <option value="Plumbing">Plumbing</option>
                  <option value="Electrical">Electrical</option>
                  <option value="Dining">Room Dining</option>
                </select>
              </div>

              <div>
                <label className="block font-medium text-zinc-700 mb-1">Room Number (Optional)</label>
                <input
                  type="text"
                  value={newRoom}
                  onChange={(e) => setNewRoom(e.target.value)}
                  placeholder="e.g. 204"
                  className="w-full border border-zinc-200 rounded-lg p-2"
                />
              </div>

              <div>
                <label className="block font-medium text-zinc-700 mb-1">Issue Description</label>
                <textarea
                  required
                  rows={3}
                  value={newSummary}
                  onChange={(e) => setNewSummary(e.target.value)}
                  placeholder="Describe the request or issue..."
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
                  {creating ? 'Creating...' : 'Create Ticket'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

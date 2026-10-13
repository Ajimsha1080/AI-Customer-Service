'use client';
import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import { Settings, Save, Shield, Phone, Sparkles, Building2, UserCheck, Key, Users, MessageSquare, ChevronRight, UserPlus, Trash2, Loader2, Check } from 'lucide-react';
import { authFetch, getCurrentSession } from '@/lib/api';

export default function AppSettingsPage() {
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [session, setSession] = useState<any>(null);

  const [orgName, setOrgName] = useState('');
  const [members, setMembers] = useState<any[]>([]);
  const [invitations, setInvitations] = useState<any[]>([]);

  // Invite modal
  const [inviteEmail, setInviteEmail] = useState('');
  const [inviteRole, setInviteRole] = useState('STAFF');
  const [inviting, setInviting] = useState(false);
  const [copiedToken, setCopiedToken] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const loadSettings = async () => {
    setLoading(true);
    try {
      const sess = await getCurrentSession();
      setSession(sess);
      if (sess?.organization_id) {
        const [orgRes, memRes, invRes] = await Promise.all([
          authFetch(`/api/v1/organizations/${sess.organization_id}`).then(r => r.ok ? r.json() : null).catch(() => null),
          authFetch(`/api/v1/organizations/${sess.organization_id}/members`).then(r => r.ok ? r.json() : []).catch(() => []),
          authFetch(`/api/v1/organizations/${sess.organization_id}/invitations`).then(r => r.ok ? r.json() : []).catch(() => [])
        ]);

        if (orgRes) {
          setOrgName(orgRes.name || '');
        }
        setMembers(Array.isArray(memRes) ? memRes : []);
        setInvitations(Array.isArray(invRes) ? invRes : []);
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const handleSaveOrg = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session?.organization_id) return;
    setSaving(true);
    try {
      const res = await authFetch(`/api/v1/organizations/${session.organization_id}`, {
        method: 'PATCH',
        body: JSON.stringify({ name: orgName })
      });
      if (res.ok) {
        showToast('✓ Organization settings updated successfully!');
      } else {
        const err = await res.json();
        showToast(`Error: ${err.detail || 'Could not update organization'}`);
      }
    } catch {
      showToast('Error: Failed to save changes.');
    } finally {
      setSaving(false);
    }
  };

  const handleInvite = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session?.organization_id || !inviteEmail.trim()) return;
    setInviting(true);
    try {
      const res = await authFetch(`/api/v1/organizations/${session.organization_id}/invitations`, {
        method: 'POST',
        body: JSON.stringify({ email: inviteEmail, role: inviteRole })
      });
      if (res.ok) {
        const data = await res.json();
        showToast(`✓ Invitation sent to ${inviteEmail}`);
        setInviteEmail('');
        loadSettings();
      } else {
        const err = await res.json();
        showToast(`Error: ${err.detail || 'Invitation failed'}`);
      }
    } finally {
      setInviting(false);
    }
  };

  return (
    <div className="max-w-4xl mx-auto space-y-8 font-sans">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-5 right-5 bg-zinc-900 text-white px-4 py-3 rounded-xl shadow-lg border border-zinc-700 text-xs flex items-center gap-2 z-50">
          <Sparkles className="w-4 h-4 text-emerald-400" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Header */}
      <div className="border-b border-zinc-200 pb-6">
        <h1 className="text-2xl font-bold text-zinc-900">Workspace & Team Settings</h1>
        <p className="text-xs text-zinc-500 mt-1">Configure tenant properties, manage staff members, and issue invites.</p>
      </div>

      {loading ? (
        <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
          <Loader2 className="w-8 h-8 animate-spin text-zinc-700" />
          <p className="text-xs">Loading workspace settings...</p>
        </div>
      ) : (
        <div className="space-y-8 text-xs font-sans">
          {/* 1. Organization Profile */}
          <form onSubmit={handleSaveOrg} className="yc-card p-6 space-y-4">
            <h2 className="text-sm font-bold text-zinc-900 flex items-center gap-2 border-b border-zinc-200 pb-3">
              <Building2 className="w-4 h-4 text-zinc-700" /> Organization Profile
            </h2>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-1">
                <label className="font-semibold text-zinc-700">Workspace Name</label>
                <input
                  type="text"
                  required
                  value={orgName}
                  onChange={(e) => setOrgName(e.target.value)}
                  className="w-full bg-zinc-50 border border-zinc-200 rounded-xl px-3.5 py-2 text-zinc-900 focus:outline-none focus:border-zinc-400"
                />
              </div>

              <div className="space-y-1">
                <label className="font-semibold text-zinc-700">Organization Slug</label>
                <input
                  type="text"
                  readOnly
                  disabled
                  value={session?.organization_slug || session?.organization_id || ''}
                  className="w-full bg-zinc-100 border border-zinc-200 rounded-xl px-3.5 py-2 text-zinc-500 font-mono"
                />
              </div>
            </div>

            <div className="flex justify-end pt-2">
              <button
                type="submit"
                disabled={saving}
                className="yc-btn-primary flex items-center gap-1.5"
              >
                <Save className="w-3.5 h-3.5" /> {saving ? 'Saving...' : 'Save Workspace Name'}
              </button>
            </div>
          </form>

          {/* 2. Team Member Management */}
          <div className="yc-card p-6 space-y-6">
            <h2 className="text-sm font-bold text-zinc-900 flex items-center gap-2 border-b border-zinc-200 pb-3">
              <Users className="w-4 h-4 text-zinc-700" /> Team Members & Roles
            </h2>

            {/* Invite Form */}
            <form onSubmit={handleInvite} className="flex flex-col sm:flex-row gap-3">
              <input
                type="email"
                required
                placeholder="colleague@hospitality.com"
                value={inviteEmail}
                onChange={(e) => setInviteEmail(e.target.value)}
                className="flex-1 bg-zinc-50 border border-zinc-200 rounded-xl px-3.5 py-2 text-zinc-900 focus:outline-none focus:border-zinc-400"
              />
              <select
                value={inviteRole}
                onChange={(e) => setInviteRole(e.target.value)}
                className="bg-zinc-50 border border-zinc-200 rounded-xl px-3 py-2 text-zinc-900"
              >
                <option value="STAFF">STAFF</option>
                <option value="ADMIN">ADMIN</option>
                <option value="VIEWER">VIEWER</option>
              </select>
              <button
                type="submit"
                disabled={inviting}
                className="yc-btn-primary flex items-center justify-center gap-1.5 shrink-0"
              >
                <UserPlus className="w-3.5 h-3.5" /> {inviting ? 'Inviting...' : 'Invite Member'}
              </button>
            </form>

            {/* Members Roster */}
            <div className="space-y-3">
              <h3 className="text-xs font-bold text-zinc-700 uppercase tracking-wider font-mono">Active Members ({members.length})</h3>
              <div className="divide-y divide-zinc-100 border border-zinc-200 rounded-xl overflow-hidden bg-white">
                {members.map(m => (
                  <div key={m.id} className="p-3.5 flex items-center justify-between">
                    <div>
                      <div className="font-semibold text-zinc-900">{m.full_name || m.email}</div>
                      <div className="text-[11px] text-zinc-500">{m.email}</div>
                    </div>
                    <span className="px-2.5 py-1 rounded-md bg-zinc-100 font-mono text-[10px] font-bold text-zinc-700">
                      {m.role}
                    </span>
                  </div>
                ))}
              </div>
            </div>

            {/* Pending Invitations */}
            {invitations.length > 0 && (
              <div className="space-y-3 pt-2">
                <h3 className="text-xs font-bold text-zinc-700 uppercase tracking-wider font-mono">Pending Invitations ({invitations.length})</h3>
                <div className="divide-y divide-zinc-100 border border-zinc-200 rounded-xl overflow-hidden bg-white">
                  {invitations.map(inv => (
                    <div key={inv.id} className="p-3.5 flex items-center justify-between">
                      <div>
                        <div className="font-semibold text-zinc-900">{inv.email}</div>
                        <div className="text-[11px] text-zinc-500 font-mono">Role: {inv.role} • Expires: {inv.expires_at?.split('T')[0]}</div>
                      </div>
                      <span className="px-2 py-0.5 rounded bg-amber-50 text-amber-700 font-mono text-[10px] font-bold">
                        PENDING
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

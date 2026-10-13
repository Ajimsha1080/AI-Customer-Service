'use client';
import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { Bot, Play, CheckCircle2, Code, Sparkles, Copy, Check, Loader2, Plus, ExternalLink } from 'lucide-react';
import { authFetch, getCurrentSession, API_BASE } from '@/lib/api';

export default function AppAgentsPage() {
  const [agents, setAgents] = useState<any[]>([]);
  const [selectedAgent, setSelectedAgent] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [copiedCode, setCopiedCode] = useState(false);
  const [session, setSession] = useState<any>(null);

  // Create agent modal
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [agentName, setAgentName] = useState('Front Desk AI Concierge');
  const [creating, setCreating] = useState(false);

  const loadAgents = useCallback(async () => {
    setLoading(true);
    try {
      const sess = await getCurrentSession();
      setSession(sess);
      if (sess?.organization_id) {
        const res = await authFetch(`/api/v1/agents?organization_id=${sess.organization_id}`);
        if (res.ok) {
          const data = await res.json();
          const list = Array.isArray(data) ? data : [];
          setAgents(list);
          if (list.length > 0) {
            setSelectedAgent((prev: any) => prev || list[0]);
          }
        }
      }
    } catch (err) {
      console.error('Failed to load agents:', err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadAgents();
  }, [loadAgents]);

  const handleCreateAgent = async (e: React.FormEvent) => {
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

      const res = await authFetch('/api/v1/agents', {
        method: 'POST',
        body: JSON.stringify({
          organization_id: session.organization_id,
          property_id: propId,
          name: agentName,
          agent_type: 'CONCIERGE',
          tone: 'Friendly, Professional'
        })
      });

      if (res.ok) {
        setIsModalOpen(false);
        setAgentName('');
        await loadAgents();
      }
    } finally {
      setCreating(false);
    }
  };

  const widgetUrl = typeof window !== 'undefined' ? `${window.location.origin}/widget.js` : 'http://localhost:3000/widget.js';
  const embedSnippet = selectedAgent ? `<script 
  src="${widgetUrl}" 
  data-agent-key="${selectedAgent.id}"
  data-api-base="${API_BASE}">
</script>` : '';

  const copyEmbedCode = () => {
    if (!embedSnippet) return;
    navigator.clipboard.writeText(embedSnippet);
    setCopiedCode(true);
    setTimeout(() => setCopiedCode(false), 3000);
  };

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="flex items-center justify-between border-b border-zinc-200 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">AI Concierge & Agents</h1>
          <p className="text-xs text-zinc-500 mt-1">Deploy, configure, and monitor AI agents with real-time tool calling and web widget snippets.</p>
        </div>

        <button
          onClick={() => setIsModalOpen(true)}
          className="yc-btn-primary flex items-center gap-1.5 text-xs"
        >
          <Plus className="w-3.5 h-3.5" /> Deploy New Agent
        </button>
      </div>

      {loading ? (
        <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
          <Loader2 className="w-8 h-8 animate-spin text-zinc-700" />
          <p className="text-xs">Loading agents...</p>
        </div>
      ) : agents.length === 0 ? (
        <div className="yc-card p-12 text-center space-y-4">
          <Bot className="w-12 h-12 text-zinc-400 mx-auto" />
          <h3 className="text-sm font-bold text-zinc-900">No AI Agents Deployed</h3>
          <p className="text-xs text-zinc-500 max-w-sm mx-auto">Create and activate your first AI concierge agent to assist guests with bookings, amenities, and room requests.</p>
          <button
            onClick={() => setIsModalOpen(true)}
            className="yc-btn-primary text-xs inline-flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" /> Deploy Agent
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Agent Picker */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            {agents.map((a) => {
              const isSelected = selectedAgent?.id === a.id;
              return (
                <div
                  key={a.id}
                  onClick={() => setSelectedAgent(a)}
                  className={`yc-card p-4 cursor-pointer transition border-2 ${
                    isSelected ? 'border-zinc-900 bg-zinc-50/50' : 'border-transparent hover:border-zinc-300'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-zinc-200 text-zinc-700">
                      {a.agent_type || 'CONCIERGE'}
                    </span>
                    <span className="text-[10px] text-emerald-600 font-bold">● ACTIVE</span>
                  </div>
                  <h3 className="font-bold text-sm text-zinc-900">{a.name}</h3>
                  <p className="text-xs text-zinc-500 font-mono mt-1">{a.id}</p>
                </div>
              );
            })}
          </div>

          {selectedAgent && (
            <div className="space-y-6">
              {/* Active Agent Overview Card */}
              <div className="yc-card p-6 space-y-6">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="w-12 h-12 rounded-2xl bg-zinc-900 text-white flex items-center justify-center font-bold text-xl shadow-xs">
                      🤖
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <h2 className="text-lg font-bold text-zinc-900">{selectedAgent.name}</h2>
                        <span className="yc-badge-emerald font-mono text-[10px]">● DEPLOYED</span>
                      </div>
                      <p className="text-xs text-zinc-500 mt-0.5 font-mono">ID: {selectedAgent.id}</p>
                    </div>
                  </div>

                  <Link 
                    href={`/guest/${selectedAgent.id}`} 
                    target="_blank"
                    className="yc-btn-primary px-4 py-2 text-xs flex items-center gap-1.5 self-start md:self-auto"
                  >
                    Open Guest View <ExternalLink className="w-3.5 h-3.5" />
                  </Link>
                </div>
              </div>

              {/* Embeddable Snippet Section */}
              <div className="yc-card p-6 space-y-4">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Code className="w-4 h-4 text-zinc-700" />
                    <h2 className="text-sm font-bold text-zinc-900">Embeddable Web Widget Snippet</h2>
                  </div>
                  <button
                    onClick={copyEmbedCode}
                    className="yc-btn-secondary text-xs flex items-center gap-1.5"
                  >
                    {copiedCode ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
                    {copiedCode ? 'Copied Snippet' : 'Copy HTML Snippet'}
                  </button>
                </div>

                <p className="text-xs text-zinc-500">
                  Paste this snippet right before the closing <code className="text-zinc-800 bg-zinc-100 px-1 py-0.5 rounded font-mono">&lt;/body&gt;</code> tag on any guest portal or hotel website.
                </p>

                <div className="p-4 bg-zinc-950 text-zinc-100 rounded-xl font-mono text-xs overflow-x-auto shadow-inner">
                  <pre>{embedSnippet}</pre>
                </div>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Deploy Agent Modal */}
      {isModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-zinc-200">
            <h3 className="text-base font-bold text-zinc-900 mb-4">Deploy New AI Concierge</h3>
            <form onSubmit={handleCreateAgent} className="space-y-4 text-xs">
              <div>
                <label className="block font-medium text-zinc-700 mb-1">Agent Name</label>
                <input
                  type="text"
                  required
                  value={agentName}
                  onChange={(e) => setAgentName(e.target.value)}
                  placeholder="e.g. Resort Host AI"
                  className="w-full border border-zinc-200 rounded-lg p-2.5 bg-zinc-50 text-zinc-900"
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
                  {creating ? 'Deploying...' : 'Deploy Agent'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

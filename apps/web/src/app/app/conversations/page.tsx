'use client';
import React, { useState, useEffect } from 'react';
import { MessageSquare, User, Bot, CheckCircle2, AlertCircle, PhoneCall, Send, ShieldAlert, Tag, UserCheck } from 'lucide-react';
import { API_BASE, authFetch } from '@/lib/api';

export default function AppConversationsInboxPage() {
  const [conversations, setConversations] = useState<any[]>([]);
  const [messages, setMessages] = useState<any[]>([]);
  const [selectedConv, setSelectedConv] = useState<string>('');
  const [isHumanTakeover, setIsHumanTakeover] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function loadConversations() {
      try {
        const res = await authFetch(`${API_BASE}/api/v1/conversations`);
        if (res.ok) {
          const data = await res.json();
          if (Array.isArray(data) && data.length > 0) {
            setConversations(data);
            setSelectedConv(data[0].id);
            setIsHumanTakeover(data[0].status === 'HUMAN_STAFF_TAKEN_OVER' || data[0].is_human_takeover);
          }
        }
      } catch (err) {
        console.error("Error loading conversations:", err);
      } finally {
        setLoading(false);
      }
    }
    loadConversations();
  }, []);

  useEffect(() => {
    if (!selectedConv) return;
    async function loadMessages() {
      try {
        const res = await authFetch(`${API_BASE}/api/v1/conversations/${selectedConv}/messages`);
        if (res.ok) {
          const data = await res.json();
          setMessages(Array.isArray(data) ? data : []);
        }
      } catch (err) {
        console.error("Error loading messages:", err);
      }
    }
    loadMessages();
  }, [selectedConv]);

  const activeConv = conversations.find(c => c.id === selectedConv) || (conversations.length > 0 ? conversations[0] : null);

  const handleTakeover = async () => {
    if (!activeConv) return;
    try {
      const res = await authFetch(`${API_BASE}/api/v1/conversations/${activeConv.id}/takeover`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason: 'Staff Takeover' })
      });
      if (res.ok) {
        setIsHumanTakeover(true);
        setConversations(prev => prev.map(c => c.id === activeConv.id ? { ...c, status: 'HUMAN_STAFF_TAKEN_OVER', is_human_takeover: true } : c));
      }
    } catch (err) {
      console.error("Error executing human takeover:", err);
    }
  };

  const handleSendMessage = async () => {
    if (!chatInput.trim() || !activeConv) return;
    const text = chatInput;
    setChatInput('');
    try {
      const res = await authFetch(`${API_BASE}/api/v1/conversations/${activeConv.id}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text })
      });
      if (res.ok) {
        const newMsg = await res.json();
        setMessages(prev => [...prev, newMsg]);
      }
    } catch (err) {
      console.error("Error sending staff message:", err);
    }
  };

  return (
    <div className="h-[calc(100vh-120px)] grid grid-cols-1 lg:grid-cols-12 gap-4 font-sans overflow-hidden">
      {/* LEFT COLUMN: Conversation List */}
      <div className="lg:col-span-3 bg-white border border-zinc-200 rounded-2xl flex flex-col overflow-hidden shadow-xs">
        <div className="p-4 border-b border-zinc-200 bg-zinc-50 flex items-center justify-between">
          <h2 className="font-bold text-sm text-zinc-900">Staff Intercom & Human Takeover</h2>
          <span className="yc-badge">
            {conversations.length} Active
          </span>
        </div>

        <div className="flex-1 overflow-y-auto divide-y divide-zinc-200">
          {loading ? (
            <div className="p-4 text-center text-xs text-zinc-400">Loading inbox...</div>
          ) : conversations.length === 0 ? (
            <div className="p-4 text-center text-xs text-zinc-500">No active conversations found.</div>
          ) : (
            conversations.map((c) => (
              <div
                key={c.id}
                onClick={() => {
                  setSelectedConv(c.id);
                  setIsHumanTakeover(c.status === 'HUMAN_STAFF_TAKEN_OVER' || c.is_human_takeover);
                }}
                className={`p-4 cursor-pointer transition-all ${
                  selectedConv === c.id ? 'bg-zinc-100 border-l-4 border-zinc-900' : 'hover:bg-zinc-50'
                }`}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-bold text-xs text-zinc-900">{c.guest || 'Guest'}</span>
                  <span className="text-[10px] text-zinc-400 font-mono">{c.time || 'Live'}</span>
                </div>
                <p className="text-[11px] text-zinc-600 line-clamp-1 mb-2">{c.last_message || 'Guest conversation active'}</p>
                <div className="flex items-center justify-between text-[10px]">
                  <span className="text-zinc-500 font-mono">{c.agent_id}</span>
                  <span className={`px-2 py-0.5 rounded font-bold ${
                    c.status === 'HUMAN_STAFF_TAKEN_OVER' ? 'bg-amber-100 text-amber-800 border border-amber-200' : 'yc-badge-emerald'
                  }`}>
                    {c.status || 'AI Active'}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>

      {/* CENTER COLUMN: Intercom-Grade Active Chat Feed */}
      <div className="lg:col-span-6 bg-white border border-zinc-200 rounded-2xl flex flex-col justify-between overflow-hidden shadow-xs">
        {activeConv ? (
          <>
            {/* Chat Header with Human Takeover Switch */}
            <div className="p-4 border-b border-zinc-200 bg-white flex items-center justify-between">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-full bg-zinc-900 text-white font-bold flex items-center justify-center text-xs shadow-xs">
                  {(activeConv.guest || 'G').charAt(0)}
                </div>
                <div>
                  <h3 className="font-bold text-sm text-zinc-900">{activeConv.guest || 'Valued Guest'}</h3>
                  <p className="text-[10px] text-zinc-500 font-medium">{activeConv.id}</p>
                </div>
              </div>

              <button
                onClick={handleTakeover}
                className={`px-3.5 py-1.5 rounded-xl text-xs font-bold transition-all flex items-center gap-1.5 ${
                  isHumanTakeover 
                    ? 'bg-amber-500 text-white shadow-xs' 
                    : 'yc-btn-secondary'
                }`}
              >
                <UserCheck className="w-3.5 h-3.5" />
                {isHumanTakeover ? 'Human Staff Controlling' : 'Take Over Conversation'}
              </button>
            </div>

            {/* Messages */}
            <div className="flex-1 p-6 space-y-4 overflow-y-auto bg-zinc-50/50">
              {messages.length === 0 ? (
                <div className="text-center text-xs text-zinc-400 py-8">No messages in this conversation yet.</div>
              ) : (
                messages.map((m: any) => {
                  const isStaff = m.sender_type === 'STAFF';
                  const isAgent = m.sender_type === 'agent' || m.sender_type === 'ai';
                  return (
                    <div key={m.id} className={`flex ${isStaff ? 'justify-end' : 'justify-start'}`}>
                      <div className={`p-4 rounded-2xl text-xs max-w-[80%] shadow-xs ${
                        isStaff 
                          ? 'bg-amber-600 text-white font-medium' 
                          : isAgent 
                            ? 'bg-zinc-900 text-white font-medium' 
                            : 'bg-white border border-zinc-200 text-zinc-800'
                      }`}>
                        <div className="text-[10px] opacity-75 font-mono mb-1">
                          {isStaff ? 'Staff Member' : isAgent ? 'AI Concierge' : (activeConv.guest || 'Guest')}
                        </div>
                        {m.content}
                      </div>
                    </div>
                  );
                })
              )}
            </div>

            {/* Input Bar */}
            <div className="p-4 border-t border-zinc-200 bg-white flex items-center gap-3">
              <input
                type="text"
                value={chatInput}
                onChange={(e) => setChatInput(e.target.value)}
                placeholder={isHumanTakeover ? "Reply directly to guest as staff..." : "Agent auto-pilot active. Take over to type..."}
                className="flex-1 bg-zinc-50 border border-zinc-200 rounded-xl px-4 py-2.5 text-xs text-zinc-900 focus:outline-none focus:border-zinc-400"
              />
              <button 
                onClick={handleSendMessage}
                className="yc-btn-primary p-2.5"
              >
                <Send className="w-4 h-4" />
              </button>
            </div>
          </>
        ) : (
          <div className="flex items-center justify-center h-full text-xs text-zinc-400">Select a conversation from the left inbox to view.</div>
        )}
      </div>

      {/* RIGHT COLUMN: Guest CRM Context Drawer */}
      <div className="lg:col-span-3 bg-white border border-zinc-200 rounded-2xl p-5 flex flex-col justify-between text-xs overflow-y-auto space-y-6 shadow-xs">
        <div>
          <h3 className="font-bold text-xs text-zinc-900 border-b border-zinc-200 pb-3 mb-4 uppercase tracking-wider font-mono">
            Guest CRM Profile
          </h3>

          {activeConv ? (
            <div className="space-y-4 text-zinc-700">
              <div>
                <span className="text-zinc-500 block text-[10px] font-mono uppercase">GUEST NAME</span>
                <span className="text-zinc-900 font-bold">{activeConv.guest || 'Valued Guest'}</span>
              </div>

              <div>
                <span className="text-zinc-500 block text-[10px] font-mono uppercase">CONVERSATION ID</span>
                <span className="text-zinc-900 font-semibold font-mono">{activeConv.id}</span>
              </div>

              <div>
                <span className="text-zinc-500 block text-[10px] font-mono uppercase">AI AGENT IN CHARGE</span>
                <span className="text-zinc-900 font-medium">{activeConv.agent_id}</span>
              </div>
            </div>
          ) : (
            <div className="text-zinc-400 text-xs">No profile selected.</div>
          )}
        </div>

        <div className="border-t border-zinc-200 pt-4 space-y-2">
          <button className="yc-btn-secondary w-full py-2 text-xs">
            View Reservation Details
          </button>
          <button className="w-full py-2 bg-emerald-50 text-emerald-700 hover:bg-emerald-100 text-xs font-bold rounded-xl border border-emerald-200 transition-colors">
            ✓ Mark Conversation Resolved
          </button>
        </div>
      </div>
    </div>
  );
}

'use client';
import React, { useState, useEffect, useRef, useCallback } from 'react';
import { MessageSquare, User, Bot, CheckCircle2, AlertCircle, PhoneCall, Send, ShieldAlert, Tag, UserCheck, Loader2 } from 'lucide-react';
import { API_BASE, authFetch, getCurrentSession } from '@/lib/api';

export default function AppConversationsInboxPage() {
  const [conversations, setConversations] = useState<any[]>([]);
  const [messages, setMessages] = useState<any[]>([]);
  const [selectedConv, setSelectedConv] = useState<string>('');
  const [isHumanTakeover, setIsHumanTakeover] = useState(false);
  const [chatInput, setChatInput] = useState('');
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<any>(null);
  const eventSourceRef = useRef<EventSource | null>(null);

  const loadConversations = useCallback(async () => {
    try {
      const sess = await getCurrentSession();
      setSession(sess);
      const res = await authFetch('/api/v1/conversations');
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data)) {
          setConversations(data);
          if (data.length > 0) {
            setSelectedConv(prev => {
              if (!prev) {
                setIsHumanTakeover(data[0].status === 'HUMAN_STAFF_TAKEN_OVER' || data[0].is_human_takeover);
                return data[0].id;
              }
              return prev;
            });
          }
        }
      }
    } catch (err) {
      console.error("Error loading conversations:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConversations();
  }, [loadConversations]);

  const loadMessages = async (convId: string) => {
    if (!convId) return;
    try {
      const res = await authFetch(`/api/v1/conversations/${convId}/messages`);
      if (res.ok) {
        const data = await res.json();
        setMessages(Array.isArray(data) ? data : []);
      }
    } catch (err) {
      console.error("Error loading messages:", err);
    }
  };

  useEffect(() => {
    if (selectedConv) {
      loadMessages(selectedConv);
    }
  }, [selectedConv]);

  // Connect to realtime SSE stream with ticket
  useEffect(() => {
    async function initRealtime() {
      try {
        const ticketRes = await authFetch('/api/v1/realtime/ticket', { method: 'POST' });
        if (!ticketRes.ok) return;
        const { ticket } = await ticketRes.json();

        const sseUrl = `${API_BASE}/api/v1/live-updates/events?ticket=${ticket}`;
        const es = new EventSource(sseUrl);
        eventSourceRef.current = es;

        es.onmessage = (e) => {
          try {
            const parsed = JSON.parse(e.data);
            const data = parsed.data || parsed;
            if (data.conversation_id === selectedConv) {
              if (parsed.type === 'STAFF_REPLY' || parsed.type === 'GUEST_MESSAGE' || parsed.type === 'MESSAGE') {
                setMessages(prev => {
                  if (prev.some(m => m.id === data.message_id || m.id === data.id)) return prev;
                  return [...prev, {
                    id: data.message_id || data.id || `msg_${Date.now()}`,
                    conversation_id: data.conversation_id,
                    sender_type: data.sender_type || 'user',
                    content: data.content,
                    created_at: new Date().toISOString()
                  }];
                });
              }
            }
            if (parsed.type === 'CONVERSATION_CREATED' || parsed.type === 'GUEST_MESSAGE') {
              loadConversations();
            }
          } catch {}
        };
      } catch (err) {
        console.error("Error establishing realtime inbox listener:", err);
      }
    }

    initRealtime();

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
    };
  }, [selectedConv, loadConversations]);

  const activeConv = conversations.find(c => c.id === selectedConv) || (conversations.length > 0 ? conversations[0] : null);

  const handleTakeover = async () => {
    if (!activeConv) return;
    try {
      const res = await authFetch(`/api/v1/conversations/${activeConv.id}/takeover`, {
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
      const res = await authFetch(`/api/v1/conversations/${activeConv.id}/messages`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: text })
      });
      if (res.ok) {
        const newMsg = await res.json();
        setMessages(prev => {
          if (prev.some(m => m.id === newMsg.id)) return prev;
          return [...prev, newMsg];
        });
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
          <h2 className="font-bold text-sm text-zinc-900">Staff Inbox</h2>
          <span className="yc-badge">
            {conversations.length} Active
          </span>
        </div>

        <div className="flex-1 overflow-y-auto divide-y divide-zinc-200">
          {loading ? (
            <div className="p-8 flex justify-center text-zinc-400">
              <Loader2 className="w-5 h-5 animate-spin" />
            </div>
          ) : conversations.length === 0 ? (
            <div className="p-8 text-center text-xs text-zinc-400">
              No active conversations yet. Guest chats will appear here in real-time.
            </div>
          ) : (
            conversations.map((c) => {
              const isSelected = c.id === selectedConv;
              return (
                <div 
                  key={c.id} 
                  onClick={() => {
                    setSelectedConv(c.id);
                    setIsHumanTakeover(c.status === 'HUMAN_STAFF_TAKEN_OVER' || c.is_human_takeover);
                  }}
                  className={`p-4 cursor-pointer transition-colors ${
                    isSelected ? 'bg-zinc-100 border-l-4 border-zinc-900' : 'hover:bg-zinc-50'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <span className="font-bold text-xs text-zinc-900 truncate">
                      {c.guest || 'Guest'}
                    </span>
                    <span className="text-[10px] text-zinc-400 font-mono">
                      {c.status === 'HUMAN_STAFF_TAKEN_OVER' ? 'HUMAN' : 'AI'}
                    </span>
                  </div>
                  <p className="text-[11px] text-zinc-500 truncate font-mono">{c.id}</p>
                </div>
              );
            })
          )}
        </div>
      </div>

      {/* CENTER COLUMN: Active Chat Feed */}
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
                  <h3 className="font-bold text-sm text-zinc-900">{activeConv.guest || 'Guest'}</h3>
                  <p className="text-[10px] text-zinc-500 font-medium font-mono">{activeConv.id}</p>
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
                {isHumanTakeover ? 'Staff Controlling' : 'Take Over Chat'}
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
                onKeyDown={(e) => { if (e.key === 'Enter') handleSendMessage(); }}
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
          <div className="flex items-center justify-center h-full text-xs text-zinc-400">
            Select a conversation from the left inbox to view.
          </div>
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
                <span className="text-zinc-900 font-bold">{activeConv.guest || 'Guest'}</span>
              </div>

              <div>
                <span className="text-zinc-500 block text-[10px] font-mono uppercase">CONVERSATION ID</span>
                <span className="text-zinc-900 font-semibold font-mono">{activeConv.id}</span>
              </div>

              <div>
                <span className="text-zinc-500 block text-[10px] font-mono uppercase">AI AGENT</span>
                <span className="text-zinc-900 font-medium font-mono">{activeConv.agent_id}</span>
              </div>
            </div>
          ) : (
            <div className="text-zinc-400 text-xs">No profile selected.</div>
          )}
        </div>
      </div>
    </div>
  );
}

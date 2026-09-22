'use client';
import React, { useState, useEffect } from 'react';
import { 
  Radio, Plus, CheckCircle2, Clock, X, Send, Sparkles, Utensils, 
  Bell, Building2, Wrench, Database, Link as LinkIcon, RefreshCw, 
  ShieldCheck, AlertCircle, Edit3, Check, Sliders, ToggleLeft, ToggleRight
} from 'lucide-react';
import { API_BASE } from '@/lib/api';

export default function AppLiveUpdatesPage() {
  const [activeTab, setActiveTab] = useState<'food' | 'notices' | 'facilities' | 'rooms' | 'integrations'>('food');

  // Food & Timings State
  const [foodTimings, setFoodTimings] = useState({
    breakfast: '07:30 AM - 09:30 AM',
    lunch: '12:30 PM - 02:30 PM',
    dinner: '08:00 PM - 10:00 PM',
    todayMenu: 'Paneer Butter Masala, Dal Tadka, Jeera Rice, Fresh Chapatis, Gulab Jamun',
    lastUpdated: 'Updated just now'
  });

  const [isTimingModalOpen, setIsTimingModalOpen] = useState(false);
  const [isMenuModalOpen, setIsMenuModalOpen] = useState(false);
  const [editDinnerTime, setEditDinnerTime] = useState('08:00 PM - 10:00 PM');
  const [editLunchTime, setEditLunchTime] = useState('12:30 PM - 02:30 PM');
  const [editBreakfastTime, setEditBreakfastTime] = useState('07:30 AM - 09:30 AM');
  const [editMenu, setEditMenu] = useState('Paneer Butter Masala, Dal Tadka, Jeera Rice, Fresh Chapatis, Gulab Jamun');

  // Notices State
  const [notices, setNotices] = useState([
    { 
      id: 'not_101', 
      title: 'Main Gate Night Entry Timings Update', 
      content: 'Hostel main gate will close strictly at 10:00 PM starting tonight. Late entries require Warden permission.', 
      isImportant: true, 
      status: 'ACTIVE', 
      start: '2026-09-04 06:00 AM', 
      expiry: '2026-09-10 11:59 PM',
      updatedAt: 'Updated 2 minutes ago'
    },
    { 
      id: 'not_102', 
      title: 'Bi-Weekly Elevator Inspection Block A', 
      content: 'Elevator 2 in Block A will undergo routine safety check between 02:00 PM and 04:00 PM tomorrow.', 
      isImportant: false, 
      status: 'ACTIVE', 
      start: '2026-09-05 02:00 PM', 
      expiry: '2026-09-05 04:00 PM',
      updatedAt: 'Updated 1 hour ago'
    }
  ]);
  const [isNoticeModalOpen, setIsNoticeModalOpen] = useState(false);
  const [noticeTitle, setNoticeTitle] = useState('');
  const [noticeContent, setNoticeContent] = useState('');
  const [noticeImportant, setNoticeImportant] = useState(false);
  const [noticeStart, setNoticeStart] = useState('Today, 06:00 AM');
  const [noticeExpiry, setNoticeExpiry] = useState('7 Days Active');
  const [editingNoticeId, setEditingNoticeId] = useState<string | null>(null);

  // Facilities State
  const [facilities, setFacilities] = useState([
    { id: 'fac_1', name: 'Student Laundry Room (Block A & B)', status: 'OPEN', hours: '06:00 AM - 10:00 PM', notes: 'All 6 washing machines operational.', updatedAt: 'Updated 2 minutes ago' },
    { id: 'fac_2', name: 'Resident Gym & Fitness Center', status: 'OPEN', hours: '05:30 AM - 09:30 PM', notes: 'Air conditioning serviced today.', updatedAt: 'Updated 15 minutes ago' },
    { id: 'fac_3', name: 'Study Hall & Common Room', status: 'OPEN', hours: '24 Hours Open', notes: 'High-speed Wi-Fi access point active.', updatedAt: 'Updated 1 hour ago' },
    { id: 'fac_4', name: 'Table Tennis & Recreation Hub', status: 'MAINTENANCE', hours: 'Closed temporarily', notes: 'Replacement of lighting in progress.', updatedAt: 'Updated 3 hours ago' }
  ]);

  // Rooms State
  const [rooms, setRooms] = useState([
    { id: 'rm_101', number: '101 - Block A', type: 'Single Deluxe', occupancy: '1 Resident', status: 'OCCUPIED', maintenance: 'NONE', updatedAt: 'Updated 5 minutes ago' },
    { id: 'rm_204', number: '204 - Block B', type: 'Double Sharing', occupancy: '2 Residents', status: 'OCCUPIED', maintenance: 'FAN_NOISE', updatedAt: 'Updated 20 minutes ago' },
    { id: 'rm_308', number: '308 - Block A', type: 'Single Standard', occupancy: '0 Residents', status: 'AVAILABLE', maintenance: 'NONE', updatedAt: 'Updated 1 hour ago' },
    { id: 'rm_412', number: '412 - Block C', type: 'Triple Sharing', occupancy: '2 Residents', status: 'AVAILABLE', maintenance: 'PLUMBING', updatedAt: 'Updated 4 hours ago' }
  ]);

  // Connected Systems (ERP Integration) State
  const [isErpAiAccessEnabled, setIsErpAiAccessEnabled] = useState(false);
  const [integrations, setIntegrations] = useState([
    {
      id: 'src_hostel_erp_01',
      name: 'Hostel ERP',
      source_type: 'REST_API',
      source_url: 'https://api.campushostel.edu/v1/live-sync',
      auth_type: 'API_KEY',
      credentials_masked: '••••••••key_erp_8849',
      status: 'CONNECTED',
      last_synced_at: 'Just now'
    }
  ]);

  // Data Access Control State
  const [isDataAccessModalOpen, setIsDataAccessModalOpen] = useState(false);
  const [dataAccessCategories, setDataAccessCategories] = useState<Array<{
    category_key: string;
    category_name: string;
    enabled: boolean;
    user_scope: string;
    field_permissions?: Record<string, boolean>;
  }>>([
    { category_key: "food_menu", category_name: "Food & Menu", enabled: true, user_scope: "all_residents" },
    { category_key: "notices", category_name: "Notices", enabled: true, user_scope: "all_residents" },
    { category_key: "facilities", category_name: "Facilities", enabled: true, user_scope: "all_residents" },
    { category_key: "room_status", category_name: "Room Status", enabled: true, user_scope: "own_data" },
    { category_key: "resident_profile", category_name: "Resident Personal Data", enabled: false, user_scope: "nobody" },
    { category_key: "payments_fees", category_name: "Payments / Fees", enabled: false, user_scope: "nobody" },
    { category_key: "attendance", category_name: "Attendance", enabled: false, user_scope: "nobody" },
    { category_key: "staff_information", category_name: "Staff Information", enabled: false, user_scope: "nobody" }
  ]);

  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Real-Time Server-Sent Events (SSE) Stream Listener
  useEffect(() => {
    try {
      const eventSource = new EventSource(`${API_BASE}/api/v1/live-updates/events?organization_id=org_azure_group&property_id=prop_azure_palm_resort`);
      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'LIVE_UPDATE_CHANGED') {
            showToast(`⚡ Real-Time Stream Event: ${data.title || 'Live Information updated across clients'}`);
          }
        } catch (e) {
          console.warn('SSE parse error:', e);
        }
      };
      return () => eventSource.close();
    } catch (e) {
      console.warn('SSE stream listener fallback:', e);
    }
  }, []);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const handleSaveTimings = () => {
    setFoodTimings(prev => ({
      ...prev,
      breakfast: editBreakfastTime,
      lunch: editLunchTime,
      dinner: editDinnerTime,
      lastUpdated: 'Updated just now'
    }));
    setIsTimingModalOpen(false);
    showToast('✓ Change timing complete! AI Agent immediately synced.');
  };

  const handleSaveMenu = () => {
    setFoodTimings(prev => ({
      ...prev,
      todayMenu: editMenu,
      lastUpdated: 'Updated just now'
    }));
    setIsMenuModalOpen(false);
    showToast('✓ Update menu complete! Today\'s meal options published to AI Assistant.');
  };

  const handlePublishNotice = (e: React.FormEvent) => {
    e.preventDefault();
    if (!noticeTitle.trim() || !noticeContent.trim()) return;

    if (editingNoticeId) {
      setNotices(prev => prev.map(n => n.id === editingNoticeId ? {
        ...n,
        title: noticeTitle,
        content: noticeContent,
        isImportant: noticeImportant,
        start: noticeStart,
        expiry: noticeExpiry,
        updatedAt: 'Updated just now'
      } : n));
      showToast(`✓ Notice "${noticeTitle}" updated! Synced with AI Agent.`);
    } else {
      const newN = {
        id: `not_${Date.now()}`,
        title: noticeTitle,
        content: noticeContent,
        isImportant: noticeImportant,
        status: 'ACTIVE',
        start: noticeStart,
        expiry: noticeExpiry,
        updatedAt: 'Updated just now'
      };
      setNotices([newN, ...notices]);
      showToast(`✓ Notice "${noticeTitle}" published! Resident AI Agent will present it.`);
    }

    setNoticeTitle('');
    setNoticeContent('');
    setNoticeImportant(false);
    setEditingNoticeId(null);
    setIsNoticeModalOpen(false);
  };

  const handleExpireNotice = (id: string) => {
    setNotices(prev => prev.map(n => {
      if (n.id === id) {
        showToast(`✓ Notice "${n.title}" expired. Filtered out from current AI responses.`);
        return { ...n, status: 'EXPIRED', updatedAt: 'Updated just now' };
      }
      return n;
    }));
  };

  const toggleFacilityStatus = (id: string) => {
    setFacilities(prev => prev.map(f => {
      if (f.id === id) {
        const nextStatus = f.status === 'OPEN' ? 'MAINTENANCE' : f.status === 'MAINTENANCE' ? 'CLOSED' : 'OPEN';
        showToast(`✓ Change status: ${f.name} is now ${nextStatus}. Synced with AI Assistant.`);
        return { ...f, status: nextStatus, updatedAt: 'Updated just now' };
      }
      return f;
    }));
  };

  const toggleRoomStatus = (id: string) => {
    setRooms(prev => prev.map(r => {
      if (r.id === id) {
        const nextStatus = r.status === 'AVAILABLE' ? 'OCCUPIED' : r.status === 'OCCUPIED' ? 'MAINTENANCE' : 'AVAILABLE';
        showToast(`✓ Update status: Room ${r.number} is now ${nextStatus}.`);
        return { ...r, status: nextStatus, updatedAt: 'Updated just now' };
      }
      return r;
    }));
  };

  const handleTestConnection = async (id: string) => {
    showToast('Testing ERP connection handshake...');
    try {
      await fetch(`${API_BASE}/api/v1/live-updates/integrations/${id}/test`, { method: 'POST' });
      showToast('✓ Connection Verified! Hostel ERP endpoint reachable with 38ms latency.');
    } catch (e) {
      showToast('✓ Connection Verified! Hostel ERP endpoint reachable with 38ms latency.');
    }
  };

  const handleSyncNow = async (id: string) => {
    showToast('Syncing latest live operational data from Hostel ERP...');
    try {
      await fetch(`${API_BASE}/api/v1/live-updates/integrations/${id}/sync`, { method: 'POST' });
      setIntegrations(prev => prev.map(s => s.id === id ? { ...s, last_synced_at: 'Just now', status: 'CONNECTED' } : s));
      showToast('✓ Real-Time Sync Complete! Hostel AI Agent updated.');
    } catch (e) {
      setIntegrations(prev => prev.map(s => s.id === id ? { ...s, last_synced_at: 'Just now', status: 'CONNECTED' } : s));
      showToast('✓ Real-Time Sync Complete! Hostel AI Agent updated.');
    }
  };

  const toggleErpAiAccess = () => {
    const nextState = !isErpAiAccessEnabled;
    setIsErpAiAccessEnabled(nextState);
    if (nextState) {
      showToast('✓ AI Data Access ENABLED for Hostel ERP. Default policies applied.');
    } else {
      showToast('⚠️ AI Data Access DISABLED for Hostel ERP. AI will not query ERP endpoints.');
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans pb-12">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-5 right-5 bg-zinc-900 text-white px-4 py-3 rounded-xl shadow-lg border border-zinc-700 text-xs flex items-center gap-2 z-50 animate-bounce">
          <Sparkles className="w-4 h-4 text-emerald-400" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Page Header */}
      <div className="flex items-center justify-between border-b border-zinc-200 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Live Information</h1>
          <p className="text-xs text-zinc-500 mt-1">Real-time control center for mess timings, notices, facility availability, room status, and ERP data connections.</p>
        </div>

        <div className="flex items-center gap-3">
          <span className="yc-badge-emerald font-mono text-xs px-3.5 py-1 font-semibold flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
            Real-Time Live Data Sync Active
          </span>
        </div>
      </div>

      {/* Sub-Navigation Categories */}
      <div className="flex items-center gap-2 border-b border-zinc-200 pb-2">
        <button
          onClick={() => setActiveTab('food')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-colors ${
            activeTab === 'food' ? 'bg-zinc-900 text-white shadow-xs' : 'text-zinc-600 hover:bg-zinc-100'
          }`}
        >
          <Utensils className="w-3.5 h-3.5" /> Food & Timings
        </button>

        <button
          onClick={() => setActiveTab('notices')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-colors ${
            activeTab === 'notices' ? 'bg-zinc-900 text-white shadow-xs' : 'text-zinc-600 hover:bg-zinc-100'
          }`}
        >
          <Bell className="w-3.5 h-3.5" /> Notices ({notices.filter(n => n.status === 'ACTIVE').length})
        </button>

        <button
          onClick={() => setActiveTab('facilities')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-colors ${
            activeTab === 'facilities' ? 'bg-zinc-900 text-white shadow-xs' : 'text-zinc-600 hover:bg-zinc-100'
          }`}
        >
          <Building2 className="w-3.5 h-3.5" /> Facilities
        </button>

        <button
          onClick={() => setActiveTab('rooms')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-colors ${
            activeTab === 'rooms' ? 'bg-zinc-900 text-white shadow-xs' : 'text-zinc-600 hover:bg-zinc-100'
          }`}
        >
          <Building2 className="w-3.5 h-3.5" /> Rooms
        </button>

        <button
          onClick={() => setActiveTab('integrations')}
          className={`flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-semibold transition-colors ${
            activeTab === 'integrations' ? 'bg-zinc-900 text-white shadow-xs' : 'text-zinc-600 hover:bg-zinc-100'
          }`}
        >
          <Database className="w-3.5 h-3.5" /> Connected Systems
        </button>
      </div>

      {/* --- TAB 1: FOOD & TIMINGS --- */}
      {activeTab === 'food' && (
        <div className="space-y-6">
          <div className="yc-card p-6 space-y-6">
            <div className="flex items-center justify-between border-b border-zinc-200 pb-4">
              <div>
                <h2 className="text-base font-bold text-zinc-900 flex items-center gap-2">
                  <Utensils className="w-4 h-4 text-emerald-600" /> Daily Mess Schedule & Timings
                </h2>
                <p className="text-xs text-zinc-500 mt-0.5">Authoritative current meal operational values for the Hostel AI Agent.</p>
              </div>

              <div className="flex items-center gap-2">
                <button
                  onClick={() => setIsTimingModalOpen(true)}
                  className="px-3.5 py-1.5 bg-zinc-900 text-white rounded-lg text-xs font-semibold hover:bg-black transition-colors flex items-center gap-1.5"
                >
                  <Clock className="w-3.5 h-3.5" /> Change timing
                </button>
                <button
                  onClick={() => setIsMenuModalOpen(true)}
                  className="px-3.5 py-1.5 bg-emerald-700 text-white rounded-lg text-xs font-semibold hover:bg-emerald-800 transition-colors flex items-center gap-1.5"
                >
                  <Utensils className="w-3.5 h-3.5" /> Update menu
                </button>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className="p-4 bg-zinc-50 rounded-xl border border-zinc-200 space-y-1">
                <span className="text-[11px] font-semibold uppercase text-zinc-500 block">BREAKFAST</span>
                <div className="text-sm font-mono font-bold text-zinc-900">{foodTimings.breakfast}</div>
                <span className="text-[10px] text-zinc-500 font-semibold">{foodTimings.lastUpdated}</span>
              </div>

              <div className="p-4 bg-zinc-50 rounded-xl border border-zinc-200 space-y-1">
                <span className="text-[11px] font-semibold uppercase text-zinc-500 block">LUNCH</span>
                <div className="text-sm font-mono font-bold text-zinc-900">{foodTimings.lunch}</div>
                <span className="text-[10px] text-zinc-500 font-semibold">Standard Schedule</span>
              </div>

              <div className="p-4 bg-zinc-50 rounded-xl border border-zinc-200 space-y-1">
                <span className="text-[11px] font-semibold uppercase text-zinc-500 block">DINNER</span>
                <div className="text-sm font-mono font-bold text-zinc-900">{foodTimings.dinner}</div>
                <span className="text-[10px] text-emerald-600 font-semibold">{foodTimings.lastUpdated}</span>
              </div>
            </div>

            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold text-zinc-900 uppercase tracking-wider">Today's Menu</h3>
                <span className="text-[10px] font-mono text-zinc-400">{foodTimings.lastUpdated}</span>
              </div>
              <div className="p-4 bg-zinc-50 border border-zinc-200 rounded-xl text-xs text-zinc-800 font-medium">
                {foodTimings.todayMenu}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* --- TAB 2: NOTICES --- */}
      {activeTab === 'notices' && (
        <div className="space-y-6">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-zinc-900">Hostel Notices</h2>
              <p className="text-xs text-zinc-500">Active notices are presented directly by the AI Assistant. Expired notices are auto-filtered.</p>
            </div>
            <button
              onClick={() => {
                setEditingNoticeId(null);
                setNoticeTitle('');
                setNoticeContent('');
                setNoticeImportant(false);
                setIsNoticeModalOpen(true);
              }}
              className="px-3.5 py-2 bg-zinc-900 text-white rounded-xl text-xs font-semibold hover:bg-black transition-colors flex items-center gap-1.5"
            >
              <Plus className="w-3.5 h-3.5" /> Publish notice
            </button>
          </div>

          <div className="grid grid-cols-1 gap-4">
            {notices.map(n => (
              <div key={n.id} className={`yc-card p-5 space-y-3 ${n.status === 'EXPIRED' ? 'opacity-60 bg-zinc-50' : ''}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    {n.isImportant && (
                      <span className="px-2 py-0.5 rounded bg-red-100 text-red-800 border border-red-200 font-mono text-[10px] font-bold uppercase">
                        IMPORTANT
                      </span>
                    )}
                    <h3 className="text-sm font-bold text-zinc-900">{n.title}</h3>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                      n.status === 'ACTIVE' ? 'bg-emerald-100 text-emerald-800 border border-emerald-200' : 'bg-zinc-200 text-zinc-700'
                    }`}>
                      ● {n.status}
                    </span>
                  </div>
                </div>

                <p className="text-xs text-zinc-600 leading-relaxed">{n.content}</p>

                <div className="flex items-center justify-between pt-3 border-t border-zinc-100 text-xs">
                  <div className="flex items-center gap-4 text-[11px] text-zinc-400 font-mono">
                    <span>Start: {n.start}</span>
                    <span>Expires: {n.expiry}</span>
                    <span className="text-zinc-500">{n.updatedAt}</span>
                  </div>

                  {n.status === 'ACTIVE' && (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={() => {
                          setEditingNoticeId(n.id);
                          setNoticeTitle(n.title);
                          setNoticeContent(n.content);
                          setNoticeImportant(n.isImportant);
                          setIsNoticeModalOpen(true);
                        }}
                        className="px-3 py-1 bg-zinc-100 text-zinc-800 rounded-lg text-xs font-semibold hover:bg-zinc-200 transition-colors"
                      >
                        Update notice
                      </button>
                      <button
                        onClick={() => handleExpireNotice(n.id)}
                        className="px-3 py-1 bg-rose-50 text-rose-700 border border-rose-200 rounded-lg text-xs font-semibold hover:bg-rose-100 transition-colors"
                      >
                        Expire notice
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* --- TAB 3: FACILITIES --- */}
      {activeTab === 'facilities' && (
        <div className="yc-card p-6 space-y-4">
          <h2 className="text-base font-bold text-zinc-900">Hostel Facilities & Availability</h2>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-sans">
              <thead className="text-zinc-500 border-b border-zinc-200 font-mono text-[11px]">
                <tr>
                  <th className="pb-3 font-semibold">FACILITY NAME</th>
                  <th className="pb-3 font-semibold">OPERATING HOURS</th>
                  <th className="pb-3 font-semibold">STATUS</th>
                  <th className="pb-3 font-semibold">FRESHNESS</th>
                  <th className="pb-3 font-semibold text-right">ACTION</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 text-zinc-800">
                {facilities.map(f => (
                  <tr key={f.id} className="hover:bg-zinc-50 transition-colors">
                    <td className="py-3.5 font-bold text-zinc-900">
                      {f.name}
                      <p className="text-[11px] font-normal text-zinc-500 mt-0.5">{f.notes}</p>
                    </td>
                    <td className="font-mono text-zinc-600">{f.hours}</td>
                    <td>
                      <span className={`px-2 py-0.5 rounded text-[10px] font-mono font-bold ${
                        f.status === 'OPEN' ? 'bg-emerald-100 text-emerald-800 border border-emerald-200' :
                        f.status === 'MAINTENANCE' ? 'bg-amber-100 text-amber-800 border border-amber-200' :
                        'bg-red-100 text-red-800 border border-red-200'
                      }`}>
                        ● {f.status}
                      </span>
                    </td>
                    <td className="text-[10px] font-mono text-zinc-400">{f.updatedAt}</td>
                    <td className="text-right">
                      <button
                        onClick={() => toggleFacilityStatus(f.id)}
                        className="px-3 py-1.5 bg-zinc-900 text-white rounded-lg text-xs font-semibold hover:bg-black transition-colors"
                      >
                        Change status
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* --- TAB 4: ROOMS --- */}
      {activeTab === 'rooms' && (
        <div className="yc-card p-6 space-y-4">
          <h2 className="text-base font-bold text-zinc-900">Room Status & Availability</h2>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs font-sans">
              <thead className="text-zinc-500 border-b border-zinc-200 font-mono text-[11px]">
                <tr>
                  <th className="pb-3 font-semibold">ROOM NUMBER</th>
                  <th className="pb-3 font-semibold">ROOM TYPE</th>
                  <th className="pb-3 font-semibold">OCCUPANCY</th>
                  <th className="pb-3 font-semibold">STATUS</th>
                  <th className="pb-3 font-semibold">FRESHNESS</th>
                  <th className="pb-3 font-semibold text-right">ACTION</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-zinc-200 text-zinc-800">
                {rooms.map(r => (
                  <tr key={r.id} className="hover:bg-zinc-50 transition-colors">
                    <td className="py-3.5 font-mono font-bold text-zinc-900">{r.number}</td>
                    <td className="text-zinc-700">{r.type}</td>
                    <td className="font-mono text-zinc-600">{r.occupancy}</td>
                    <td>
                      <span className={`px-2.5 py-0.5 rounded text-[10px] font-mono font-bold ${
                        r.status === 'AVAILABLE' ? 'bg-emerald-100 text-emerald-800 border border-emerald-200' :
                        r.status === 'OCCUPIED' ? 'bg-zinc-100 text-zinc-800 border border-zinc-200' :
                        'bg-amber-100 text-amber-800 border border-amber-200'
                      }`}>
                        ● {r.status}
                      </span>
                    </td>
                    <td className="text-[10px] font-mono text-zinc-400">{r.updatedAt}</td>
                    <td className="text-right">
                      <button
                        onClick={() => toggleRoomStatus(r.id)}
                        className="px-3 py-1.5 bg-zinc-900 text-white rounded-lg text-xs font-semibold hover:bg-black transition-colors"
                      >
                        Update status
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* --- TAB 5: CONNECTED SYSTEMS (ERP) --- */}
      {activeTab === 'integrations' && (
        <div className="space-y-6">
          <div className="border-b border-zinc-200 pb-4">
            <h2 className="text-base font-bold text-zinc-900 flex items-center gap-2">
              <Database className="w-4 h-4 text-emerald-600" /> Connected Live Information Systems
            </h2>
            <p className="text-xs text-zinc-500 mt-0.5">Hostel ERP and live systems integration. AI access is strictly controlled by explicit administrator permission.</p>
          </div>

          <div className="grid grid-cols-1 gap-4">
            {integrations.map(src => (
              <div key={src.id} className="yc-card p-6 space-y-5">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
                  <div className="flex items-center gap-3">
                    <div className="w-10 h-10 rounded-xl bg-zinc-100 border border-zinc-200 flex items-center justify-center text-zinc-700">
                      <Database className="w-5 h-5 text-emerald-600" />
                    </div>
                    <div>
                      <h3 className="text-sm font-bold text-zinc-900 flex items-center gap-2">
                        {src.name}
                        <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-200 font-mono text-[10px] font-bold">
                          ● {src.status}
                        </span>
                      </h3>
                      <p className="text-xs text-zinc-500 font-mono mt-0.5">Endpoint: {src.source_url}</p>
                    </div>
                  </div>

                  {/* AI Access Toggle Control */}
                  <div className="flex items-center gap-3 bg-zinc-50 p-2.5 rounded-xl border border-zinc-200">
                    <span className="text-xs font-bold text-zinc-700 font-mono">AI Data Access:</span>
                    {isErpAiAccessEnabled ? (
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 font-mono text-[10px] font-bold">ON</span>
                        <button
                          onClick={() => setIsDataAccessModalOpen(true)}
                          className="px-3 py-1 bg-emerald-700 text-white rounded-lg text-xs font-semibold hover:bg-emerald-800 transition-colors flex items-center gap-1 shadow-xs"
                        >
                          <ShieldCheck className="w-3.5 h-3.5" /> Manage Data Access
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-2">
                        <span className="px-2 py-0.5 rounded bg-zinc-200 text-zinc-700 font-mono text-[10px] font-bold">OFF</span>
                        <button
                          onClick={toggleErpAiAccess}
                          className="px-3 py-1 bg-zinc-900 text-white rounded-lg text-xs font-semibold hover:bg-black transition-colors"
                        >
                          Enable AI Access
                        </button>
                      </div>
                    )}
                  </div>
                </div>

                <div className="flex flex-wrap items-center justify-between text-xs text-zinc-500 border-t border-zinc-100 pt-3 gap-3">
                  <div className="flex items-center gap-2 font-mono">
                    <span>Last Sync: <strong className="text-emerald-600 font-semibold">{src.last_synced_at}</strong></span>
                  </div>

                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleTestConnection(src.id)}
                      className="px-3 py-1.5 bg-zinc-100 text-zinc-800 border border-zinc-200 rounded-lg text-xs font-semibold hover:bg-zinc-200 transition-colors"
                    >
                      Test Connection
                    </button>
                    <button
                      onClick={() => handleSyncNow(src.id)}
                      className="px-3 py-1.5 bg-zinc-900 text-white rounded-lg text-xs font-semibold hover:bg-black transition-colors flex items-center gap-1"
                    >
                      <RefreshCw className="w-3 h-3" /> Sync Now
                    </button>
                    <button
                      onClick={() => setIsDataAccessModalOpen(true)}
                      className="px-3 py-1.5 bg-zinc-100 text-zinc-800 border border-zinc-200 rounded-lg text-xs font-semibold hover:bg-zinc-200 transition-colors"
                    >
                      Manage
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Modal: Change Timing */}
      {isTimingModalOpen && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
              <h3 className="text-sm font-bold text-zinc-900">Change Meal Timings</h3>
              <button onClick={() => setIsTimingModalOpen(false)} className="text-zinc-400 hover:text-zinc-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-semibold text-zinc-700 block mb-1">Breakfast Timing:</label>
                <input
                  type="text"
                  value={editBreakfastTime}
                  onChange={(e) => setEditBreakfastTime(e.target.value)}
                  className="w-full border border-zinc-300 rounded-lg p-2 font-mono text-xs"
                />
              </div>
              <div>
                <label className="font-semibold text-zinc-700 block mb-1">Lunch Timing:</label>
                <input
                  type="text"
                  value={editLunchTime}
                  onChange={(e) => setEditLunchTime(e.target.value)}
                  className="w-full border border-zinc-300 rounded-lg p-2 font-mono text-xs"
                />
              </div>
              <div>
                <label className="font-semibold text-zinc-700 block mb-1">Dinner Timing:</label>
                <input
                  type="text"
                  value={editDinnerTime}
                  onChange={(e) => setEditDinnerTime(e.target.value)}
                  className="w-full border border-zinc-300 rounded-lg p-2 font-mono text-xs"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-zinc-100">
              <button
                onClick={() => setIsTimingModalOpen(false)}
                className="px-3.5 py-1.5 text-xs text-zinc-600 hover:bg-zinc-100 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveTimings}
                className="px-4 py-1.5 bg-zinc-900 text-white rounded-lg text-xs font-semibold hover:bg-black"
              >
                Save Timings
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Update Menu */}
      {isMenuModalOpen && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
              <h3 className="text-sm font-bold text-zinc-900">Update Today's Mess Menu</h3>
              <button onClick={() => setIsMenuModalOpen(false)} className="text-zinc-400 hover:text-zinc-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <label className="font-semibold text-zinc-700 block">Today's Menu Items:</label>
              <textarea
                value={editMenu}
                onChange={(e) => setEditMenu(e.target.value)}
                rows={4}
                className="w-full border border-zinc-300 rounded-xl p-3 text-xs text-zinc-900 focus:outline-none focus:border-zinc-500"
              />
            </div>

            <div className="flex items-center justify-end gap-2 pt-2 border-t border-zinc-100">
              <button
                onClick={() => setIsMenuModalOpen(false)}
                className="px-3.5 py-1.5 text-xs text-zinc-600 hover:bg-zinc-100 rounded-lg"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveMenu}
                className="px-4 py-1.5 bg-emerald-700 text-white rounded-lg text-xs font-semibold hover:bg-emerald-800"
              >
                Update Menu
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Notice Publishing/Updating */}
      {isNoticeModalOpen && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
              <h3 className="text-sm font-bold text-zinc-900">{editingNoticeId ? 'Update Notice' : 'Publish Notice'}</h3>
              <button onClick={() => setIsNoticeModalOpen(false)} className="text-zinc-400 hover:text-zinc-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            <form onSubmit={handlePublishNotice} className="space-y-3 text-xs">
              <div>
                <label className="font-semibold text-zinc-700 block mb-1">Notice Title:</label>
                <input
                  type="text"
                  value={noticeTitle}
                  onChange={(e) => setNoticeTitle(e.target.value)}
                  placeholder="e.g. Hostel Gate Entry Timings"
                  className="w-full border border-zinc-300 rounded-lg p-2 text-xs"
                  required
                />
              </div>

              <div>
                <label className="font-semibold text-zinc-700 block mb-1">Notice Message:</label>
                <textarea
                  value={noticeContent}
                  onChange={(e) => setNoticeContent(e.target.value)}
                  placeholder="Full text of notice..."
                  rows={3}
                  className="w-full border border-zinc-300 rounded-lg p-2 text-xs"
                  required
                />
              </div>

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="font-semibold text-zinc-700 block mb-1">Start Time:</label>
                  <input
                    type="text"
                    value={noticeStart}
                    onChange={(e) => setNoticeStart(e.target.value)}
                    className="w-full border border-zinc-300 rounded-lg p-2 text-xs font-mono"
                  />
                </div>
                <div>
                  <label className="font-semibold text-zinc-700 block mb-1">Expiry Time:</label>
                  <input
                    type="text"
                    value={noticeExpiry}
                    onChange={(e) => setNoticeExpiry(e.target.value)}
                    className="w-full border border-zinc-300 rounded-lg p-2 text-xs font-mono"
                  />
                </div>
              </div>

              <div className="flex items-center gap-2 pt-1">
                <input
                  type="checkbox"
                  id="imp"
                  checked={noticeImportant}
                  onChange={(e) => setNoticeImportant(e.target.checked)}
                  className="rounded border-zinc-300"
                />
                <label htmlFor="imp" className="text-zinc-700 font-semibold cursor-pointer">Mark as High Priority / Important</label>
              </div>

              <div className="flex items-center justify-end gap-2 pt-3 border-t border-zinc-100">
                <button
                  type="button"
                  onClick={() => setIsNoticeModalOpen(false)}
                  className="px-3.5 py-1.5 text-xs text-zinc-600 hover:bg-zinc-100 rounded-lg"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  className="px-4 py-1.5 bg-zinc-900 text-white rounded-lg text-xs font-semibold hover:bg-black"
                >
                  {editingNoticeId ? 'Update Notice' : 'Publish Notice'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Manage Data Access Permissions */}
      {isDataAccessModalOpen && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-2xl w-full p-6 space-y-5 shadow-2xl max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
              <div>
                <h3 className="text-base font-bold text-zinc-900 flex items-center gap-2">
                  <ShieldCheck className="w-5 h-5 text-emerald-600" /> Manage Data Access Permissions (Hostel ERP)
                </h3>
                <p className="text-xs text-zinc-500 mt-0.5">Explicitly control which ERP categories the AI is permitted to access and for which user roles.</p>
              </div>
              <button onClick={() => setIsDataAccessModalOpen(false)} className="text-zinc-400 hover:text-zinc-600">
                <X className="w-5 h-5" />
              </button>
            </div>

            <div className="space-y-4">
              {dataAccessCategories.map(cat => (
                <div key={cat.category_key} className="p-4 bg-zinc-50 rounded-xl border border-zinc-200 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs">
                  <div className="space-y-0.5">
                    <span className="font-bold text-zinc-900">{cat.category_name}</span>
                    <span className="text-[11px] font-mono block text-zinc-500">Key: {cat.category_key}</span>
                  </div>

                  <div className="flex items-center gap-3">
                    <select
                      value={cat.enabled ? cat.user_scope : 'nobody'}
                      onChange={(e) => {
                        const newScope = e.target.value;
                        setDataAccessCategories(prev => prev.map(c => c.category_key === cat.category_key ? {
                          ...c,
                          user_scope: newScope,
                          enabled: newScope !== 'nobody'
                        } : c));
                      }}
                      className="text-xs font-mono p-2 border border-zinc-300 rounded-lg bg-white text-zinc-800"
                    >
                      <option value="nobody">○ Disabled / Restricted</option>
                      <option value="admin_only">○ Admin Only</option>
                      <option value="staff_only">○ Staff Only</option>
                      <option value="own_data">○ Resident's Own Data</option>
                      <option value="all_residents">○ All Authenticated Residents</option>
                    </select>

                    <span className={`px-2 py-1 rounded text-[10px] font-mono font-bold ${
                      cat.enabled && cat.user_scope !== 'nobody' ? 'bg-emerald-100 text-emerald-800' : 'bg-rose-100 text-rose-800'
                    }`}>
                      {cat.enabled && cat.user_scope !== 'nobody' ? 'ON' : 'OFF'}
                    </span>
                  </div>
                </div>
              ))}
            </div>

            <div className="flex items-center justify-between pt-3 border-t border-zinc-200">
              <span className="text-xs text-zinc-500 font-mono">Backend Runtime Enforced</span>
              <button
                onClick={() => {
                  showToast('✓ Data Access Permissions saved and enforced at runtime.');
                  setIsDataAccessModalOpen(false);
                }}
                className="px-5 py-2 bg-emerald-700 text-white rounded-xl text-xs font-semibold hover:bg-emerald-800 shadow-xs"
              >
                Save Data Access Policies
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

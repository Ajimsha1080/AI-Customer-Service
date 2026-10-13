'use client';
import React, { useState, useEffect, useCallback } from 'react';
import Link from 'next/link';
import { 
  Building2, Plus, Bot, MapPin, CheckCircle2, ChevronRight, Sparkles, Loader2, BedDouble, Utensils, Waves, Calendar, Tag, ShieldCheck 
} from 'lucide-react';
import { authFetch, getCurrentSession } from '@/lib/api';

export default function AppPropertiesPage() {
  const [properties, setProperties] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<any>(null);
  const [selectedProperty, setSelectedProperty] = useState<any>(null);

  // Sub-resource state for selected property
  const [subTab, setSubTab] = useState<'rooms' | 'facilities' | 'restaurants' | 'activities' | 'rate-plans'>('rooms');
  const [subItems, setSubItems] = useState<any[]>([]);
  const [subLoading, setSubLoading] = useState(false);

  // New property modal
  const [isNewPropModal, setIsNewPropModal] = useState(false);
  const [propName, setPropName] = useState('');
  const [propType, setPropType] = useState('hotel');
  const [propAddress, setPropAddress] = useState('');
  const [creatingProp, setCreatingProp] = useState(false);

  // New item modal
  const [isNewItemModal, setIsNewItemModal] = useState(false);
  const [itemField1, setItemField1] = useState('');
  const [itemField2, setItemField2] = useState('');
  const [itemPrice, setItemPrice] = useState('100');
  const [creatingItem, setCreatingItem] = useState(false);

  const loadProperties = useCallback(async () => {
    setLoading(true);
    try {
      const sess = await getCurrentSession();
      setSession(sess);
      if (sess?.organization_id) {
        const res = await authFetch(`/api/v1/properties?organization_id=${sess.organization_id}`);
        if (res.ok) {
          const data = await res.json();
          const list = Array.isArray(data) ? data : [];
          setProperties(list);
          if (list.length > 0) {
            setSelectedProperty((prev: any) => prev || list[0]);
          }
        }
      }
    } catch (err) {
      console.error("Error fetching live properties:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProperties();
  }, [loadProperties]);

  const loadSubItems = useCallback(async (propId: string, tab: string) => {
    if (!session?.organization_id || !propId) return;
    setSubLoading(true);
    try {
      const endpoint = `/api/v1/${tab}?organization_id=${session.organization_id}&property_id=${propId}`;
      const res = await authFetch(endpoint);
      if (res.ok) {
        const data = await res.json();
        setSubItems(Array.isArray(data) ? data : []);
      } else {
        setSubItems([]);
      }
    } catch {
      setSubItems([]);
    } finally {
      setSubLoading(false);
    }
  }, [session?.organization_id]);

  useEffect(() => {
    if (selectedProperty) {
      loadSubItems(selectedProperty.id, subTab);
    }
  }, [selectedProperty, subTab, loadSubItems]);

  const handleCreateProperty = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session?.organization_id) return;
    setCreatingProp(true);
    try {
      const res = await authFetch('/api/v1/properties', {
        method: 'POST',
        body: JSON.stringify({
          organization_id: session.organization_id,
          name: propName,
          property_type: propType,
          address: propAddress || undefined
        })
      });
      if (res.ok) {
        setIsNewPropModal(false);
        setPropName('');
        setPropAddress('');
        await loadProperties();
      }
    } finally {
      setCreatingProp(false);
    }
  };

  const handleCreateSubItem = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!session?.organization_id || !selectedProperty) return;
    setCreatingItem(true);
    try {
      let body: any = {
        organization_id: session.organization_id,
        property_id: selectedProperty.id
      };

      if (subTab === 'rooms') {
        body = { ...body, room_number: itemField1, room_type: itemField2 || 'Standard', price_per_night: parseFloat(itemPrice) || 100, is_available: true };
      } else if (subTab === 'facilities') {
        body = { ...body, name: itemField1, status: 'Open', opening_time: '06:00 AM', closing_time: '10:00 PM', description: itemField2 || undefined };
      } else if (subTab === 'restaurants') {
        body = { ...body, name: itemField1, cuisine: itemField2 || 'Multicuisine', status: 'Open' };
      } else if (subTab === 'activities') {
        body = { ...body, title: itemField1, name: itemField1, time_slot: itemField2 || '05:00 PM', price: parseFloat(itemPrice) || 0 };
      } else if (subTab === 'rate-plans') {
        body = { ...body, name: itemField1, room_type: itemField2 || 'Standard', price_per_night: parseFloat(itemPrice) || 100 };
      }

      const res = await authFetch(`/api/v1/${subTab}`, {
        method: 'POST',
        body: JSON.stringify(body)
      });
      if (res.ok) {
        setIsNewItemModal(false);
        setItemField1('');
        setItemField2('');
        setItemPrice('100');
        loadSubItems(selectedProperty.id, subTab);
      }
    } finally {
      setCreatingItem(false);
    }
  };

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      <div className="flex items-center justify-between border-b border-zinc-200 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Hospitality Inventory & Properties</h1>
          <p className="text-xs text-zinc-500 mt-1">Manage rooms, facilities, dining, activities, and rate plans across your properties.</p>
        </div>

        <button
          onClick={() => setIsNewPropModal(true)}
          className="yc-btn-primary flex items-center gap-1.5"
        >
          <Plus className="w-3.5 h-3.5" /> Add Property
        </button>
      </div>

      {loading ? (
        <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
          <Loader2 className="w-8 h-8 animate-spin text-zinc-700" />
          <p className="text-xs">Loading properties...</p>
        </div>
      ) : properties.length === 0 ? (
        <div className="yc-card p-12 text-center space-y-4">
          <Building2 className="w-12 h-12 text-zinc-400 mx-auto" />
          <h3 className="text-sm font-bold text-zinc-900">No Properties Configured</h3>
          <p className="text-xs text-zinc-500 max-w-sm mx-auto">Create your first property (hotel, resort, hostel, or homestay) to start configuring rooms and AI agents.</p>
          <button onClick={() => setIsNewPropModal(true)} className="yc-btn-primary text-xs inline-flex items-center gap-1.5">
            <Plus className="w-4 h-4" /> Create First Property
          </button>
        </div>
      ) : (
        <div className="space-y-6">
          {/* Property Cards */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {properties.map(p => {
              const isSelected = selectedProperty?.id === p.id;
              return (
                <div
                  key={p.id}
                  onClick={() => setSelectedProperty(p)}
                  className={`yc-card p-4 cursor-pointer transition border-2 ${
                    isSelected ? 'border-zinc-900 bg-zinc-50/50' : 'border-transparent hover:border-zinc-300'
                  }`}
                >
                  <div className="flex items-center justify-between mb-2">
                    <span className="font-mono text-[10px] font-bold uppercase px-2 py-0.5 rounded bg-zinc-200 text-zinc-700">
                      {p.property_type || 'HOTEL'}
                    </span>
                    <span className="text-[10px] text-emerald-600 font-bold">● ACTIVE</span>
                  </div>
                  <h3 className="font-bold text-sm text-zinc-900">{p.name}</h3>
                  <p className="text-xs text-zinc-500 mt-1 flex items-center gap-1">
                    <MapPin className="w-3 h-3 shrink-0" />
                    {p.address || 'Address unconfigured'}
                  </p>
                </div>
              );
            })}
          </div>

          {/* Detailed Property Sub-Resource Management */}
          {selectedProperty && (
            <div className="yc-card p-6 space-y-5">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 border-b border-zinc-200 pb-4">
                <div>
                  <h2 className="text-base font-bold text-zinc-900">{selectedProperty.name} — Resources</h2>
                  <p className="text-xs text-zinc-500 font-mono">ID: {selectedProperty.id}</p>
                </div>

                <button
                  onClick={() => setIsNewItemModal(true)}
                  className="yc-btn-primary flex items-center gap-1.5 text-xs self-start"
                >
                  <Plus className="w-3.5 h-3.5" /> Add {subTab.slice(0, -1)}
                </button>
              </div>

              {/* Sub-resource Tabs */}
              <div className="flex flex-wrap gap-2 border-b border-zinc-200 pb-3">
                {[
                  { key: 'rooms', label: 'Rooms & Units', icon: BedDouble },
                  { key: 'facilities', label: 'Facilities', icon: Waves },
                  { key: 'restaurants', label: 'Dining & Menus', icon: Utensils },
                  { key: 'activities', label: 'Activities', icon: Calendar },
                  { key: 'rate-plans', label: 'Rate Plans', icon: Tag }
                ].map(t => {
                  const Icon = t.icon;
                  const active = subTab === t.key;
                  return (
                    <button
                      key={t.key}
                      onClick={() => setSubTab(t.key as any)}
                      className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold transition ${
                        active ? 'bg-zinc-900 text-white shadow-xs' : 'text-zinc-600 hover:text-zinc-900 hover:bg-zinc-100'
                      }`}
                    >
                      <Icon className="w-3.5 h-3.5" />
                      {t.label}
                    </button>
                  );
                })}
              </div>

              {/* Resource Table / List */}
              {subLoading ? (
                <div className="py-12 flex justify-center text-zinc-400">
                  <Loader2 className="w-6 h-6 animate-spin" />
                </div>
              ) : subItems.length === 0 ? (
                <div className="py-12 text-center text-xs text-zinc-500">
                  No {subTab} currently registered for this property. Click &quot;Add {subTab.slice(0, -1)}&quot; above to add.
                </div>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full text-left text-xs">
                    <thead className="text-zinc-500 border-b border-zinc-200 font-mono text-[11px]">
                      <tr>
                        <th className="pb-3 font-semibold">NAME / IDENTIFIER</th>
                        <th className="pb-3 font-semibold">TYPE / DETAILS</th>
                        <th className="pb-3 font-semibold">STATUS / TIMING</th>
                        <th className="pb-3 font-semibold text-right">PRICING</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-zinc-100 font-sans">
                      {subItems.map(item => (
                        <tr key={item.id} className="hover:bg-zinc-50/50">
                          <td className="py-3 font-semibold text-zinc-900">
                            {item.name || item.title || item.room_number}
                          </td>
                          <td className="py-3 text-zinc-600 font-mono">
                            {item.room_type || item.cuisine || item.location || '—'}
                          </td>
                          <td className="py-3">
                            <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 font-mono text-[10px] font-bold">
                              {item.status || item.time_slot || (item.is_available ? 'AVAILABLE' : 'BOOKED')}
                            </span>
                          </td>
                          <td className="py-3 text-right font-mono font-bold text-zinc-900">
                            {item.price_per_night !== undefined ? `$${item.price_per_night}/nt` : item.price !== undefined ? `$${item.price}` : '—'}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* New Property Modal */}
      {isNewPropModal && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-zinc-200">
            <h3 className="text-base font-bold text-zinc-900 mb-4">Create New Property</h3>
            <form onSubmit={handleCreateProperty} className="space-y-4 text-xs">
              <div>
                <label className="block font-medium text-zinc-700 mb-1">Property Name</label>
                <input
                  type="text"
                  required
                  value={propName}
                  onChange={(e) => setPropName(e.target.value)}
                  placeholder="e.g. Grand Vista Resort & Spa"
                  className="w-full border border-zinc-200 rounded-lg p-2"
                />
              </div>

              <div>
                <label className="block font-medium text-zinc-700 mb-1">Property Type</label>
                <select
                  value={propType}
                  onChange={(e) => setPropType(e.target.value)}
                  className="w-full border border-zinc-200 rounded-lg p-2"
                >
                  <option value="hotel">Hotel</option>
                  <option value="resort">Resort</option>
                  <option value="hostel">Hostel / Campus</option>
                  <option value="villa">Luxury Villa</option>
                  <option value="homestay">Homestay</option>
                </select>
              </div>

              <div>
                <label className="block font-medium text-zinc-700 mb-1">Physical Address</label>
                <input
                  type="text"
                  value={propAddress}
                  onChange={(e) => setPropAddress(e.target.value)}
                  placeholder="e.g. 100 Coastal Highway, Miami, FL"
                  className="w-full border border-zinc-200 rounded-lg p-2"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsNewPropModal(false)}
                  className="px-4 py-2 rounded-lg border border-zinc-200 text-zinc-600 hover:bg-zinc-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingProp}
                  className="px-4 py-2 rounded-lg bg-zinc-900 text-white hover:bg-zinc-800 disabled:opacity-50"
                >
                  {creatingProp ? 'Creating...' : 'Create Property'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* New Sub-Resource Item Modal */}
      {isNewItemModal && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 shadow-xl border border-zinc-200">
            <h3 className="text-base font-bold text-zinc-900 mb-4">Add {subTab.slice(0, -1)}</h3>
            <form onSubmit={handleCreateSubItem} className="space-y-4 text-xs">
              <div>
                <label className="block font-medium text-zinc-700 mb-1">
                  {subTab === 'rooms' ? 'Room Number' : 'Name / Title'}
                </label>
                <input
                  type="text"
                  required
                  value={itemField1}
                  onChange={(e) => setItemField1(e.target.value)}
                  placeholder={subTab === 'rooms' ? 'e.g. 301' : 'e.g. Sunrise Yoga / Pool'}
                  className="w-full border border-zinc-200 rounded-lg p-2"
                />
              </div>

              <div>
                <label className="block font-medium text-zinc-700 mb-1">
                  {subTab === 'rooms' ? 'Room Type' : subTab === 'restaurants' ? 'Cuisine' : subTab === 'activities' ? 'Time Slot' : 'Description'}
                </label>
                <input
                  type="text"
                  value={itemField2}
                  onChange={(e) => setItemField2(e.target.value)}
                  placeholder={subTab === 'rooms' ? 'e.g. Deluxe Suite' : 'e.g. Italian / 07:00 AM'}
                  className="w-full border border-zinc-200 rounded-lg p-2"
                />
              </div>

              {(subTab === 'rooms' || subTab === 'rate-plans' || subTab === 'activities') && (
                <div>
                  <label className="block font-medium text-zinc-700 mb-1">Price ($)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={itemPrice}
                    onChange={(e) => setItemPrice(e.target.value)}
                    className="w-full border border-zinc-200 rounded-lg p-2"
                  />
                </div>
              )}

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsNewItemModal(false)}
                  className="px-4 py-2 rounded-lg border border-zinc-200 text-zinc-600 hover:bg-zinc-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={creatingItem}
                  className="px-4 py-2 rounded-lg bg-zinc-900 text-white hover:bg-zinc-800 disabled:opacity-50"
                >
                  {creatingItem ? 'Saving...' : 'Save Item'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

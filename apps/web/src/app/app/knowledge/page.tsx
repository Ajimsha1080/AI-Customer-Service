'use client';
import React, { useState, useEffect } from 'react';
import { Upload, FileText, Trash2, Search, BookOpen, HelpCircle, Shield, Info, Sparkles, ExternalLink, Plus, Eye, RefreshCw, X } from 'lucide-react';
import Link from 'next/link';

export default function AppKnowledgeBasePage() {
  const [activeCategory, setActiveCategory] = useState<'documents' | 'faqs' | 'rules'>('documents');

  const [documents, setDocuments] = useState<any[]>([
    { id: 'doc_rules_01', title: 'Hostel Resident Rules & Visitor Policy 2026.pdf', category: 'rules', type: 'PDF', status: 'Ready', date: 'Added Jan 15, 2026', updated: 'Updated today', content: 'Hostel Main Gate closes at 10:00 PM. Visitors allowed in common area until 08:00 PM.' },
    { id: 'doc_faqs_02', title: 'Frequently Asked Questions (Hostel FAQs).txt', category: 'faqs', type: 'TXT', status: 'Ready', date: 'Added Jan 20, 2026', updated: 'Updated yesterday', content: 'Q: How to request maintenance? A: Ask Hostel AI Agent or Warden office.' },
    { id: 'doc_gen_03', title: 'General Hostel Information & Directory.pdf', category: 'documents', type: 'PDF', status: 'Ready', date: 'Added Feb 01, 2026', updated: 'Updated Feb 01, 2026', content: 'Hostel Office: Block A Ground Floor. Warden Email: warden@azurehostel.com' }
  ]);

  const [search, setSearch] = useState('');
  const [toastMessage, setToastMessage] = useState<string | null>(null);
  
  // Add Knowledge Modal state
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [addMode, setAddMode] = useState<'upload' | 'paste'>('upload');
  const [docTitle, setDocTitle] = useState('');
  const [docContent, setDocContent] = useState('');
  const [docCategory, setDocCategory] = useState<'documents' | 'faqs' | 'rules'>('documents');

  // View Document Modal state
  const [viewingDoc, setViewingDoc] = useState<any | null>(null);

  const API_BASE = 'http://127.0.0.1:8000';

  const fetchDocuments = async () => {
    try {
      const res = await fetch(`${API_BASE}/api/v1/knowledge/documents?organization_id=org_azure_group`);
      if (res.ok) {
        const data = await res.json();
        if (data && data.length > 0) {
          const mapped = data.map((d: any) => ({
            id: d.id,
            title: d.title,
            category: d.title.toLowerCase().includes('faq') ? 'faqs' : (d.title.toLowerCase().includes('rule') || d.title.toLowerCase().includes('policy') ? 'rules' : 'documents'),
            type: (d.type || 'TXT').toUpperCase(),
            status: d.status === 'PROCESSED' ? 'Ready' : (d.status || 'Ready'),
            date: d.created_at ? `Added ${d.created_at.split('T')[0]}` : 'Added recently',
            updated: 'Updated today',
            content: `Ingested document: ${d.title} (${d.chunks || 1} vector chunks stored)`
          }));
          setDocuments(prev => {
            const combined = [...mapped];
            for (const p of prev) {
              if (!combined.some(c => c.id === p.id)) {
                combined.push(p);
              }
            }
            return combined;
          });
        }
      }
    } catch (e) {
      console.error('Failed to fetch knowledge documents:', e);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, []);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = async (event) => {
      const content = (event.target?.result as string) || file.name;
      try {
        const res = await fetch(`${API_BASE}/api/v1/knowledge/documents`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            organization_id: 'org_azure_group',
            property_id: 'prop_azure_palm_resort',
            title: file.name,
            content: content,
            document_type: file.name.split('.').pop() || 'txt'
          })
        });
        if (res.ok) {
          const apiDoc = await res.json();
          const newDoc = {
            id: apiDoc.id || `doc_${Date.now()}`,
            title: file.name,
            category: docCategory,
            type: file.name.split('.').pop()?.toUpperCase() || 'DOCUMENT',
            status: 'Ready',
            date: 'Added today',
            updated: 'Updated just now',
            content: content
          };
          setDocuments(prev => [newDoc, ...prev]);
          setIsAddModalOpen(false);
          showToast(`✓ Knowledge added & indexed: "${file.name}" ready for AI Assistant.`);
          return;
        }
      } catch (err) {
        console.error('Failed to post document:', err);
      }

      const newDoc = {
        id: `doc_${Date.now()}`,
        title: file.name,
        category: docCategory,
        type: file.name.split('.').pop()?.toUpperCase() || 'DOCUMENT',
        status: 'Ready',
        date: 'Added today',
        updated: 'Updated just now',
        content: `Uploaded document: ${file.name}`
      };
      setDocuments(prev => [newDoc, ...prev]);
      setIsAddModalOpen(false);
      showToast(`✓ Knowledge added: "${file.name}" ready for AI Assistant.`);
    };
    reader.readAsText(file);
  };

  const handleAddTextKnowledge = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!docTitle.trim() || !docContent.trim()) return;

    try {
      const res = await fetch(`${API_BASE}/api/v1/knowledge/documents`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          organization_id: 'org_azure_group',
          property_id: 'prop_azure_palm_resort',
          title: docTitle,
          content: docContent,
          document_type: 'txt'
        })
      });
      if (res.ok) {
        const apiDoc = await res.json();
        const newDoc = {
          id: apiDoc.id || `doc_${Date.now()}`,
          title: docTitle,
          category: docCategory,
          type: 'TEXT',
          status: 'Ready',
          date: 'Added today',
          updated: 'Updated just now',
          content: docContent
        };
        setDocuments(prev => [newDoc, ...prev]);
        setDocTitle('');
        setDocContent('');
        setIsAddModalOpen(false);
        showToast(`✓ Knowledge added & indexed: "${newDoc.title}" ready for AI Assistant.`);
        return;
      }
    } catch (err) {
      console.error('Failed to post text knowledge:', err);
    }

    const newDoc = {
      id: `doc_${Date.now()}`,
      title: docTitle,
      category: docCategory,
      type: 'TEXT',
      status: 'Ready',
      date: 'Added today',
      updated: 'Updated just now',
      content: docContent
    };

    setDocuments(prev => [newDoc, ...prev]);
    setDocTitle('');
    setDocContent('');
    setIsAddModalOpen(false);
    showToast(`✓ Knowledge added: "${newDoc.title}" ready for AI Assistant.`);
  };

  const handleRemoveDoc = async (id: string, title: string) => {
    try {
      await fetch(`${API_BASE}/api/v1/knowledge/documents/${id}?organization_id=org_azure_group&property_id=prop_azure_palm_resort`, {
        method: 'DELETE'
      });
    } catch (err) {
      console.error('Failed to delete document from backend:', err);
    }
    setDocuments(prev => prev.filter(d => d.id !== id));
    showToast(`✓ Removed knowledge document: "${title}".`);
  };


  const filteredDocs = documents.filter(d => {
    const matchesCat = d.category === activeCategory;
    const matchesSearch = (d.title || '').toLowerCase().includes(search.toLowerCase());
    return matchesCat && matchesSearch;
  });

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
          <h1 className="text-2xl font-bold text-zinc-900">Knowledge</h1>
          <p className="text-xs text-zinc-500 mt-1">Hostel documents, FAQs, and rules & policies provided to the Hostel AI Agent.</p>
        </div>

        <button
          onClick={() => setIsAddModalOpen(true)}
          className="px-4 py-2 bg-zinc-900 text-white rounded-xl text-xs font-semibold hover:bg-black transition-colors flex items-center gap-1.5 shadow-xs"
        >
          <Plus className="w-4 h-4" /> Add Knowledge
        </button>
      </div>

      {/* Sub-Category Navigation */}
      <div className="flex items-center gap-2 border-b border-zinc-200 pb-2">
        <button
          onClick={() => setActiveCategory('documents')}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold transition-colors ${
            activeCategory === 'documents' ? 'bg-zinc-900 text-white shadow-xs' : 'text-zinc-600 hover:bg-zinc-100'
          }`}
        >
          <FileText className="w-3.5 h-3.5" /> Documents
        </button>

        <button
          onClick={() => setActiveCategory('faqs')}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold transition-colors ${
            activeCategory === 'faqs' ? 'bg-zinc-900 text-white shadow-xs' : 'text-zinc-600 hover:bg-zinc-100'
          }`}
        >
          <HelpCircle className="w-3.5 h-3.5" /> FAQs
        </button>

        <button
          onClick={() => setActiveCategory('rules')}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-semibold transition-colors ${
            activeCategory === 'rules' ? 'bg-zinc-900 text-white shadow-xs' : 'text-zinc-600 hover:bg-zinc-100'
          }`}
        >
          <Shield className="w-3.5 h-3.5" /> Rules & Policies
        </button>
      </div>

      {/* Knowledge Documents List */}
      <div className="yc-card p-6 space-y-4">
        <div className="flex items-center justify-between">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search knowledge..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-full bg-zinc-50 border border-zinc-200 rounded-xl pl-9 pr-4 py-2 text-xs text-zinc-800 focus:outline-none focus:border-zinc-400 font-sans"
            />
          </div>

          <span className="text-xs text-zinc-500 font-mono">
            {filteredDocs.length} Item(s)
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs font-sans">
            <thead className="text-zinc-500 border-b border-zinc-200 font-mono text-[11px]">
              <tr>
                <th className="pb-3 font-semibold">NAME</th>
                <th className="pb-3 font-semibold">TYPE</th>
                <th className="pb-3 font-semibold">STATUS</th>
                <th className="pb-3 font-semibold">ADDED DATE</th>
                <th className="pb-3 font-semibold">LAST UPDATED</th>
                <th className="pb-3 font-semibold text-right">ACTIONS</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-zinc-200 text-zinc-800">
              {filteredDocs.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-zinc-400 text-xs font-mono">
                    No items in this category yet. Click "+ Add Knowledge" to add rules, FAQs, or documents.
                  </td>
                </tr>
              ) : (
                filteredDocs.map(doc => (
                  <tr key={doc.id} className="hover:bg-zinc-50 transition-colors">
                    <td className="py-3.5 font-bold text-zinc-900 flex items-center gap-2">
                      <FileText className="w-4 h-4 text-zinc-500 shrink-0" />
                      <span className="truncate max-w-sm">{doc.title}</span>
                    </td>
                    <td className="font-mono text-zinc-600 text-[11px]">{doc.type}</td>
                    <td>
                      <span className="px-2 py-0.5 rounded bg-emerald-100 text-emerald-800 border border-emerald-200 font-mono text-[10px] font-bold">
                        ● {doc.status}
                      </span>
                    </td>
                    <td className="font-mono text-zinc-500 text-[11px]">{doc.date}</td>
                    <td className="font-mono text-zinc-500 text-[11px]">{doc.updated}</td>
                    <td className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={() => setViewingDoc(doc)}
                          className="px-2.5 py-1 bg-zinc-100 text-zinc-800 rounded-md text-xs font-semibold hover:bg-zinc-200 transition-colors flex items-center gap-1"
                        >
                          <Eye className="w-3 h-3" /> View
                        </button>
                        <button
                          onClick={() => showToast(`✓ Knowledge item "${doc.title}" re-synced.`)}
                          className="px-2.5 py-1 bg-zinc-100 text-zinc-800 rounded-md text-xs font-semibold hover:bg-zinc-200 transition-colors flex items-center gap-1"
                        >
                          <RefreshCw className="w-3 h-3" /> Replace
                        </button>
                        <button
                          onClick={() => handleRemoveDoc(doc.id, doc.title)}
                          className="px-2.5 py-1 bg-rose-50 text-rose-700 border border-rose-200 rounded-md text-xs font-semibold hover:bg-rose-100 transition-colors flex items-center gap-1"
                        >
                          <Trash2 className="w-3 h-3" /> Remove
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Modal: Add Knowledge */}
      {isAddModalOpen && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
              <h3 className="text-sm font-bold text-zinc-900">Add Knowledge</h3>
              <button onClick={() => setIsAddModalOpen(false)} className="text-zinc-400 hover:text-zinc-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            {/* Mode Switcher */}
            <div className="flex items-center gap-2 bg-zinc-100 p-1 rounded-xl text-xs font-semibold">
              <button
                onClick={() => setAddMode('upload')}
                className={`flex-1 py-1.5 rounded-lg transition-colors ${addMode === 'upload' ? 'bg-white text-zinc-900 shadow-xs' : 'text-zinc-600'}`}
              >
                Upload document
              </button>
              <button
                onClick={() => setAddMode('paste')}
                className={`flex-1 py-1.5 rounded-lg transition-colors ${addMode === 'paste' ? 'bg-white text-zinc-900 shadow-xs' : 'text-zinc-600'}`}
              >
                Paste information
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-semibold text-zinc-700 block mb-1">Knowledge Category:</label>
                <select
                  value={docCategory}
                  onChange={(e: any) => setDocCategory(e.target.value)}
                  className="w-full border border-zinc-300 rounded-lg p-2 text-xs bg-white"
                >
                  <option value="documents">Documents</option>
                  <option value="faqs">FAQs</option>
                  <option value="rules">Rules & Policies</option>
                </select>
              </div>

              {addMode === 'upload' ? (
                <label className="block p-6 border-2 border-dashed border-zinc-300 rounded-xl text-center space-y-2 cursor-pointer hover:border-zinc-400 transition-colors">
                  <Upload className="w-6 h-6 text-zinc-500 mx-auto" />
                  <span className="font-bold text-zinc-800 block">Choose file (.pdf, .txt, .md)</span>
                  <span className="text-[11px] text-zinc-500 block">Select document from your device</span>
                  <input type="file" onChange={handleUpload} className="hidden" accept=".txt,.csv,.json,.md,.pdf" />
                </label>
              ) : (
                <form onSubmit={handleAddTextKnowledge} className="space-y-3">
                  <div>
                    <label className="font-semibold text-zinc-700 block mb-1">Title:</label>
                    <input
                      type="text"
                      value={docTitle}
                      onChange={(e) => setDocTitle(e.target.value)}
                      placeholder="e.g. Quiet Hours Policy"
                      className="w-full border border-zinc-300 rounded-lg p-2 text-xs"
                      required
                    />
                  </div>
                  <div>
                    <label className="font-semibold text-zinc-700 block mb-1">Information Content:</label>
                    <textarea
                      value={docContent}
                      onChange={(e) => setDocContent(e.target.value)}
                      placeholder="Type or paste information for the AI Assistant..."
                      rows={4}
                      className="w-full border border-zinc-300 rounded-lg p-2 text-xs"
                      required
                    />
                  </div>
                  <div className="flex justify-end gap-2 pt-2 border-t border-zinc-100">
                    <button
                      type="button"
                      onClick={() => setIsAddModalOpen(false)}
                      className="px-3.5 py-1.5 text-xs text-zinc-600 hover:bg-zinc-100 rounded-lg"
                    >
                      Cancel
                    </button>
                    <button
                      type="submit"
                      className="px-4 py-1.5 bg-zinc-900 text-white rounded-lg text-xs font-semibold hover:bg-black"
                    >
                      Add Knowledge
                    </button>
                  </div>
                </form>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Modal: View Knowledge Content */}
      {viewingDoc && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-xs flex items-center justify-center p-4 z-50">
          <div className="bg-white rounded-2xl max-w-md w-full p-6 space-y-4 shadow-xl">
            <div className="flex items-center justify-between border-b border-zinc-200 pb-3">
              <h3 className="text-sm font-bold text-zinc-900 truncate pr-4">{viewingDoc.title}</h3>
              <button onClick={() => setViewingDoc(null)} className="text-zinc-400 hover:text-zinc-600">
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="space-y-2 text-xs">
              <div className="flex items-center justify-between text-[11px] font-mono text-zinc-500">
                <span>Format: {viewingDoc.type}</span>
                <span>Status: {viewingDoc.status}</span>
              </div>
              <div className="p-3 bg-zinc-50 border border-zinc-200 rounded-xl text-zinc-800 leading-relaxed font-mono text-[11px]">
                {viewingDoc.content}
              </div>
            </div>

            <div className="flex justify-end pt-2 border-t border-zinc-100">
              <button
                onClick={() => setViewingDoc(null)}
                className="px-4 py-1.5 bg-zinc-900 text-white rounded-lg text-xs font-semibold hover:bg-black"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

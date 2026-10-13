'use client';
import React, { useState, useEffect } from 'react';
import { Upload, FileText, Trash2, Search, BookOpen, Sparkles, ExternalLink, Plus, Eye, Loader2, CheckCircle2 } from 'lucide-react';
import { authFetch, getCurrentSession } from '@/lib/api';

export default function AppKnowledgeBasePage() {
  const [documents, setDocuments] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<any>(null);
  const [properties, setProperties] = useState<any[]>([]);
  const [selectedPropertyId, setSelectedPropertyId] = useState<string>('');
  const [search, setSearch] = useState('');
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  // Add Knowledge Modal state
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [docTitle, setDocTitle] = useState('');
  const [docContent, setDocContent] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // View Document Modal state
  const [viewingDoc, setViewingDoc] = useState<any | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 4000);
  };

  const loadData = async () => {
    setLoading(true);
    try {
      const sess = await getCurrentSession();
      setSession(sess);
      if (sess?.organization_id) {
        const [docsRes, propsRes] = await Promise.all([
          authFetch(`/api/v1/knowledge/documents?organization_id=${sess.organization_id}`),
          authFetch(`/api/v1/properties?organization_id=${sess.organization_id}`)
        ]);

        if (docsRes.ok) {
          const docsData = await docsRes.json();
          setDocuments(Array.isArray(docsData) ? docsData : []);
        }

        if (propsRes.ok) {
          const propsData = await propsRes.json();
          const pList = Array.isArray(propsData) ? propsData : [];
          setProperties(pList);
          if (pList.length > 0 && !selectedPropertyId) {
            setSelectedPropertyId(pList[0].id);
          }
        }
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, []);

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || !e.target.files[0]) return;
    const file = e.target.files[0];
    const reader = new FileReader();
    reader.onload = async (event) => {
      const content = (event.target?.result as string) || '';
      await createDocument(file.name, content, file.name.split('.').pop() || 'txt');
    };
    reader.readAsText(file);
  };

  const createDocument = async (title: string, content: string, type: string = 'txt') => {
    if (!session?.organization_id || !title.trim() || !content.trim()) return;
    setSubmitting(true);
    try {
      const res = await authFetch('/api/v1/knowledge/documents', {
        method: 'POST',
        body: JSON.stringify({
          organization_id: session.organization_id,
          property_id: selectedPropertyId || undefined,
          title,
          content,
          document_type: type
        })
      });

      if (res.ok) {
        showToast(`✓ Document "${title}" indexed & vectorized for RAG.`);
        setIsAddModalOpen(false);
        setDocTitle('');
        setDocContent('');
        await loadData();
      } else {
        const err = await res.json();
        showToast(`Error: ${err.detail || 'Failed to upload document'}`);
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleRemoveDoc = async (id: string, title: string) => {
    try {
      const res = await authFetch(`/api/v1/knowledge/documents/${id}`, {
        method: 'DELETE'
      });
      if (res.ok) {
        setDocuments(prev => prev.filter(d => d.id !== id));
        showToast(`✓ Removed document "${title}".`);
      }
    } catch {
      showToast('Error removing document');
    }
  };

  const filteredDocs = documents.filter(d =>
    (d.title || '').toLowerCase().includes(search.toLowerCase()) ||
    (d.content || '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="max-w-6xl mx-auto space-y-8 font-sans">
      {/* Toast Notification */}
      {toastMessage && (
        <div className="fixed bottom-5 right-5 bg-zinc-900 text-white px-4 py-3 rounded-xl shadow-lg border border-zinc-700 text-xs flex items-center gap-2 z-50">
          <Sparkles className="w-4 h-4 text-emerald-400" />
          <span>{toastMessage}</span>
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between border-b border-zinc-200 pb-6">
        <div>
          <h1 className="text-2xl font-bold text-zinc-900">Knowledge Base & RAG Index</h1>
          <p className="text-xs text-zinc-500 mt-1">Upload property guides, restaurant menus, policies, and FAQs into PostgreSQL vector storage.</p>
        </div>

        <button
          onClick={() => setIsAddModalOpen(true)}
          className="yc-btn-primary flex items-center gap-1.5 text-xs"
        >
          <Plus className="w-3.5 h-3.5" /> Add Knowledge
        </button>
      </div>

      {/* Search Header */}
      <div className="flex items-center justify-between gap-4">
        <div className="relative flex-1 max-w-md">
          <Search className="w-4 h-4 text-zinc-400 absolute left-3 top-1/2 -translate-y-1/2" />
          <input
            type="text"
            placeholder="Search documents by keyword..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-zinc-50 border border-zinc-200 rounded-xl pl-9 pr-4 py-2 text-xs text-zinc-800 focus:outline-none focus:border-zinc-400"
          />
        </div>

        <span className="yc-badge font-mono text-xs">
          {filteredDocs.length} Indexed Docs
        </span>
      </div>

      {loading ? (
        <div className="py-16 flex flex-col items-center justify-center gap-3 text-zinc-500">
          <Loader2 className="w-8 h-8 animate-spin text-zinc-700" />
          <p className="text-xs">Loading knowledge documents...</p>
        </div>
      ) : filteredDocs.length === 0 ? (
        <div className="yc-card p-12 text-center space-y-4">
          <BookOpen className="w-12 h-12 text-zinc-400 mx-auto" />
          <h3 className="text-sm font-bold text-zinc-900">No Knowledge Documents Found</h3>
          <p className="text-xs text-zinc-500 max-w-sm mx-auto">Upload guides, rules, dining schedules, or FAQs to allow the AI concierge to answer guest questions accurately.</p>
          <button
            onClick={() => setIsAddModalOpen(true)}
            className="yc-btn-primary text-xs inline-flex items-center gap-1.5"
          >
            <Plus className="w-4 h-4" /> Upload First Document
          </button>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {filteredDocs.map((doc) => (
            <div key={doc.id} className="yc-card p-5 flex flex-col justify-between space-y-4">
              <div>
                <div className="flex items-center justify-between mb-2">
                  <span className="px-2 py-0.5 rounded bg-zinc-100 text-zinc-700 font-mono text-[10px] font-bold uppercase">
                    {doc.document_type || 'TXT'}
                  </span>
                  <span className="text-[10px] text-emerald-600 font-bold font-mono">● {doc.status || 'INDEXED'}</span>
                </div>
                <h3 className="font-bold text-sm text-zinc-900 line-clamp-1">{doc.title}</h3>
                <p className="text-xs text-zinc-500 mt-2 line-clamp-3">
                  {doc.content || 'Document vectorized and available for live semantic retrieval.'}
                </p>
              </div>

              <div className="flex items-center justify-between pt-3 border-t border-zinc-100">
                <button
                  onClick={() => setViewingDoc(doc)}
                  className="text-xs font-semibold text-zinc-600 hover:text-zinc-900 flex items-center gap-1"
                >
                  <Eye className="w-3.5 h-3.5" /> View Content
                </button>

                <button
                  onClick={() => handleRemoveDoc(doc.id, doc.title)}
                  className="p-1.5 text-zinc-400 hover:text-rose-600 rounded-lg hover:bg-rose-50 transition"
                  title="Delete Document"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Add Document Modal */}
      {isAddModalOpen && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-lg w-full p-6 shadow-xl border border-zinc-200">
            <h3 className="text-base font-bold text-zinc-900 mb-4">Add Knowledge Document</h3>

            <div className="space-y-4 text-xs">
              {properties.length > 0 && (
                <div>
                  <label className="block font-medium text-zinc-700 mb-1">Target Property</label>
                  <select
                    value={selectedPropertyId}
                    onChange={(e) => setSelectedPropertyId(e.target.value)}
                    className="w-full border border-zinc-200 rounded-lg p-2 bg-zinc-50 text-zinc-900"
                  >
                    {properties.map(p => (
                      <option key={p.id} value={p.id}>{p.name}</option>
                    ))}
                  </select>
                </div>
              )}

              {/* File Upload Area */}
              <div className="border-2 border-dashed border-zinc-300 rounded-xl p-5 text-center bg-zinc-50">
                <Upload className="w-6 h-6 text-zinc-400 mx-auto mb-2" />
                <label className="cursor-pointer font-bold text-indigo-600 hover:text-indigo-500">
                  Select a document file (.txt, .md, .pdf)
                  <input
                    type="file"
                    accept=".txt,.md,.pdf,.docx"
                    onChange={handleFileUpload}
                    className="hidden"
                  />
                </label>
                <p className="text-[11px] text-zinc-500 mt-1">Automatic parsing and PGVector embedding</p>
              </div>

              <div className="relative flex py-1 items-center">
                <div className="flex-grow border-t border-zinc-200"></div>
                <span className="flex-shrink mx-3 text-zinc-400 font-mono text-[10px]">OR PASTE TEXT</span>
                <div className="flex-grow border-t border-zinc-200"></div>
              </div>

              <div>
                <label className="block font-medium text-zinc-700 mb-1">Document Title</label>
                <input
                  type="text"
                  value={docTitle}
                  onChange={(e) => setDocTitle(e.target.value)}
                  placeholder="e.g. Dining Hours & Room Service"
                  className="w-full border border-zinc-200 rounded-lg p-2 bg-zinc-50 text-zinc-900"
                />
              </div>

              <div>
                <label className="block font-medium text-zinc-700 mb-1">Document Content</label>
                <textarea
                  rows={4}
                  value={docContent}
                  onChange={(e) => setDocContent(e.target.value)}
                  placeholder="Enter policies, instructions, menus, or FAQs..."
                  className="w-full border border-zinc-200 rounded-lg p-2 bg-zinc-50 text-zinc-900"
                />
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <button
                  type="button"
                  onClick={() => setIsAddModalOpen(false)}
                  className="px-4 py-2 rounded-lg border border-zinc-200 text-zinc-600 hover:bg-zinc-50"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={submitting || !docTitle.trim() || !docContent.trim()}
                  onClick={() => createDocument(docTitle, docContent, 'txt')}
                  className="px-4 py-2 rounded-lg bg-zinc-900 text-white hover:bg-zinc-800 disabled:opacity-50"
                >
                  {submitting ? 'Indexing...' : 'Index Document'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* View Content Modal */}
      {viewingDoc && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl max-w-xl w-full p-6 shadow-xl border border-zinc-200 max-h-[80vh] flex flex-col">
            <div className="flex items-center justify-between border-b border-zinc-200 pb-3 mb-4">
              <h3 className="font-bold text-sm text-zinc-900">{viewingDoc.title}</h3>
              <button onClick={() => setViewingDoc(null)} className="text-zinc-400 hover:text-zinc-600 text-xs">✕ Close</button>
            </div>
            <div className="flex-1 overflow-y-auto p-4 bg-zinc-50 rounded-xl border border-zinc-200 font-mono text-xs whitespace-pre-wrap text-zinc-800">
              {viewingDoc.content}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

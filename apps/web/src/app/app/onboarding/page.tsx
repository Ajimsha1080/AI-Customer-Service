'use client';
import React, { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { ChevronRight, Building2, BookOpen, Bot, Rocket, Sparkles, Play, Upload, AlertCircle, Loader2, CheckCircle2 } from 'lucide-react';
import { API_BASE, authFetch, getCurrentSession } from '@/lib/api';

export default function OnboardingWizardPage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(1);
  const [session, setSession] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [propertyName, setPropertyName] = useState('');
  const [propertyType, setPropertyType] = useState('hotel');
  const [propertyAddress, setPropertyAddress] = useState('');

  // Step 2 Document
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [documentContent, setDocumentContent] = useState('');
  const [documentTitle, setDocumentTitle] = useState('');

  // Step 4 Agent
  const [agentName, setAgentName] = useState('Front Desk AI Concierge');
  const [agentTone, setAgentTone] = useState('Friendly, Professional');

  useEffect(() => {
    async function load() {
      const sess = await getCurrentSession();
      setSession(sess);
      if (sess?.organization_name) {
        setPropertyName(`${sess.organization_name} Main`);
      }
    }
    load();
  }, []);

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files[0]) {
      const file = e.target.files[0];
      setUploadedFile(file);
      setDocumentTitle(file.name);
      const reader = new FileReader();
      reader.onload = (event) => {
        setDocumentContent((event.target?.result as string) || '');
      };
      reader.readAsText(file);
    }
  };

  const handleCompleteOnboarding = async () => {
    if (!session?.organization_id) {
      setError('Active session not found. Please log in.');
      return;
    }
    setLoading(true);
    setError(null);

    try {
      // 1. Create property
      const propRes = await authFetch('/api/v1/properties', {
        method: 'POST',
        body: JSON.stringify({
          organization_id: session.organization_id,
          name: propertyName || 'Main Property',
          property_type: propertyType,
          address: propertyAddress || undefined,
          timezone: 'UTC'
        })
      });

      if (!propRes.ok) {
        const err = await propRes.json();
        throw new Error(err.detail || 'Failed to create property');
      }
      const propData = await propRes.json();
      const propertyId = propData.id;

      // 2. Upload knowledge document if provided
      if (documentContent.trim()) {
        const docRes = await authFetch('/api/v1/knowledge/documents', {
          method: 'POST',
          body: JSON.stringify({
            organization_id: session.organization_id,
            property_id: propertyId,
            title: documentTitle || 'Property Knowledge Guide',
            content: documentContent,
            document_type: uploadedFile?.name.split('.').pop() || 'txt'
          })
        });

        if (!docRes.ok) {
          const err = await docRes.json();
          throw new Error(err.detail || 'Failed to index knowledge document');
        }
      }

      // 3. Create Concierge Agent
      const agentRes = await authFetch('/api/v1/agents', {
        method: 'POST',
        body: JSON.stringify({
          organization_id: session.organization_id,
          property_id: propertyId,
          name: agentName || 'AI Concierge',
          agent_type: 'CONCIERGE',
          tone: agentTone
        })
      });

      if (!agentRes.ok) {
        const err = await agentRes.json();
        throw new Error(err.detail || 'Failed to deploy AI concierge agent');
      }

      router.push('/app/dashboard');
    } catch (err: any) {
      setError(err.message || 'Onboarding failed');
      setLoading(false);
    }
  };

  const steps = [
    { num: 1, title: 'Create Property' },
    { num: 2, title: 'Upload Knowledge' },
    { num: 3, title: 'Configure AI Concierge' },
    { num: 4, title: 'Deploy & Finish' }
  ];

  return (
    <div className="max-w-2xl mx-auto py-12 px-4 font-sans">
      <div className="mb-8">
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs font-mono font-bold uppercase text-zinc-400">Step {currentStep} of {steps.length}</span>
          <span className="text-xs font-bold text-zinc-900">{Math.round((currentStep / steps.length) * 100)}% Complete</span>
        </div>
        <div className="w-full bg-zinc-200 h-1.5 rounded-full overflow-hidden">
          <div 
            className="bg-zinc-900 h-full rounded-full transition-all duration-300"
            style={{ width: `${(currentStep / steps.length) * 100}%` }}
          />
        </div>
      </div>

      {error && (
        <div className="mb-6 p-4 rounded-xl bg-rose-50 border border-rose-200 text-rose-700 text-xs flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="yc-card p-8 space-y-6">
        {currentStep === 1 && (
          <div className="space-y-4 text-xs">
            <div className="border-b border-zinc-200 pb-3">
              <h2 className="text-base font-bold text-zinc-900">Step 1: Property Details</h2>
              <p className="text-zinc-500">Enter your hospitality property name and type.</p>
            </div>

            <div>
              <label className="block font-medium text-zinc-700 mb-1">Property Name</label>
              <input
                type="text"
                required
                value={propertyName}
                onChange={(e) => setPropertyName(e.target.value)}
                placeholder="e.g. Grand Sapphire Resort"
                className="w-full border border-zinc-200 rounded-lg p-2.5 bg-zinc-50 text-zinc-900"
              />
            </div>

            <div>
              <label className="block font-medium text-zinc-700 mb-1">Property Type</label>
              <select
                value={propertyType}
                onChange={(e) => setPropertyType(e.target.value)}
                className="w-full border border-zinc-200 rounded-lg p-2.5 bg-zinc-50 text-zinc-900"
              >
                <option value="hotel">Hotel</option>
                <option value="resort">Resort</option>
                <option value="hostel">Hostel / Campus</option>
                <option value="villa">Luxury Villa</option>
              </select>
            </div>

            <div>
              <label className="block font-medium text-zinc-700 mb-1">Physical Address</label>
              <input
                type="text"
                value={propertyAddress}
                onChange={(e) => setPropertyAddress(e.target.value)}
                placeholder="e.g. 100 Coastal Rd, Miami, FL"
                className="w-full border border-zinc-200 rounded-lg p-2.5 bg-zinc-50 text-zinc-900"
              />
            </div>
          </div>
        )}

        {currentStep === 2 && (
          <div className="space-y-4 text-xs">
            <div className="border-b border-zinc-200 pb-3">
              <h2 className="text-base font-bold text-zinc-900">Step 2: Add Knowledge Base Guide</h2>
              <p className="text-zinc-500">Upload a guest guide, FAQ list, or restaurant menu.</p>
            </div>

            <div className="border-2 border-dashed border-zinc-300 rounded-xl p-6 text-center space-y-3 bg-zinc-50">
              <Upload className="w-8 h-8 text-zinc-400 mx-auto" />
              <div>
                <label className="cursor-pointer font-bold text-indigo-600 hover:text-indigo-500">
                  Select a document file (.txt, .pdf, .md)
                  <input
                    type="file"
                    accept=".txt,.pdf,.md,.docx"
                    onChange={handleFileChange}
                    className="hidden"
                  />
                </label>
                <p className="text-[11px] text-zinc-500 mt-1">Text or document up to 10 MB</p>
              </div>
              {uploadedFile && (
                <div className="p-2 bg-emerald-50 text-emerald-800 rounded-lg font-mono text-[11px] flex items-center justify-center gap-1.5">
                  <CheckCircle2 className="w-4 h-4" /> Selected: {uploadedFile.name} ({Math.round(uploadedFile.size / 1024)} KB)
                </div>
              )}
            </div>

            <div>
              <label className="block font-medium text-zinc-700 mb-1">Or paste plain text guide:</label>
              <textarea
                rows={4}
                value={documentContent}
                onChange={(e) => {
                  setDocumentContent(e.target.value);
                  if (!documentTitle) setDocumentTitle('Property Guidelines');
                }}
                placeholder="Pool hours: 6 AM to 10 PM. Breakfast served 7 AM to 10:30 AM at Main Dining..."
                className="w-full border border-zinc-200 rounded-lg p-2.5 bg-zinc-50 text-zinc-900"
              />
            </div>
          </div>
        )}

        {currentStep === 3 && (
          <div className="space-y-4 text-xs">
            <div className="border-b border-zinc-200 pb-3">
              <h2 className="text-base font-bold text-zinc-900">Step 3: AI Concierge Persona</h2>
              <p className="text-zinc-500">Customize the AI agent greeting and communication style.</p>
            </div>

            <div>
              <label className="block font-medium text-zinc-700 mb-1">Agent Name</label>
              <input
                type="text"
                required
                value={agentName}
                onChange={(e) => setAgentName(e.target.value)}
                className="w-full border border-zinc-200 rounded-lg p-2.5 bg-zinc-50 text-zinc-900"
              />
            </div>

            <div>
              <label className="block font-medium text-zinc-700 mb-1">Tone & Persona</label>
              <input
                type="text"
                value={agentTone}
                onChange={(e) => setAgentTone(e.target.value)}
                placeholder="Friendly, Courteous, Professional"
                className="w-full border border-zinc-200 rounded-lg p-2.5 bg-zinc-50 text-zinc-900"
              />
            </div>
          </div>
        )}

        {currentStep === 4 && (
          <div className="space-y-4 text-xs">
            <div className="border-b border-zinc-200 pb-3">
              <h2 className="text-base font-bold text-zinc-900">Step 4: Ready to Deploy</h2>
              <p className="text-zinc-500">Review your setup and activate the production AI concierge.</p>
            </div>

            <div className="bg-zinc-50 p-4 rounded-xl space-y-2 border border-zinc-200">
              <div className="flex justify-between">
                <span className="text-zinc-500">Property:</span>
                <span className="font-bold text-zinc-900">{propertyName}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">Knowledge:</span>
                <span className="font-bold text-zinc-900">{documentTitle || (documentContent ? 'Text Guide' : 'None')}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-zinc-500">AI Concierge:</span>
                <span className="font-bold text-zinc-900">{agentName}</span>
              </div>
            </div>
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex justify-between pt-4 border-t border-zinc-200">
          {currentStep > 1 ? (
            <button
              type="button"
              onClick={() => setCurrentStep(prev => prev - 1)}
              className="px-4 py-2 border border-zinc-200 rounded-lg text-xs font-semibold text-zinc-700 hover:bg-zinc-50"
            >
              Back
            </button>
          ) : <div />}

          {currentStep < 4 ? (
            <button
              type="button"
              onClick={() => setCurrentStep(prev => prev + 1)}
              className="yc-btn-primary flex items-center gap-1.5 text-xs"
            >
              Continue <ChevronRight className="w-3.5 h-3.5" />
            </button>
          ) : (
            <button
              type="button"
              disabled={loading}
              onClick={handleCompleteOnboarding}
              className="yc-btn-primary flex items-center gap-1.5 text-xs disabled:opacity-50"
            >
              {loading ? (
                <>
                  <Loader2 className="w-4 h-4 animate-spin" /> Provisioning...
                </>
              ) : (
                <>
                  <Rocket className="w-3.5 h-3.5" /> Activate Workspace
                </>
              )}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

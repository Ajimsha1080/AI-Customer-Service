'use client';
import React, { useState } from 'react';
import { useRouter } from 'next/navigation';
import { ChevronRight, Building2, BookOpen, Bot, Rocket, Sparkles, Play } from 'lucide-react';
import { API_BASE } from '@/lib/api';

export default function OnboardingWizardPage() {
  const [currentStep, setCurrentStep] = useState(1);
  const router = useRouter();

  const [formData, setFormData] = useState({
    propertyName: 'Azure Palm Resort & Spa',
    propertyType: 'resort',
    address: 'Marari Beach, Kerala, India',
    agentName: 'Azure Concierge',
    enabledTools: ['availability', 'facility_status', 'booking']
  });

  const steps = [
    { num: 1, title: 'Create Property', desc: 'Set property name and location' },
    { num: 2, title: 'Property Information', desc: 'Upload guest guide or policies' },
    { num: 3, title: 'Connect Availability', desc: 'Enable live room & pool tools' },
    { num: 4, title: 'Select Predefined AI Agent', desc: 'Choose Concierge, Booking, or Support' },
    { num: 5, title: 'Test Agent', desc: 'Try sample guest inquiries' },
    { num: 6, title: 'Deploy', desc: 'Activate agent in production' }
  ];

  const progressPct = Math.round((currentStep / steps.length) * 100);

  const handleNext = async () => {
    if (currentStep < 6) {
      setCurrentStep(prev => prev + 1);
    } else {
      try {
        const propRes = await fetch(`${API_BASE}/api/v1/properties`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            organization_id: 'org_azure_group',
            name: formData.propertyName,
            property_type: formData.propertyType,
            timezone: 'UTC'
          })
        });
        const propData = await propRes.json();
        const propertyId = propData.id || 'prop_azure_palm_resort';

        await fetch(`${API_BASE}/api/v1/agents`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            organization_id: 'org_azure_group',
            property_id: propertyId,
            name: formData.agentName,
            agent_type: 'CONCIERGE',
            tone: 'Luxury'
          })
        });
      } catch (err) {
        console.error('Onboarding sync error:', err);
      }
      router.push('/app/dashboard');
    }
  };

  return (
    <div className="max-w-3xl mx-auto space-y-6 font-sans">
      {/* Onboarding Header */}
      <div className="text-center space-y-2">
        <div className="yc-badge mb-2">
          <span>✨ Welcome to Hospitality Agent Cloud</span>
        </div>
        <h1 className="text-2xl font-bold text-zinc-900">Let's launch your first AI concierge.</h1>
        <p className="text-xs text-zinc-600">Complete this 6-step guided wizard to deploy an AI agent for your property in under 3 minutes.</p>
      </div>

      {/* Progress Bar & Percentage */}
      <div className="yc-card p-5 space-y-2.5">
        <div className="flex items-center justify-between text-xs font-semibold">
          <span className="text-zinc-500 uppercase tracking-wider text-[11px] font-mono">ONBOARDING PROGRESS</span>
          <span className="text-zinc-900 font-mono text-[11px] font-bold">{progressPct}% Completed</span>
        </div>
        <div className="w-full bg-zinc-100 rounded-full h-2 overflow-hidden border border-zinc-200">
          <div 
            style={{ width: `${progressPct}%` }}
            className="bg-zinc-900 h-full transition-all duration-300 rounded-full"
          ></div>
        </div>
      </div>

      {/* Step Content */}
      <div className="yc-card p-6 space-y-5">
        {currentStep === 1 && (
          <div className="space-y-5">
            <div className="flex items-center gap-3 border-b border-zinc-200 pb-4">
              <div className="w-8 h-8 rounded-lg bg-zinc-900 text-white flex items-center justify-center shadow-xs">
                <Building2 className="w-4 h-4" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-zinc-900">STEP 1: Create Property</h2>
                <p className="text-[11px] text-zinc-500">Enter basic details for your resort, hotel, or hostel.</p>
              </div>
            </div>

            <div className="space-y-4 text-xs">
              <div>
                <label className="block text-zinc-700 font-semibold mb-1.5">Property Name</label>
                <input 
                  type="text" 
                  value={formData.propertyName}
                  onChange={(e) => setFormData({...formData, propertyName: e.target.value})}
                  className="w-full bg-zinc-50 border border-zinc-200 rounded-lg px-3.5 py-2 text-xs text-zinc-900 focus:outline-none focus:border-zinc-400"
                />
              </div>

              <div>
                <label className="block text-zinc-700 font-semibold mb-1.5">Property Category</label>
                <select 
                  value={formData.propertyType}
                  onChange={(e) => setFormData({...formData, propertyType: e.target.value})}
                  className="w-full bg-zinc-50 border border-zinc-200 rounded-lg px-3.5 py-2 text-xs text-zinc-900 focus:outline-none focus:border-zinc-400"
                >
                  <option value="resort">Luxury Resort & Spa</option>
                  <option value="hotel">Boutique Hotel</option>
                  <option value="hostel">Hostel</option>
                  <option value="apartment">Serviced Apartments</option>
                </select>
              </div>
            </div>
          </div>
        )}

        {currentStep === 2 && (
          <div className="space-y-5">
            <div className="flex items-center gap-3 border-b border-zinc-200 pb-4">
              <div className="w-8 h-8 rounded-lg bg-zinc-900 text-white flex items-center justify-center shadow-xs">
                <BookOpen className="w-4 h-4" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-zinc-900">STEP 2: Add Property Information</h2>
                <p className="text-[11px] text-zinc-500">Upload your guest guide, policies, or restaurant menu PDF.</p>
              </div>
            </div>

            <div className="p-6 border-2 border-dashed border-zinc-300 rounded-xl text-center bg-zinc-50 space-y-2">
              <BookOpen className="w-6 h-6 text-zinc-600 mx-auto" />
              <p className="text-xs font-semibold text-zinc-900">Demo File Loaded: Azure Palm Resort Guest Guide 2026.pdf</p>
              <p className="text-[11px] text-emerald-700 font-mono font-semibold">✓ Parsed into 24 vector chunks with pgvector tenant metadata.</p>
            </div>
          </div>
        )}

        {currentStep === 3 && (
          <div className="space-y-5">
            <div className="flex items-center gap-3 border-b border-zinc-200 pb-4">
              <div className="w-8 h-8 rounded-lg bg-zinc-900 text-white flex items-center justify-center shadow-xs">
                <Sparkles className="w-4 h-4" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-zinc-900">STEP 3: Connect Live Tools & Availability</h2>
                <p className="text-[11px] text-zinc-500">Enable real-time tools for room availability, prices, and pool hours.</p>
              </div>
            </div>

            <div className="p-4 bg-zinc-50 border border-zinc-200 rounded-lg space-y-2.5 text-xs">
              <div className="flex items-center justify-between">
                <span className="text-zinc-800 font-medium">✓ Room Vacancy & Availability Tool</span>
                <span className="yc-badge-emerald">Connected</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-zinc-800 font-medium">✓ Facility Operational Status (Pool/Spa)</span>
                <span className="yc-badge-emerald">Connected</span>
              </div>
            </div>
          </div>
        )}

        {currentStep === 4 && (
          <div className="space-y-5">
            <div className="flex items-center gap-3 border-b border-zinc-200 pb-4">
              <div className="w-8 h-8 rounded-lg bg-zinc-900 text-white flex items-center justify-center shadow-xs">
                <Bot className="w-4 h-4" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-zinc-900">STEP 4: Select Predefined AI Agent</h2>
                <p className="text-[11px] text-zinc-500">Select pre-configured enterprise agent template for your property.</p>
              </div>
            </div>

            <div className="text-xs">
              <label className="block text-zinc-700 font-semibold mb-1.5">Agent Name</label>
              <input 
                type="text" 
                value={formData.agentName}
                onChange={(e) => setFormData({...formData, agentName: e.target.value})}
                className="w-full bg-zinc-50 border border-zinc-200 rounded-lg px-3.5 py-2 text-xs text-zinc-900 focus:outline-none focus:border-zinc-400"
              />
            </div>
          </div>
        )}

        {currentStep === 5 && (
          <div className="space-y-5">
            <div className="flex items-center gap-3 border-b border-zinc-200 pb-4">
              <div className="w-8 h-8 rounded-lg bg-zinc-900 text-white flex items-center justify-center shadow-xs">
                <Play className="w-4 h-4" />
              </div>
              <div>
                <h2 className="text-sm font-bold text-zinc-900">STEP 5: Test Agent Inquiries</h2>
                <p className="text-[11px] text-zinc-500">Simulate a guest question before publishing to production.</p>
              </div>
            </div>

            <div className="p-4 bg-zinc-50 border border-zinc-200 rounded-lg text-xs space-y-2">
              <p className="font-semibold text-zinc-900">Test Query: "Is the swimming pool open now?"</p>
              <p className="text-zinc-600 italic">Agent Response: "The Infinity Swimming Pool is currently Open (06:00 AM - 08:00 PM)."</p>
            </div>
          </div>
        )}

        {currentStep === 6 && (
          <div className="space-y-4 text-center py-4">
            <Rocket className="w-8 h-8 text-zinc-900 mx-auto" />
            <h2 className="text-base font-bold text-zinc-900">STEP 6: Deploy Your AI Agent</h2>
            <p className="text-xs text-zinc-600 max-w-sm mx-auto">
              Your agent is fully configured. Click below to activate your agent on the Shared Agent Runtime.
            </p>
          </div>
        )}

        {/* Wizard Footer Navigation */}
        <div className="flex items-center justify-between border-t border-zinc-200 pt-4">
          <button 
            disabled={currentStep === 1}
            onClick={() => setCurrentStep(prev => prev - 1)}
            className="yc-btn-secondary disabled:opacity-40"
          >
            ← Back
          </button>

          <button 
            onClick={handleNext}
            className="yc-btn-primary flex items-center gap-1.5"
          >
            {currentStep === 6 ? 'Complete Setup & Open Dashboard →' : 'Continue to Next Step'} <ChevronRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    </div>
  );
}

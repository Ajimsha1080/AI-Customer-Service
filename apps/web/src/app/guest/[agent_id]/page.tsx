'use client';
import React, { useState, useRef } from 'react';
import { Volume2, Mic, MicOff, Globe, Sparkles, Send, Bot, CheckCircle2, User, PhoneCall, Radio, MessageSquare, AlertCircle } from 'lucide-react';
import { API_BASE } from '@/lib/api';
import { VoiceOrb } from '../../../components/ui/voice-orb';

const WELCOME_GREETINGS: Record<string, string> = {
  English: 'Welcome to Azure Hostel! I am your Hostel AI Assistant. Ask me anything about your hostel, mess menu, timings, rules, or room maintenance.',
  Malayalam: 'അസൂർ ഹോസ്റ്റലിലേക്ക് സ്വാഗതം! ഞാൻ നിങ്ങളുടെ ഹോസ്റ്റൽ AI അസിസ്റ്റന്റ് ആണ്.',
  Hindi: 'अज़ूर हॉस्टल में आपका स्वागत है! मैं आपका हॉस्टल AI सहायक हूँ।',
  Tamil: 'அஸூர் ஹாஸ்டலுக்கு நல்வரவு! நான் உங்கள் ஹாஸ்டல் AI உதவியாளர்.',
  Telugu: 'అజూర్ హాస్టల్‌కి స్వాగతం! నేను మీ హాస్టల్ AI సహాయకుడిని.',
  Kannada: 'ಅಜೂರ್ ಹಾಸ್ಟೆಲ್‌ಗೆ ಸುಸ್ವಾಗತ! ನಾನು ನಿಮ್ಮ ಹಾಸ್ಟೆಲ್ AI ಸಹಾಯಕ.'
};

const FALLBACK_RESPONSES: Record<string, string> = {
  English: 'Thank you for asking! Hostel gate and dining operations are fully running today. Dinner is served at 08:00 PM.',
  Malayalam: 'ചോദിച്ചതിന് നന്ദി! ഹോസ്റ്റൽ ഗേറ്റും മെസ് ഡൈനിംഗും ഇന്ന് തടസ്സമില്ലാതെ പ്രവർത്തിക്കുന്നു.',
  Hindi: 'पूछने के लिए धन्यवाद! हॉस्टल गेट और मैस डायनिंग आज सामान्य रूप से चालू हैं।',
  Tamil: 'கேட்டதற்கு நன்றி! ஹாஸ்டல் கேட் மற்றும் മെസ് இயங்குகின்றன.',
  Telugu: 'అడిగినందుకు ధన్యవాదాలు! హాస్టల్ గేట్ మరియు డైనింగ్ ఈరోజు అందుబాటులో ఉన్నాయి.',
  Kannada: 'ಕೇಳಿದ್ದಕ್ಕಾಗಿ ಧನ್ಯವಾದಗಳು! ಹಾಸ್ಟೆಲ್ ಗೇಟ್ ಮತ್ತು ಡೈನಿಂಗ್ ಇಂದು ಸರಿಯಾಗಿ ಕಾರ್ಯನಿರ್ವಹಿಸುತ್ತಿದೆ.'
};

const THINKING_TEXTS: Record<string, string> = {
  English: 'Hostel AI is thinking...',
  Malayalam: 'ഹോസ്റ്റൽ AI ചിന്തിക്കുന്നു...',
  Hindi: 'हॉस्टल AI सोच रहा है...',
  Tamil: 'ஹாஸ்டல் AI யோசிக்கிறது...',
  Telugu: 'హాస్టల్ AI ఆలోచిస్తోంది...',
  Kannada: 'ಹಾಸ್ಟೆಲ್ AI ಯೋಚಿಸುತ್ತಿದೆ...'
};

const VOICE_STATUS_TEXTS: Record<string, { idle: string; listening: string; thinking: string; speaking: string }> = {
  English: {
    idle: 'Tap Orb & Speak to Hostel Assistant',
    listening: 'Listening to your voice...',
    thinking: 'Hostel AI processing...',
    speaking: 'Speaking response...'
  },
  Malayalam: {
    idle: 'ഓർബ് ടാപ്പ് ചെയ്ത് ഹോസ്റ്റൽ AI-യോട് സംസാരിക്കുക',
    listening: 'ശ്രദ്ധിക്കുന്നു...',
    thinking: 'ഹോസ്റ്റൽ AI ചിന്തിക്കുന്നു...',
    speaking: 'മറുപടി നൽകുന്നു...'
  },
  Hindi: {
    idle: 'ऑर्ब टैप करें और हॉस्टल AI से बात करें',
    listening: 'सुन रहा है...',
    thinking: 'हॉस्टल AI सोच रहा है...',
    speaking: 'उत्तर दे रहा है...'
  },
  Tamil: {
    idle: 'ஆர்பைத் தட்டி ஹாஸ்டல் AI-யிடம் பேசவும்',
    listening: 'கேட்கிறது...',
    thinking: 'ஹாஸ்டல் AI யோசிக்கிறது...',
    speaking: 'பதிலளிக்கிறது...'
  },
  Telugu: {
    idle: 'ఆర్బ్‌ని నొక్కి హాస్టల్ AIతో మాట్లాడండి',
    listening: 'వింటోంది...',
    thinking: 'హాస్టల్ AI ఆలోచిస్తోంది...',
    speaking: 'సమాధానం ఇస్తోంది...'
  },
  Kannada: {
    idle: 'ಆರ್ಬ್ ತಟ್ಟಿ ಹಾಸ್ಟೆಲ್ AI ಜೊತೆ ಮಾತನಾಡಿ',
    listening: 'ಕೇಳಿಸಿಕೊಳ್ಳುತ್ತಿದೆ...',
    thinking: 'ಹಾಸ್ಟೆಲ್ AI ಯೋಚಿಸುತ್ತಿದೆ...',
    speaking: 'ಉತ್ತರಿಸುತ್ತಿದೆ...'
  }
};

const ACTION_CHIPS: Record<string, { dinner: string; timing: string; rules: string; laundry: string; fan: string; status: string; notices: string }> = {
  English: {
    dinner: "🍽️ What's for dinner today?",
    timing: '⏰ What time is dinner?',
    rules: '📜 Visitor Rules',
    laundry: '🧺 Where is the laundry?',
    fan: "🔧 My fan isn't working.",
    status: '🔍 Complaint Status',
    notices: "📢 Today's Notices"
  },
  Malayalam: {
    dinner: '🍽️ ഇന്നത്തെ അത്താഴം എന്താണ്?',
    timing: '⏰ അത്താഴ സമയം എപ്പോഴാണ്?',
    rules: '📜 സന്ദർശക നിയമങ്ങൾ',
    laundry: '🧺 ലോൺട്രി എവിടെയാണ്?',
    fan: '🔧 ഫാൻ പ്രവർത്തിക്കുന്നില്ല',
    status: '🔍 പരാതിയുടെ അവസ്ഥ',
    notices: '📢 ഇന്നത്തെ നോട്ടീസുകൾ'
  },
  Hindi: {
    dinner: '🍽️ आज रात के खाने में क्या है?',
    timing: '⏰ डिनर का समय क्या है?',
    rules: '📜 विजिटर नियम',
    laundry: '🧺 लॉन्ड्री कहाँ है?',
    fan: '🔧 पंखा काम नहीं कर रहा',
    status: '🔍 शिकायत की स्थिति',
    notices: '📢 आज के नोटिस'
  },
  Tamil: {
    dinner: '🍽️ இன்று இரவு உணவு என்ன?',
    timing: '⏰ இரவு உணவு நேரம் என்ன?',
    rules: '📜 பார்வையாளர் விதிகள்',
    laundry: '🧺 துணி துவைக்கும் இடம்',
    fan: '🔧 பேன் வேலை செய்யவில்லை',
    status: '🔍 புகாரின் நிலை',
    notices: '📢 இன்றைய அறிவிப்புகள்'
  },
  Telugu: {
    dinner: '🍽️ ఈరోజు డిన్నర్ ఏమిటి?',
    timing: '⏰ డిన్నర్ సమయం ఎంత?',
    rules: '📜 విజిటర్ నిబంధనలు',
    laundry: '🧺 లాండ్రీ ఎక్కడ ఉంది?',
    fan: '🔧 ఫ్యాన్ పనిచేయడం లేదు',
    status: '🔍 ఫిర్యాదు స్థితి',
    notices: '📢 నేటి నోటీసులు'
  },
  Kannada: {
    dinner: '🍽️ ಇಂದಿನ ಊಟ ಏನು?',
    timing: '⏰ ಊಟದ ಸಮಯ ಎಷ್ಟು?',
    rules: '📜 ಭೇಟಿಯ ನಿಯಮಗಳು',
    laundry: '🧺 ಲಾಂಡ್ರಿ ಎಲ್ಲಿದೆ?',
    fan: '🔧 ಫ್ಯಾನ್ ಕೆಲಸ ಮಾಡುತ್ತಿಲ್ಲ',
    status: '🔍 ದೂರಿನ ಸ್ಥಿತಿ',
    notices: '📢 ಇಂದಿನ ನೋಟಿಸ್‌ಗಳು'
  }
};

const PLACEHOLDERS: Record<string, string> = {
  English: 'Ask me anything about your hostel (mess menu, timings, rules, maintenance)...',
  Malayalam: 'ഹോസ്റ്റലിനെക്കുറിച്ച് എന്തും ചോദിക്കുക...',
  Hindi: 'अपने हॉस्टल के बारे में कुछ भी पूछें...',
  Tamil: 'உங்கள் ஹாஸ்டல் பற்றி எதையும் கேட்கவும்...',
  Telugu: 'మీ హాస్టల్ గురించి ఏదైనా అడగండి...',
  Kannada: 'ನಿಮ್ಮ ಹಾಸ್ಟೆಲ್ ಬಗ್ಗೆ ಕೇಳಿ...'
};

export default function ResidentHostelAssistantPage() {
  const [mode, setMode] = useState<'chat' | 'voice'>('chat');
  const [voiceState, setVoiceState] = useState<'idle' | 'listening' | 'thinking' | 'speaking'>('idle');
  const [language, setLanguage] = useState('English');
  const languageRef = useRef('English');

  const [messages, setMessages] = useState([
    { sender: 'agent', text: WELCOME_GREETINGS.English }
  ]);
  const [propertyTitle, setPropertyTitle] = useState('Azure Palm Hostel & Campus Residence');
  const [propertySubtitle, setPropertySubtitle] = useState('Hostel Assistant • Campus Block A');
  const [inputText, setInputText] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  const [statusNotice, setStatusNotice] = useState<string | null>(null);

  // Real-Time Server-Sent Events (SSE) Stream Listener for Resident Chat
  React.useEffect(() => {
    try {
      const eventSource = new EventSource(`${API_BASE}/api/v1/live-updates/events?organization_id=org_azure_group&property_id=prop_azure_palm_resort`);
      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          if (data.type === 'LIVE_UPDATE_CHANGED') {
            setStatusNotice(`⚡ Live Update: ${data.title || 'New hostel operational update available'}`);
            setTimeout(() => setStatusNotice(null), 6000);
          }
        } catch (e) {
          console.warn('SSE parse error:', e);
        }
      };
      return () => eventSource.close();
    } catch (e) {
      console.warn('SSE stream fallback:', e);
    }
  }, []);

  const getLanguageTag = (lang: string) => {
    switch (lang) {
      case 'Malayalam': return 'ml-IN';
      case 'Hindi': return 'hi-IN';
      case 'Tamil': return 'ta-IN';
      case 'Telugu': return 'te-IN';
      case 'Kannada': return 'kn-IN';
      default: return 'en-US';
    }
  };

  const getApiEndpoint = () => {
    return `${API_BASE}/api/v1/agents/agt_hostel_01/chat`;
  };

  const sendVoiceMessage = async (queryText: string): Promise<string | null> => {
    const activeLang = languageRef.current || language;
    try {
      const res = await fetch(getApiEndpoint(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          organization_id: 'org_azure_group',
          property_id: 'prop_azure_palm_resort',
          message: activeLang !== 'English' ? `[Language: ${activeLang}] ${queryText}` : queryText,
          channel: 'voice_session',
          language: activeLang
        })
      });
      const data = await res.json();
      setMessages(prev => [...prev, { sender: 'user', text: queryText }, { sender: 'agent', text: data.response }]);
      return data.response;
    } catch (e) {
      console.error("Voice execution error:", e);
      const fb = FALLBACK_RESPONSES[activeLang] || FALLBACK_RESPONSES.English;
      setMessages(prev => [...prev, { sender: 'user', text: queryText }, { sender: 'agent', text: fb }]);
      return fb;
    }
  };

  const speakResponse = async (text: string) => {
    const activeLang = languageRef.current || language;
    setVoiceState('speaking');
    try {
      const res = await fetch(`${API_BASE}/api/v1/voice/tts`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text, language: activeLang })
      });
      const data = await res.json();
      if (data && data.audio_base64) {
        const mimeType = data.format || 'audio/mp3';
        const audio = new Audio(`data:${mimeType};base64,${data.audio_base64}`);
        audio.onended = () => setVoiceState('idle');
        audio.onerror = () => fallbackBrowserSpeech(text, activeLang);
        try {
          const playPromise = audio.play();
          if (playPromise !== undefined) {
            await playPromise;
          }
        } catch (playErr) {
          console.warn('Audio play promise blocked:', playErr);
          fallbackBrowserSpeech(text, activeLang);
        }
      } else {
        fallbackBrowserSpeech(text, activeLang);
      }
    } catch (e) {
      fallbackBrowserSpeech(text, activeLang);
    }
  };

  const fallbackBrowserSpeech = (text: string, lang: string) => {
    setVoiceState('speaking');
    let timer = setTimeout(() => setVoiceState('idle'), 4500);

    if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
      try {
        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(text);
        const tag = getLanguageTag(lang);
        utterance.lang = tag;
        
        const voices = window.speechSynthesis.getVoices();
        const matchingVoice = voices.find(v => v.lang.toLowerCase().startsWith(tag.split('-')[0].toLowerCase()));
        if (matchingVoice) utterance.voice = matchingVoice;

        utterance.onend = () => {
          clearTimeout(timer);
          setVoiceState('idle');
        };
        utterance.onerror = () => {
          clearTimeout(timer);
          setVoiceState('idle');
        };
        window.speechSynthesis.speak(utterance);
      } catch (err) {
        console.warn('SpeechSynthesis error:', err);
      }
    }
  };

  const startVoiceInput = () => {
    const activeLang = languageRef.current || language;

    // Gesture unlock audio playback context
    try {
      const unlockAudio = new Audio('data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=');
      unlockAudio.play().catch(() => {});
      if (typeof window !== 'undefined' && 'speechSynthesis' in window) {
        window.speechSynthesis.resume();
      }
    } catch (e) {}

    if (!('webkitSpeechRecognition' in window) && !('SpeechRecognition' in window)) {
      triggerSampleVoiceTurn();
      return;
    }

    try {
      const SpeechRecognition = (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
      const recognition = new SpeechRecognition();
      recognition.lang = getLanguageTag(activeLang);
      recognition.interimResults = false;
      recognition.maxAlternatives = 1;

      setVoiceState('listening');

      recognition.onresult = async (event: any) => {
        const transcript = event.results[0][0].transcript;
        setVoiceState('thinking');
        const reply = await sendVoiceMessage(transcript);
        if (reply) {
          speakResponse(reply);
        } else {
          setVoiceState('idle');
        }
      };

      recognition.onerror = () => {
        setVoiceState('idle');
        triggerSampleVoiceTurn();
      };

      recognition.onend = () => {
        if (voiceState === 'listening') {
          setVoiceState('idle');
        }
      };

      recognition.start();
    } catch (e) {
      triggerSampleVoiceTurn();
    }
  };

  const handleSendMessage = async (customMsg?: string) => {
    const activeLang = languageRef.current || language;
    const msgToSend = customMsg || inputText;
    if (!msgToSend.trim() || isLoading) return;

    setInputText('');
    setMessages(prev => [...prev, { sender: 'user', text: msgToSend }]);
    setIsLoading(true);

    try {
      const res = await fetch(getApiEndpoint(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          organization_id: 'org_azure_group',
          property_id: 'prop_azure_palm_resort',
          message: activeLang !== 'English' ? `[Language: ${activeLang}] ${msgToSend}` : msgToSend,
          channel: 'web_widget',
          language: activeLang
        })
      });

      if (res.ok) {
        const data = await res.json();
        setMessages(prev => [...prev, { sender: 'agent', text: data.response }]);
      } else {
        const fb = FALLBACK_RESPONSES[activeLang] || FALLBACK_RESPONSES.English;
        setMessages(prev => [...prev, { sender: 'agent', text: fb }]);
      }
    } catch (err) {
      const fb = FALLBACK_RESPONSES[activeLang] || FALLBACK_RESPONSES.English;
      setMessages(prev => [...prev, { sender: 'agent', text: fb }]);
    } finally {
      setIsLoading(false);
    }
  };

  const triggerSampleVoiceTurn = (queryText?: string) => {
    const activeLang = languageRef.current || language;
    const chipsForLang = ACTION_CHIPS[activeLang] || ACTION_CHIPS.English;
    const sampleQuery = (queryText && activeLang === 'English') ? queryText : chipsForLang.dinner;
    setVoiceState('listening');
    setTimeout(() => setVoiceState('thinking'), 1500);
    setTimeout(async () => {
      const reply = await sendVoiceMessage(sampleQuery);
      if (reply) speakResponse(reply);
      else setVoiceState('idle');
    }, 3000);
  };

  const currentChips = ACTION_CHIPS[language] || ACTION_CHIPS.English;
  const currentPlaceholder = PLACEHOLDERS[language] || PLACEHOLDERS.English;

  return (
    <div className="min-h-screen bg-white text-zinc-900 flex flex-col justify-between max-w-4xl mx-auto border-x border-zinc-200 font-sans shadow-sm">
      {/* 1-Click Unified Portal Switcher */}
      <div className="flex items-center justify-between bg-zinc-100 p-2 border-b border-zinc-200 text-xs font-semibold px-4">
        <span className="text-zinc-500 font-mono text-[11px] font-semibold">PORTAL SWITCHER:</span>
        <div className="flex items-center gap-1">
          <Link href="/app/dashboard" className="px-3 py-1 rounded-lg text-zinc-600 hover:text-zinc-900 transition-colors">
            🏨 Hostel SaaS Admin
          </Link>
          <Link href="/guest/agt_hostel_01" className="px-3 py-1 rounded-lg bg-zinc-900 text-white shadow-xs">
            💬 Resident AI Chat
          </Link>
          <Link href="/platform/dashboard" className="px-3 py-1 rounded-lg text-zinc-600 hover:text-zinc-900 transition-colors">
            🛡️ Super Admin
          </Link>
        </div>
      </div>

      {/* Hostel Assistant Header */}
      <header className="p-5 border-b border-zinc-200 bg-white flex items-center justify-between sticky top-0 z-50">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-xl bg-zinc-900 text-white font-bold flex items-center justify-center text-xl shadow-xs">
            🏢
          </div>
          <div>
            <h1 className="text-base font-bold text-zinc-900 flex items-center gap-2">
              Hostel Assistant <span className="w-2 h-2 rounded-full bg-emerald-500"></span>
            </h1>
            <p className="text-xs text-zinc-500 font-medium">Ask me anything about your hostel</p>
          </div>
        </div>

        {/* Header Right Actions */}
        <div className="flex items-center gap-3">
          <select 
            value={language}
            onChange={(e) => {
              const newLang = e.target.value;
              languageRef.current = newLang;
              setLanguage(newLang);
              setMessages(prev => {
                const newGreeting = WELCOME_GREETINGS[newLang] || WELCOME_GREETINGS.English;
                if (prev.length === 0) return [{ sender: 'agent', text: newGreeting }];
                if (prev[0].sender === 'agent') {
                  const copy = [...prev];
                  copy[0] = { sender: 'agent', text: newGreeting };
                  return copy;
                }
                return prev;
              });
            }}
            className="bg-zinc-50 border border-zinc-200 rounded-lg px-3 py-1.5 text-xs text-zinc-800 focus:outline-none font-semibold cursor-pointer"
          >
            {['English', 'Malayalam', 'Hindi', 'Tamil', 'Kannada', 'Telugu'].map(lang => (
              <option key={lang} value={lang}>{lang}</option>
            ))}
          </select>

          <div className="flex bg-zinc-100 p-1 rounded-xl border border-zinc-200 text-xs font-semibold">
            <button 
              onClick={() => setMode('chat')}
              className={`px-3 py-1 rounded-lg transition-colors ${mode === 'chat' ? 'bg-zinc-900 text-white shadow-xs' : 'text-zinc-600 hover:text-zinc-900'}`}
            >
              💬 Text Chat
            </button>
            <button 
              onClick={() => setMode('voice')}
              className={`px-3 py-1 rounded-lg transition-colors ${mode === 'voice' ? 'bg-zinc-900 text-white shadow-xs' : 'text-zinc-600 hover:text-zinc-900'}`}
            >
              🎙️ Indic Voice
            </button>
          </div>
        </div>
      </header>

      {/* Main Container */}
      <main className="flex-1 p-6 flex flex-col justify-between overflow-y-auto space-y-6">
        {mode === 'voice' ? (
          <div className="flex-1 flex flex-col items-center justify-center space-y-6 py-6">
            <VoiceOrb state={voiceState} onToggleRecord={startVoiceInput} />
            <div className="text-center space-y-2">
              <h2 className="text-base font-bold text-zinc-900">
                {(VOICE_STATUS_TEXTS[language] || VOICE_STATUS_TEXTS.English)[voiceState]}
              </h2>
              <p className="text-xs text-zinc-500 max-w-sm font-medium">
                Supports Sarvam AI Malayalam, Hindi, Tamil, Telugu, Kannada & English voice reception.
              </p>
            </div>

            {/* Real-time Voice Message Transcript Stream */}
            <div className="w-full max-w-xl space-y-3 mt-4 max-h-[220px] overflow-y-auto border-t border-zinc-200 pt-4 px-2">
              <div className="text-[11px] font-bold text-zinc-400 uppercase tracking-wider text-center">
                🎙️ Voice Conversation Log
              </div>
              {messages.map((m, idx) => (
                <div key={idx} className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`max-w-[85%] rounded-2xl px-4 py-2.5 text-xs shadow-2xs ${
                    m.sender === 'user' 
                      ? 'bg-zinc-900 text-white rounded-br-none' 
                      : 'bg-white border border-zinc-200 text-zinc-800 rounded-bl-none font-medium'
                  }`}>
                    {m.text}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="space-y-4 max-h-[600px] overflow-y-auto pr-2">
            {messages.map((m, idx) => (
              <div key={idx} className={`flex ${m.sender === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-2xl px-5 py-3 text-sm shadow-2xs ${
                  m.sender === 'user' 
                    ? 'bg-zinc-900 text-white rounded-br-none' 
                    : 'bg-white border border-zinc-200 text-zinc-800 rounded-bl-none'
                }`}>
                  {m.text}
                </div>
              </div>
            ))}

            {/* AI Thinking Animation */}
            {isLoading && (
              <div className="flex justify-start items-center gap-2">
                <div className="max-w-[80%] rounded-2xl px-5 py-3 text-sm bg-white border border-zinc-200 text-zinc-800 rounded-bl-none flex items-center gap-3 shadow-xs">
                  <div className="flex items-center gap-1.5">
                    <Sparkles className="w-4 h-4 text-emerald-600 animate-spin" />
                    <span className="text-xs font-semibold text-zinc-600">
                      {THINKING_TEXTS[language] || THINKING_TEXTS.English}
                    </span>
                  </div>
                  <div className="flex items-center gap-1">
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-bounce [animation-delay:-0.3s]"></span>
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-bounce [animation-delay:-0.15s]"></span>
                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-bounce"></span>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Quick Action Chips */}
        {mode === 'chat' && (
          <div className="py-3 flex gap-2 overflow-x-auto border-t border-zinc-200">
            <button onClick={() => handleSendMessage(currentChips.dinner)} className="px-3 py-1.5 rounded-lg bg-white border border-zinc-200 text-zinc-700 text-xs font-medium hover:bg-zinc-100 whitespace-nowrap shadow-xs cursor-pointer">
              {currentChips.dinner}
            </button>
            <button onClick={() => handleSendMessage(currentChips.timing)} className="px-3 py-1.5 rounded-lg bg-white border border-zinc-200 text-zinc-700 text-xs font-medium hover:bg-zinc-100 whitespace-nowrap shadow-xs cursor-pointer">
              {currentChips.timing}
            </button>
            <button onClick={() => handleSendMessage(currentChips.rules)} className="px-3 py-1.5 rounded-lg bg-white border border-zinc-200 text-zinc-700 text-xs font-medium hover:bg-zinc-100 whitespace-nowrap shadow-xs cursor-pointer">
              {currentChips.rules}
            </button>
            <button onClick={() => handleSendMessage(currentChips.laundry)} className="px-3 py-1.5 rounded-lg bg-white border border-zinc-200 text-zinc-700 text-xs font-medium hover:bg-zinc-100 whitespace-nowrap shadow-xs cursor-pointer">
              {currentChips.laundry}
            </button>
            <button onClick={() => handleSendMessage(currentChips.fan)} className="px-3 py-1.5 rounded-lg bg-white border border-zinc-200 text-zinc-700 text-xs font-medium hover:bg-zinc-100 whitespace-nowrap shadow-xs cursor-pointer">
              {currentChips.fan}
            </button>
            <button onClick={() => handleSendMessage(currentChips.status)} className="px-3 py-1.5 rounded-lg bg-white border border-zinc-200 text-zinc-700 text-xs font-medium hover:bg-zinc-100 whitespace-nowrap shadow-xs cursor-pointer">
              {currentChips.status}
            </button>
            <button onClick={() => handleSendMessage(currentChips.notices)} className="px-3 py-1.5 rounded-lg bg-white border border-zinc-200 text-zinc-700 text-xs font-medium hover:bg-zinc-100 whitespace-nowrap shadow-xs cursor-pointer">
              {currentChips.notices}
            </button>
          </div>
        )}
      </main>

      {/* Footer Input Bar */}
      {mode === 'chat' && (
        <footer className="p-5 border-t border-zinc-200 bg-white">
          <div className="flex items-center gap-3">
            <input 
              type="text" 
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleSendMessage()}
              placeholder={currentPlaceholder}
              className="flex-1 bg-zinc-50 border border-zinc-200 rounded-xl px-4 py-2.5 text-sm text-zinc-900 focus:outline-none focus:border-zinc-400 font-sans"
            />
            <button 
              onClick={() => handleSendMessage()}
              className="px-5 py-2.5 bg-zinc-900 hover:bg-black text-white font-semibold text-xs rounded-xl shadow-xs transition-colors flex items-center gap-1.5"
            >
              <Send className="w-3.5 h-3.5" /> Send
            </button>
          </div>
        </footer>
      )}
    </div>
  );
}

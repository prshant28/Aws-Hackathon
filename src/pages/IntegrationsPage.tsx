import React, { useState, useMemo } from 'react';
import {
  Plug, Search, Filter, CheckCircle2, ExternalLink, Settings as SettingsIcon,
  Mail, Calendar as CalendarIcon, FileText, MessageSquare, Cloud, Database,
  Github, Slack, Trello, Chrome, Zap, Bot, Globe, Youtube, BookOpen,
  Twitter, Linkedin, Music, Camera, Folder, HardDrive, Activity,
  Sparkles, Star, Shield, Layers, Plus, ArrowRight, Lock, Send, Pin,
  Hash, Cpu, Brain
} from 'lucide-react';
import { motion } from 'motion/react';

type IntCategory = 'productivity' | 'google' | 'communication' | 'developer' | 'social' | 'storage' | 'media' | 'ai';

interface Integration {
  id: string;
  name: string;
  desc: string;
  category: IntCategory;
  color: string;
  icon: any;
  status: 'connected' | 'available' | 'coming-soon';
  popular?: boolean;
  capabilities: string[];
}

const INTEGRATIONS: Integration[] = [
  // Google
  { id: 'gmail', name: 'Gmail', desc: 'Capture important emails as memories, summarise threads with AI', category: 'google', color: '#ea4335', icon: Mail, status: 'available', popular: true, capabilities: ['capture', 'summarise', 'reply'] },
  { id: 'gcal', name: 'Google Calendar', desc: 'Sync events, get briefings, schedule study sessions', category: 'google', color: '#4285f4', icon: CalendarIcon, status: 'available', popular: true, capabilities: ['sync', 'schedule', 'remind'] },
  { id: 'gdrive', name: 'Google Drive', desc: 'Auto-capture docs, sheets and slides into your brain', category: 'google', color: '#0f9d58', icon: HardDrive, status: 'available', popular: true, capabilities: ['capture', 'index', 'search'] },
  { id: 'gdocs', name: 'Google Docs', desc: 'Pull in documents, get summaries and key insights', category: 'google', color: '#4285f4', icon: FileText, status: 'available', capabilities: ['capture', 'summarise'] },
  { id: 'gphotos', name: 'Google Photos', desc: 'OCR text from photos, capture memorable moments', category: 'google', color: '#fbbc04', icon: Camera, status: 'coming-soon', capabilities: ['ocr', 'capture'] },
  { id: 'gkeep', name: 'Google Keep', desc: 'Sync notes and todos across your knowledge graph', category: 'google', color: '#fbbc04', icon: BookOpen, status: 'coming-soon', capabilities: ['sync', 'capture'] },
  { id: 'youtube', name: 'YouTube', desc: 'Auto-capture videos, transcribe and summarise content', category: 'google', color: '#ff0000', icon: Youtube, status: 'connected', popular: true, capabilities: ['transcribe', 'summarise', 'capture'] },

  // Productivity
  { id: 'notion', name: 'Notion', desc: 'Two-way sync with Notion pages and databases', category: 'productivity', color: '#fff', icon: FileText, status: 'available', popular: true, capabilities: ['sync', 'capture', 'organise'] },
  { id: 'obsidian', name: 'Obsidian', desc: 'Import vaults, build knowledge graphs', category: 'productivity', color: '#7c3aed', icon: Brain, status: 'available', capabilities: ['import', 'graph'] },
  { id: 'evernote', name: 'Evernote', desc: 'Migrate notes from Evernote into your second brain', category: 'productivity', color: '#00a82d', icon: BookOpen, status: 'available', capabilities: ['import', 'capture'] },
  { id: 'todoist', name: 'Todoist', desc: 'Sync tasks across both apps with smart prioritisation', category: 'productivity', color: '#e44332', icon: CheckCircle2, status: 'available', capabilities: ['sync', 'prioritise'] },
  { id: 'trello', name: 'Trello', desc: 'Mirror boards into your workspace with agent automation', category: 'productivity', color: '#0079bf', icon: Trello, status: 'available', capabilities: ['sync', 'automate'] },

  // Communication
  { id: 'slack', name: 'Slack', desc: 'Save important threads, get briefings in channels', category: 'communication', color: '#4a154b', icon: Slack, status: 'available', popular: true, capabilities: ['capture', 'briefing'] },
  { id: 'discord', name: 'Discord', desc: 'Capture server messages and bookmark resources', category: 'communication', color: '#5865f2', icon: MessageSquare, status: 'available', capabilities: ['capture', 'bookmark'] },
  { id: 'telegram', name: 'Telegram', desc: 'Send notes via bot, capture forwarded messages', category: 'communication', color: '#0088cc', icon: Send, status: 'available', capabilities: ['capture', 'bot'] },
  { id: 'whatsapp', name: 'WhatsApp', desc: 'Save important chats as searchable memories', category: 'communication', color: '#25d366', icon: MessageSquare, status: 'coming-soon', capabilities: ['capture'] },

  // Developer
  { id: 'github', name: 'GitHub', desc: 'Capture issues, PRs, and code snippets with context', category: 'developer', color: '#fff', icon: Github, status: 'available', popular: true, capabilities: ['capture', 'review', 'sync'] },
  { id: 'gitlab', name: 'GitLab', desc: 'Sync GitLab projects, MRs and pipeline events', category: 'developer', color: '#fc6d26', icon: Github, status: 'available', capabilities: ['sync', 'capture'] },
  { id: 'linear', name: 'Linear', desc: 'Bidirectional sync with Linear issues and cycles', category: 'developer', color: '#5e6ad2', icon: Activity, status: 'available', capabilities: ['sync', 'automate'] },
  { id: 'jira', name: 'Jira', desc: 'Mirror Jira tickets, get AI summaries on epics', category: 'developer', color: '#0052cc', icon: Layers, status: 'available', capabilities: ['sync', 'summarise'] },

  // Social
  { id: 'twitter', name: 'X (Twitter)', desc: 'Save bookmarks, threads and important tweets', category: 'social', color: '#1da1f2', icon: Twitter, status: 'available', popular: true, capabilities: ['capture', 'bookmarks'] },
  { id: 'linkedin', name: 'LinkedIn', desc: 'Capture posts, save articles and contacts', category: 'social', color: '#0a66c2', icon: Linkedin, status: 'available', capabilities: ['capture', 'sync'] },
  { id: 'reddit', name: 'Reddit', desc: 'Save posts, comments and subreddit highlights', category: 'social', color: '#ff4500', icon: MessageSquare, status: 'coming-soon', capabilities: ['capture'] },

  // Storage
  { id: 'dropbox', name: 'Dropbox', desc: 'Auto-capture documents from Dropbox folders', category: 'storage', color: '#0061ff', icon: Cloud, status: 'available', capabilities: ['capture', 'sync'] },
  { id: 'onedrive', name: 'OneDrive', desc: 'Pull in Office files and PDFs for AI processing', category: 'storage', color: '#0078d4', icon: Cloud, status: 'available', capabilities: ['capture', 'sync'] },
  { id: 's3', name: 'AWS S3', desc: 'Connect S3 buckets for large-scale data ingestion', category: 'storage', color: '#ff9900', icon: Database, status: 'coming-soon', capabilities: ['ingest'] },

  // Media
  { id: 'spotify', name: 'Spotify', desc: 'Capture podcast episodes, transcribe and summarise', category: 'media', color: '#1db954', icon: Music, status: 'available', capabilities: ['transcribe', 'capture'] },
  { id: 'pocket', name: 'Pocket', desc: 'Import saved articles into your knowledge graph', category: 'media', color: '#ee4056', icon: BookOpen, status: 'available', capabilities: ['import', 'summarise'] },
  { id: 'instapaper', name: 'Instapaper', desc: 'Sync read-later articles with AI summaries', category: 'media', color: '#fff', icon: BookOpen, status: 'available', capabilities: ['sync', 'summarise'] },

  // AI / Browser
  { id: 'chrome', name: 'Chrome Extension', desc: 'One-click capture from any webpage', category: 'ai', color: '#4285f4', icon: Chrome, status: 'connected', popular: true, capabilities: ['capture', 'highlight'] },
  { id: 'zapier', name: 'Zapier', desc: 'Connect to 5000+ apps via Zapier automations', category: 'ai', color: '#ff4a00', icon: Zap, status: 'available', popular: true, capabilities: ['automate', 'webhook'] },
  { id: 'make', name: 'Make.com', desc: 'Visual automation with no-code workflows', category: 'ai', color: '#6d00cc', icon: Activity, status: 'available', capabilities: ['automate'] },
  { id: 'openai', name: 'OpenAI API', desc: 'Bring your own key for unlimited AI processing', category: 'ai', color: '#10a37f', icon: Bot, status: 'connected', capabilities: ['llm', 'embed'] },
  { id: 'webhook', name: 'Generic Webhooks', desc: 'POST any payload to capture endpoints', category: 'ai', color: '#a78bfa', icon: Globe, status: 'available', capabilities: ['ingest', 'webhook'] },
];

const CATEGORIES: { key: IntCategory | 'all'; label: string; icon: any; color: string }[] = [
  { key: 'all', label: 'All', icon: Layers, color: '#a78bfa' },
  { key: 'google', label: 'Google', icon: Chrome, color: '#4285f4' },
  { key: 'productivity', label: 'Productivity', icon: CheckCircle2, color: '#10b981' },
  { key: 'communication', label: 'Communication', icon: MessageSquare, color: '#06b6d4' },
  { key: 'developer', label: 'Developer', icon: Github, color: '#a78bfa' },
  { key: 'social', label: 'Social', icon: Twitter, color: '#1da1f2' },
  { key: 'storage', label: 'Storage', icon: Cloud, color: '#3b82f6' },
  { key: 'media', label: 'Media', icon: Music, color: '#ec4899' },
  { key: 'ai', label: 'AI & Automation', icon: Bot, color: '#f59e0b' },
];

const IntegrationsPage: React.FC = () => {
  const [activeCategory, setActiveCategory] = useState<IntCategory | 'all'>('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [showOnlyConnected, setShowOnlyConnected] = useState(false);
  const [showPopularOnly, setShowPopularOnly] = useState(false);
  const [selectedIntegration, setSelectedIntegration] = useState<Integration | null>(null);

  const filtered = useMemo(() => {
    return INTEGRATIONS.filter(int => {
      if (activeCategory !== 'all' && int.category !== activeCategory) return false;
      if (showOnlyConnected && int.status !== 'connected') return false;
      if (showPopularOnly && !int.popular) return false;
      if (searchQuery && !int.name.toLowerCase().includes(searchQuery.toLowerCase()) && !int.desc.toLowerCase().includes(searchQuery.toLowerCase())) return false;
      return true;
    });
  }, [activeCategory, showOnlyConnected, showPopularOnly, searchQuery]);

  const connectedCount = INTEGRATIONS.filter(i => i.status === 'connected').length;
  const availableCount = INTEGRATIONS.filter(i => i.status === 'available').length;
  const comingSoonCount = INTEGRATIONS.filter(i => i.status === 'coming-soon').length;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '14px 0 28px', minHeight: 'calc(100vh - 5rem)' }}>

      {/* HERO HEADER */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 14 }}>
            <div style={{ width: 52, height: 52, borderRadius: 14, background: 'linear-gradient(135deg, rgba(34,211,238,0.25), rgba(6,182,212,0.18))', border: '1px solid rgba(34,211,238,0.4)', display: 'flex', alignItems: 'center', justifyContent: 'center', boxShadow: '0 0 28px rgba(34,211,238,0.2)' }}>
              <Plug size={24} color="#22d3ee" />
            </div>
            <div>
              <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '4px 12px', background: 'rgba(34,211,238,0.1)', border: '1px solid rgba(34,211,238,0.3)', borderRadius: 20, marginBottom: 6 }}>
                <div style={{ width: 6, height: 6, borderRadius: '50%', background: '#10b981', boxShadow: '0 0 8px #10b981' }} />
                <span style={{ fontSize: 10.5, fontWeight: 700, color: '#22d3ee', letterSpacing: '0.5px' }}>{INTEGRATIONS.length} INTEGRATIONS · GOOGLE + 3RD PARTY APPS</span>
              </div>
              <h2 style={{ fontSize: 'clamp(22px,3.5vw,30px)', fontWeight: 900, color: 'var(--text-1)', margin: 0, letterSpacing: '-0.6px', lineHeight: 1.05 }}>
                Integrations <span style={{ color: '#22d3ee' }}>✦</span>
              </h2>
              <p style={{ color: 'var(--text-3)', fontSize: 13.5, margin: '4px 0 0' }}>
                Capture and organise everything from Gmail, Drive, Slack, GitHub, Notion and 30+ more
              </p>
            </div>
          </div>
        </div>

        {/* Stats strip */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 10 }}>
          {[
            { icon: CheckCircle2, color: '#10b981', label: 'Connected', value: connectedCount, sub: 'syncing now' },
            { icon: Sparkles, color: '#3b82f6', label: 'Available', value: availableCount, sub: 'ready to connect' },
            { icon: Star, color: '#f59e0b', label: 'Popular', value: INTEGRATIONS.filter(i => i.popular).length, sub: 'most used' },
            { icon: Layers, color: '#a78bfa', label: 'Coming Soon', value: comingSoonCount, sub: 'in development' },
          ].map(stat => (
            <div key={stat.label} style={{ padding: '12px 14px', display: 'flex', alignItems: 'center', gap: 12, background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 13 }}>
              <div style={{ width: 40, height: 40, borderRadius: 10, background: `${stat.color}15`, border: `1px solid ${stat.color}30`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <stat.icon size={18} color={stat.color} />
              </div>
              <div>
                <div style={{ color: 'var(--text-3)', fontSize: 10.5, fontWeight: 700, letterSpacing: '1px', textTransform: 'uppercase' }}>{stat.label}</div>
                <div style={{ color: 'var(--text-1)', fontSize: 20, fontWeight: 800, lineHeight: 1.1 }}>{stat.value}</div>
                <div style={{ color: 'var(--text-3)', fontSize: 10.5, marginTop: 2 }}>{stat.sub}</div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* SEARCH + FILTERS */}
      <div style={{ background: 'var(--surface)', border: '1px solid var(--border)', borderRadius: 14, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <div style={{ flex: '1 1 280px', position: 'relative', minWidth: 220 }}>
            <Search size={14} color="var(--text-3)" style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)' }} />
            <input value={searchQuery} onChange={e => setSearchQuery(e.target.value)} placeholder="Search 30+ integrations..."
              style={{ width: '100%', padding: '10px 14px 10px 36px', borderRadius: 10, border: '1px solid var(--border)', background: 'var(--surface-2)', color: 'var(--text-1)', fontSize: 13, outline: 'none', fontFamily: 'inherit', boxSizing: 'border-box' }} />
          </div>
          <button onClick={() => setShowOnlyConnected(!showOnlyConnected)}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '9px 14px', background: showOnlyConnected ? 'rgba(16,185,129,0.12)' : 'var(--surface-2)', border: `1px solid ${showOnlyConnected ? 'rgba(16,185,129,0.4)' : 'var(--border)'}`, borderRadius: 10, color: showOnlyConnected ? '#10b981' : 'var(--text-2)', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
            <CheckCircle2 size={13} /> Connected only
          </button>
          <button onClick={() => setShowPopularOnly(!showPopularOnly)}
            style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '9px 14px', background: showPopularOnly ? 'rgba(245,158,11,0.12)' : 'var(--surface-2)', border: `1px solid ${showPopularOnly ? 'rgba(245,158,11,0.4)' : 'var(--border)'}`, borderRadius: 10, color: showPopularOnly ? '#f59e0b' : 'var(--text-2)', fontSize: 12, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
            <Star size={13} /> Popular
          </button>
        </div>

        {/* Category pills */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {CATEGORIES.map(cat => (
            <button key={cat.key} onClick={() => setActiveCategory(cat.key)}
              style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '7px 13px', background: activeCategory === cat.key ? `${cat.color}15` : 'transparent', border: `1px solid ${activeCategory === cat.key ? cat.color + '50' : 'var(--border)'}`, borderRadius: 20, color: activeCategory === cat.key ? cat.color : 'var(--text-2)', fontSize: 11.5, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit', transition: 'all 0.15s' }}>
              <cat.icon size={12} /> {cat.label}
              <span style={{ padding: '1px 6px', background: activeCategory === cat.key ? `${cat.color}20` : 'var(--surface-3)', borderRadius: 8, fontSize: 9.5, color: activeCategory === cat.key ? cat.color : 'var(--text-3)' }}>
                {cat.key === 'all' ? INTEGRATIONS.length : INTEGRATIONS.filter(i => i.category === cat.key).length}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* INTEGRATIONS GRID */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
        {filtered.map(int => {
          const isConnected = int.status === 'connected';
          const isComingSoon = int.status === 'coming-soon';
          return (
            <motion.div key={int.id} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} whileHover={{ y: -2 }}
              style={{ background: 'var(--surface)', border: `1px solid ${isConnected ? int.color + '40' : 'var(--border)'}`, borderRadius: 14, padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 10, transition: 'all 0.2s', cursor: isComingSoon ? 'default' : 'pointer', position: 'relative', overflow: 'hidden' }}
              onClick={() => !isComingSoon && setSelectedIntegration(int)}>
              {isConnected && (
                <div style={{ position: 'absolute', top: 0, right: 0, padding: '3px 10px', background: int.color, color: '#fff', fontSize: 9.5, fontWeight: 800, letterSpacing: '0.5px', borderRadius: '0 14px 0 8px' }}>
                  CONNECTED
                </div>
              )}
              {int.popular && !isConnected && (
                <div style={{ position: 'absolute', top: 8, right: 8, display: 'flex', alignItems: 'center', gap: 3, padding: '2px 7px', background: 'rgba(245,158,11,0.12)', border: '1px solid rgba(245,158,11,0.3)', borderRadius: 10, color: '#f59e0b', fontSize: 9, fontWeight: 700 }}>
                  <Star size={8} /> POPULAR
                </div>
              )}
              <div style={{ display: 'flex', alignItems: 'flex-start', gap: 11 }}>
                <div style={{ width: 42, height: 42, borderRadius: 11, background: `${int.color}15`, border: `1px solid ${int.color}30`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                  <int.icon size={20} color={int.color} />
                </div>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <h4 style={{ margin: '2px 0 4px', color: 'var(--text-1)', fontSize: 14, fontWeight: 800, letterSpacing: '-0.2px' }}>{int.name}</h4>
                  <p style={{ margin: 0, color: 'var(--text-3)', fontSize: 11.5, lineHeight: 1.45 }}>{int.desc}</p>
                </div>
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {int.capabilities.map(cap => (
                  <span key={cap} style={{ padding: '2px 8px', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 12, color: 'var(--text-3)', fontSize: 9.5, fontWeight: 600 }}>{cap}</span>
                ))}
              </div>
              <button disabled={isComingSoon}
                style={{ marginTop: 4, padding: '8px 12px', background: isConnected ? 'var(--surface-2)' : isComingSoon ? 'var(--surface-3)' : `${int.color}15`, border: `1px solid ${isConnected ? 'var(--border)' : isComingSoon ? 'var(--border)' : int.color + '40'}`, borderRadius: 9, color: isConnected ? 'var(--text-1)' : isComingSoon ? 'var(--text-3)' : int.color, fontSize: 11.5, fontWeight: 700, cursor: isComingSoon ? 'default' : 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 5, transition: 'all 0.15s' }}>
                {isConnected ? <><SettingsIcon size={11} /> Configure</> : isComingSoon ? <><Lock size={11} /> Coming soon</> : <><Plus size={11} /> Connect</>}
              </button>
            </motion.div>
          );
        })}
      </div>

      {filtered.length === 0 && (
        <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-3)', fontSize: 13 }}>
          <Search size={36} color="var(--border-2)" style={{ margin: '0 auto 12px' }} />
          <p style={{ margin: 0, fontWeight: 600 }}>No integrations match your filters</p>
          <p style={{ margin: '4px 0 0', fontSize: 12 }}>Try a different category or clear search</p>
        </div>
      )}

      {/* CONNECT MODAL */}
      {selectedIntegration && (
        <div onClick={() => setSelectedIntegration(null)} style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', backdropFilter: 'blur(6px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 9000, padding: 20 }}>
          <motion.div initial={{ opacity: 0, scale: 0.95, y: 10 }} animate={{ opacity: 1, scale: 1, y: 0 }} onClick={e => e.stopPropagation()}
            style={{ background: 'var(--surface)', border: `1px solid ${selectedIntegration.color}50`, borderRadius: 16, padding: '24px 26px', maxWidth: 480, width: '100%', boxShadow: '0 20px 60px rgba(0,0,0,0.5)' }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', gap: 14, marginBottom: 16 }}>
              <div style={{ width: 56, height: 56, borderRadius: 13, background: `${selectedIntegration.color}15`, border: `1px solid ${selectedIntegration.color}40`, display: 'flex', alignItems: 'center', justifyContent: 'center', flexShrink: 0 }}>
                <selectedIntegration.icon size={26} color={selectedIntegration.color} />
              </div>
              <div style={{ flex: 1 }}>
                <h3 style={{ margin: '2px 0 4px', color: 'var(--text-1)', fontSize: 18, fontWeight: 800, letterSpacing: '-0.3px' }}>{selectedIntegration.name}</h3>
                <p style={{ margin: 0, color: 'var(--text-3)', fontSize: 12.5, lineHeight: 1.5 }}>{selectedIntegration.desc}</p>
              </div>
            </div>
            <div style={{ padding: '12px 14px', background: 'var(--surface-2)', borderRadius: 11, marginBottom: 14 }}>
              <div style={{ color: 'var(--text-3)', fontSize: 10.5, fontWeight: 700, letterSpacing: '0.5px', textTransform: 'uppercase', marginBottom: 8 }}>Capabilities</div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5 }}>
                {selectedIntegration.capabilities.map(cap => (
                  <span key={cap} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '3px 9px', background: `${selectedIntegration.color}12`, border: `1px solid ${selectedIntegration.color}30`, borderRadius: 12, color: selectedIntegration.color, fontSize: 10.5, fontWeight: 700 }}>
                    <Hash size={9} /> {cap}
                  </span>
                ))}
              </div>
            </div>
            <div style={{ padding: '12px 14px', background: 'rgba(99,102,241,0.06)', border: '1px solid rgba(99,102,241,0.2)', borderRadius: 11, marginBottom: 16, display: 'flex', alignItems: 'flex-start', gap: 10 }}>
              <Shield size={14} color="#a78bfa" style={{ flexShrink: 0, marginTop: 2 }} />
              <div style={{ fontSize: 11.5, color: 'var(--text-2)', lineHeight: 1.5 }}>
                Recall X247 only requests minimal scopes needed for capture. Your data stays in your brain — we never share or sell it.
              </div>
            </div>
            <div style={{ display: 'flex', gap: 8 }}>
              <button onClick={() => setSelectedIntegration(null)} style={{ flex: 1, padding: '11px', background: 'var(--surface-2)', border: '1px solid var(--border)', borderRadius: 10, color: 'var(--text-2)', fontSize: 13, fontWeight: 600, cursor: 'pointer', fontFamily: 'inherit' }}>
                Cancel
              </button>
              <button style={{ flex: 2, padding: '11px', background: `linear-gradient(135deg, ${selectedIntegration.color}, ${selectedIntegration.color}cc)`, border: 'none', borderRadius: 10, color: '#fff', fontSize: 13, fontWeight: 700, cursor: 'pointer', fontFamily: 'inherit', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6, boxShadow: `0 4px 16px ${selectedIntegration.color}50` }}>
                Authorise {selectedIntegration.name} <ArrowRight size={13} />
              </button>
            </div>
          </motion.div>
        </div>
      )}
    </div>
  );
};

export default IntegrationsPage;

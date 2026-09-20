import { useEffect, useState, useCallback } from 'react';
import { motion } from 'motion/react';
import { nextTabIndex, panelProps, tabIds, tabProps } from '../lib/tablist';
import { fetchManagedAgents, createManagedAgent } from '../lib/api';
import type { ManagedAgent } from '../lib/api';
import { Database, MessageSquare, Loader2, Brain } from 'lucide-react';
import { MemorySection } from './data-sources/MemorySection';
import { MessagingSection } from './data-sources/MessagingSection';
import { DataSourcesSection } from './data-sources/DataSourcesSection';

// ---------------------------------------------------------------------------
// Inline connect form (reused from AgentsPage pattern)
// ---------------------------------------------------------------------------

export function DataSourcesPage() {
  const [agents, setAgents] = useState<ManagedAgent[]>([]);
  const [activeTab, setActiveTab] = useState<'sources' | 'messaging' | 'memory'>('sources');
  const [creatingAgent, setCreatingAgent] = useState(false);

  const loadAgents = useCallback(() => {
    fetchManagedAgents().then(setAgents).catch(() => {});
  }, []);

  useEffect(() => { loadAgents(); }, [loadAgents]);

  // Pick the first agent for messaging channel bindings.
  // If none exists and user opens Messaging tab, auto-create a default one.
  const firstAgent = agents[0];

  const ensureAgent = useCallback(async (): Promise<string | null> => {
    if (firstAgent) return firstAgent.id;
    setCreatingAgent(true);
    try {
      const agent = await createManagedAgent({
        name: "My Assistant",
        template_id: "personal_deep_research",
      });
      setAgents((prev) => [...prev, agent]);
      return agent.id;
    } catch {
      return null;
    } finally {
      setCreatingAgent(false);
    }
  }, [firstAgent]);

  // Auto-create agent when switching to messaging tab
  useEffect(() => {
    if (activeTab === 'messaging' && !firstAgent && !creatingAgent) {
      ensureAgent();
    }
  }, [activeTab, firstAgent, creatingAgent, ensureAgent]);

  const tabs = [
    { id: 'sources' as const, label: 'Data Sources', icon: Database },
    { id: 'messaging' as const, label: 'Messaging Channels', icon: MessageSquare },
    { id: 'memory' as const, label: 'Memory', icon: Brain },
  ];

  return (
    <div className="flex-1 overflow-y-auto px-6 py-10">
      <div className="max-w-5xl mx-auto">
      <header className="mb-6">
        <h1 className="text-lg font-semibold" style={{ color: 'var(--color-text)' }}>
          Data Sources, Channels &amp; Memory
        </h1>
        <p className="text-sm mt-2 max-w-2xl" style={{ color: 'var(--color-text-secondary)' }}>
          Connect personal data so the assistant can search across everything, and set up messaging channels to chat from your phone.
        </p>
      </header>

      <div
        role="tablist"
        aria-label="Data sources sections"
        className="flex gap-1 mb-6"
        style={{ borderBottom: '1px solid var(--color-border)' }}
        onKeyDown={(e) => {
          const at = tabs.findIndex((t) => t.id === activeTab);
          const next = nextTabIndex(e.key, at, tabs.length);
          if (next === null) return;
          e.preventDefault();
          setActiveTab(tabs[next].id);
          document.getElementById(tabIds('data-sources', tabs[next].id).tab)?.focus();
        }}
      >
        {tabs.map((tab) => {
          const isActive = activeTab === tab.id;
          return (
            <button
              key={tab.id}
              {...tabProps('data-sources', tab.id, isActive)}
              onClick={() => setActiveTab(tab.id)}
              className="relative px-4 py-2.5 text-sm transition-colors cursor-pointer"
              style={{
                color: isActive ? 'var(--color-text)' : 'var(--color-text-secondary)',
                fontWeight: isActive ? 600 : 400,
              }}
            >
              {tab.label}
              {isActive && (
                <motion.span
                  layoutId="data-sources-tab-indicator"
                  className="absolute left-0 right-0 -bottom-px h-[2px]"
                  style={{ background: 'var(--color-text)' }}
                  transition={{ type: 'spring', stiffness: 380, damping: 30 }}
                />
              )}
            </button>
          );
        })}
      </div>

      <div {...panelProps('data-sources', activeTab)}>
        {activeTab === 'sources' && <DataSourcesSection />}
        {activeTab === 'messaging' && (
          firstAgent ? (
            <MessagingSection agentId={firstAgent.id} />
          ) : creatingAgent ? (
            <div className="flex items-center gap-3 p-4 text-sm" style={{ color: 'var(--color-text-secondary)' }}>
              <Loader2 size={16} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
              Setting up your assistant...
            </div>
          ) : null
        )}
        {activeTab === 'memory' && <MemorySection />}
      </div>
      </div>
    </div>
  );
}

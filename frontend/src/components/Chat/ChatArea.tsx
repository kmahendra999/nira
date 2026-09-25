import { useRef, useEffect, useState, useCallback } from 'react';
import { useNavigate } from 'react-router';
import { MessageBubble } from './MessageBubble';
import { InputArea } from './InputArea';
import { ChatAnnouncer } from './ChatAnnouncer';
import { StreamingDots } from './StreamingDots';
import { useAppStore } from '../../lib/store';
import {
  Sparkles,
  PanelRightOpen,
  PanelRightClose,
  Database,
  MessageSquare,
  X,
  Image as ImageIcon,
  FileText,
} from 'lucide-react';
import { listConnectors } from '../../lib/connectors-api';

function getGreeting(): string {
  // A question rather than a greeting, per the reference. "Good morning" is
  // pleasant and tells you nothing; "Where should we start?" points at the
  // box below it.
  return 'Where should we start?';
}

/** A few concrete starting points, in the reference's shape. */
const SUGGESTIONS = [
  {
    icon: ImageIcon,
    label: 'Create an image',
    prompt: 'A quiet harbour at dawn, soft light on the water',
  },
  {
    icon: FileText,
    label: 'Summarise a document',
    prompt: 'Summarise the attached document and list its three main claims.',
  },
  {
    icon: Database,
    label: 'Ask about my data',
    prompt: 'What has come up most often in my messages this week?',
  },
];

export function ChatArea() {
  const activeId = useAppStore((s) => s.activeId);
  const messages = useAppStore((s) => s.messages);
  const streamState = useAppStore((s) => s.streamState);
  const systemPanelOpen = useAppStore((s) => s.systemPanelOpen);
  const toggleSystemPanel = useAppStore((s) => s.toggleSystemPanel);
  const navigate = useNavigate();
  const listRef = useRef<HTMLDivElement>(null);
  const shouldAutoScroll = useRef(true);
  const wasStreaming = useRef(false);
  const lastScrollTop = useRef(0);
  const isCurrentChatStreaming = streamState.isStreaming && streamState.conversationId === activeId;
  const currentStreamContent = isCurrentChatStreaming ? streamState.content : '';

  // Check if any data sources are connected
  const [hasConnectedSources, setHasConnectedSources] = useState<boolean | null>(null);
  const [bannerDismissed, setBannerDismissed] = useState(false);

  useEffect(() => {
    listConnectors()
      .then((list) => setHasConnectedSources(list.some((c) => c.connected)))
      .catch(() => setHasConnectedSources(null));
  }, []);

  useEffect(() => {
    // Sending a message always pins the view to the bottom, even if the
    // user had scrolled up to read earlier messages.
    if (isCurrentChatStreaming && !wasStreaming.current) {
      shouldAutoScroll.current = true;
    }
    wasStreaming.current = isCurrentChatStreaming;
    if (shouldAutoScroll.current && listRef.current) {
      listRef.current.scrollTop = listRef.current.scrollHeight;
    }
  }, [messages, currentStreamContent, isCurrentChatStreaming]);

  const handleScroll = () => {
    if (!listRef.current) return;
    const { scrollTop, scrollHeight, clientHeight } = listRef.current;
    const distance = scrollHeight - scrollTop - clientHeight;
    const scrolledUp = scrollTop < lastScrollTop.current;
    lastScrollTop.current = scrollTop;
    if (scrolledUp && distance >= 1) {
      // Any upward scroll away from the bottom stops autoscroll immediately,
      // so streaming content never fights the user (no jitter). Sub-1px
      // upward movement (elastic bounce settling at the bottom) is ignored.
      shouldAutoScroll.current = false;
    } else if (!scrolledUp) {
      // Re-engage when scrolled back to the bottom. < 2 rather than < 1:
      // at fractional zoom levels the at-bottom residual can reach 1px,
      // which would otherwise leave autoscroll permanently disengaged.
      shouldAutoScroll.current = distance < 2;
    }
  };

  const isEmpty = messages.length === 0 && !isCurrentChatStreaming;

  const PanelIcon = systemPanelOpen ? PanelRightClose : PanelRightOpen;

  return (
    <div className="flex flex-col h-full">
      {/* Toggle bar */}
      <div className="flex items-center justify-end px-3 py-1.5 shrink-0">
        <button
          onClick={toggleSystemPanel}
          className="p-1.5 rounded-md transition-colors cursor-pointer"
          style={{ color: 'var(--color-text-tertiary)' }}
          title={`${systemPanelOpen ? 'Hide' : 'Show'} system panel (${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+I)`}
        >
          <PanelIcon size={16} />
        </button>
      </div>

      {/* Data sources banner */}
      {hasConnectedSources === false && !bannerDismissed && (
        <div
          className="mx-4 mb-2 flex items-center gap-3 px-4 py-3 rounded-lg text-sm shrink-0"
          style={{
            background: 'var(--color-accent-subtle)',
            border: '1px solid var(--color-border)',
          }}
        >
          <Database size={16} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
          <span style={{ color: 'var(--color-text-secondary)', flex: 1 }}>
            Connect your data sources (Gmail, iMessage, Slack, etc.) to get personalized answers.
          </span>
          <button
            onClick={() => navigate('/data-sources')}
            className="px-3 py-1 rounded text-xs font-medium cursor-pointer"
            style={{ background: 'var(--color-accent)', color: 'var(--color-on-accent)', border: 'none' }}
          >
            Connect
          </button>
          <button
            onClick={() => setBannerDismissed(true)}
            className="p-1 rounded cursor-pointer"
            style={{ color: 'var(--color-text-tertiary)', background: 'transparent', border: 'none' }}
          >
            <X size={14} />
          </button>
        </div>
      )}
      <div
        ref={listRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto"
      >
        {isEmpty ? (
          /* The reference layout: one large question, and a few things you
             could actually do, rather than a paragraph explaining the product
             to someone who has already installed it. The composer sits below
             this in the normal flow, so the eye lands on the heading, then
             the input, then the suggestions. */
          <div className="flex flex-col items-center justify-center h-full px-4">
            <h2
              className="text-3xl md:text-4xl font-normal text-center mb-8"
              style={{ color: 'var(--color-text)' }}
            >
              {getGreeting()}
            </h2>

            <div className="flex flex-col gap-1 w-full max-w-md">
              {SUGGESTIONS.map(({ icon: Icon, label, prompt }) => (
                <button
                  key={label}
                  onClick={() => {
                    // Put it in the composer rather than sending it: a
                    // suggestion is a starting point, and firing it off
                    // immediately takes the edit away from the user.
                    window.dispatchEvent(
                      new CustomEvent('nira-compose', { detail: prompt }),
                    );
                  }}
                  className="flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm
                    text-left cursor-pointer transition-colors bg-transparent
                    hover:bg-bg-secondary"
                  style={{ color: 'var(--color-text-secondary)' }}
                >
                  <Icon size={16} style={{ color: 'var(--color-text-tertiary)' }} />
                  {label}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="max-w-[var(--chat-max-width)] mx-auto px-4 py-6">
            {messages.map((msg, i) => {
              const isLastAssistant =
                i === messages.length - 1 && msg.role === 'assistant';
              return (
                <MessageBubble
                  key={msg.id}
                  message={msg}
                  isLive={isLastAssistant && isCurrentChatStreaming}
                />
              );
            })}
            {(() => {
              if (!isCurrentChatStreaming || streamState.content !== '') return null;
              // For research messages the ResearchTimeline handles its own
              // pre-content loading state — suppress the generic dots.
              const last = messages[messages.length - 1];
              if (last?.role === 'assistant' && last.isResearch) return null;
              return (
                <div className="flex justify-start mb-4">
                  <StreamingDots phase={streamState.phase} />
                </div>
              );
            })()}
          </div>
        )}
      </div>
      <InputArea />
      <ChatAnnouncer
        streaming={isCurrentChatStreaming}
        phase={streamState.phase}
        content={currentStreamContent}
      />
    </div>
  );
}

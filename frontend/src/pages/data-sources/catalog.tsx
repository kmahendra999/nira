/**
 * Which icon and catalog entry a connector gets.
 *
 * Shared by the panels that offer a source and the section that lists them,
 * so it belongs beside both rather than in the page that used to hold
 * everything.
 */

import {
  FolderOpen,
  FileText,
  Mail,
  Hash,
  MessageCircle,
  CalendarDays,
  Contact,
  StickyNote,
  BookText,
  Package,
  Upload,
  Link2,
  PhoneCall,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { SOURCE_CATALOG } from '../../types/connectors';

export const iconMap: Record<string, LucideIcon> = {
  gmail: Mail,
  gmail_imap: Mail,
  gmail_api: Mail,
  outlook: Mail,
  slack: Hash,
  imessage: MessageCircle,
  whatsapp: PhoneCall,
  gdrive: FolderOpen,
  dropbox: Package,
  notion: BookText,
  obsidian: FileText,
  apple_notes: StickyNote,
  granola: FileText,
  gcalendar: CalendarDays,
  gcontacts: Contact,
  apple_contacts: Contact,
  upload: Upload,
};

export const IconFor = ({ id, size = 18 }: { id: string; size?: number }) => {
  const Ico = iconMap[id] ?? Link2;
  return <Ico size={size} />;
};

// The Gmail card unifies the OAuth (`gmail`) and IMAP (`gmail_imap`) backend
// connectors — both should resolve to the gmail_imap catalog entry so the
// connected card shows the same name, unit label, and troubleshooting tips
// regardless of which underlying flow the user picked.
export function metaFor(connectorId: string) {
  const id = connectorId === 'gmail' ? 'gmail_imap' : connectorId;
  return SOURCE_CATALOG.find((s) => s.connector_id === id);
}

// Advanced OAuth disclosure for the unified Gmail card. Hidden by default;
// expands to a Client ID + Client Secret form that POSTs to the OAuth
// `gmail` backend connector. Lives here rather than in SOURCE_CATALOG
// because the Gmail card is the only one with a dual-flow shape.

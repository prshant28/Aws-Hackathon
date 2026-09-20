import React, { lazy } from 'react';
import { Library, Database, StickyNote, Bookmark, FileText, Inbox, CheckSquare, Flame, FlipHorizontal, Bell, Tag, Trash2 } from 'lucide-react';
import TabbedPage from '../components/TabbedPage';

const VaultPage = lazy(() => import('./VaultPage'));
const NotesPage = lazy(() => import('./NotesPage'));
const BookmarksPage = lazy(() => import('./BookmarksPage'));
const TasksPage = lazy(() => import('./TasksPage'));
const HabitsPage = lazy(() => import('./HabitsPage'));
const FlashcardsPage = lazy(() => import('./FlashcardsPage'));
const RevisitsPage = lazy(() => import('./RevisitsPage'));
const LibraryInboxTab = lazy(() => import('../components/LibraryInboxTab'));
const TrashPage = lazy(() => import('./TrashPage'));
const TagsManagerPage = lazy(() => import('./TagsManagerPage'));

const LibraryPage: React.FC = () => {
  return (
    <TabbedPage
      icon={Library}
      iconColor="#f472b6"
      iconBg="rgba(244,114,182,0.15)"
      title="Library"
      subtitle="Vault, notes, bookmarks, files, inbox, tasks, habits, flashcards & revisits — your full second brain in one place"
      hub="library"
      paramKey="tab"
      defaultTab="vault"
      tabs={[
        { id: 'vault',      label: 'Vault',      icon: Database,        render: () => <VaultPage embedded storageKey="recall:library:vault" /> },
        { id: 'notes',      label: 'Notes',      icon: StickyNote,      render: () => <NotesPage embedded /> },
        { id: 'bookmarks',  label: 'Bookmarks',  icon: Bookmark,        render: () => <BookmarksPage embedded /> },
        { id: 'files',      label: 'Files',      icon: FileText,        render: () => <VaultPage embedded initialSourceFilter="pdf" storageKey="recall:library:files" /> },
        { id: 'inbox',      label: 'Inbox',      icon: Inbox,           render: () => <LibraryInboxTab /> },
        { id: 'tags',       label: 'Tags',       icon: Tag,             render: () => <TagsManagerPage /> },
        { id: 'tasks',      label: 'Tasks',      icon: CheckSquare,     render: () => <TasksPage embedded /> },
        { id: 'habits',     label: 'Habits',     icon: Flame,           render: () => <HabitsPage embedded /> },
        { id: 'flashcards', label: 'Flashcards', icon: FlipHorizontal,  render: () => <FlashcardsPage embedded /> },
        { id: 'revisits',   label: 'Revisits',   icon: Bell,            render: () => <RevisitsPage embedded /> },
        { id: 'trash',      label: 'Trash',      icon: Trash2,          render: () => <TrashPage /> },
      ]}
    />
  );
};

export default LibraryPage;

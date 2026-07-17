import { create } from 'zustand';
import type {
  Repository,
  RepositoryFile,
  FileContent,
  ChatMessage,
  IndexingStatus,
} from '../types';

interface AppStore {
  // Repository state
  currentRepository: Repository | null;
  repositoryFiles: RepositoryFile[];
  indexingStatus: IndexingStatus | null;
  setCurrentRepository: (repo: Repository) => void;
  setRepositoryFiles: (files: RepositoryFile[]) => void;
  setIndexingStatus: (status: IndexingStatus) => void;

  // Editor state
  openFiles: Map<string, FileContent>;
  activeFile: string | null;
  selectedCode: string | null;
  selectedCodeRange?: { start: number; end: number };
  
  openFile: (file: FileContent) => void;
  closeFile: (path: string) => void;
  setActiveFile: (path: string) => void;
  updateFileContent: (path: string, content: string) => void;
  setSelectedCode: (code: string | null) => void;

  // Chat state
  chatMessages: ChatMessage[];
  chatLoading: boolean;
  chatError: string | null;
  
  addChatMessage: (message: ChatMessage) => void;
  clearChatMessages: () => void;
  setChatLoading: (loading: boolean) => void;
  setChatError: (error: string | null) => void;

  // UI state
  sidebarOpen: boolean;
  explorerExpanded: Map<string, boolean>;
  
  toggleSidebar: () => void;
  toggleExplorerNode: (path: string) => void;
  
  // File explorer state
  expandedFolders: Set<string>;
  toggleFolder: (path: string) => void;
}

export const useAppStore = create<AppStore>((set) => ({
  // Repository state
  currentRepository: null,
  repositoryFiles: [],
  indexingStatus: null,
  setCurrentRepository: (repo) => set({ currentRepository: repo }),
  setRepositoryFiles: (files) => set({ repositoryFiles: files }),
  setIndexingStatus: (status) => set({ indexingStatus: status }),

  // Editor state
  openFiles: new Map(),
  activeFile: null,
  selectedCode: null,
  
  openFile: (file) =>
    set((state) => {
      const newOpenFiles = new Map(state.openFiles);
      newOpenFiles.set(file.path, file);
      return {
        openFiles: newOpenFiles,
        activeFile: file.path,
      };
    }),

  closeFile: (path) =>
    set((state) => {
      const newOpenFiles = new Map(state.openFiles);
      newOpenFiles.delete(path);
      const remaining = Array.from(newOpenFiles.keys());
      return {
        openFiles: newOpenFiles,
        activeFile: remaining.length > 0 ? remaining[remaining.length - 1] : null,
      };
    }),

  setActiveFile: (path) => set({ activeFile: path }),

  updateFileContent: (path, content) =>
    set((state) => {
      const newOpenFiles = new Map(state.openFiles);
      const file = newOpenFiles.get(path);
      if (file) {
        newOpenFiles.set(path, { ...file, content });
      }
      return { openFiles: newOpenFiles };
    }),

  setSelectedCode: (code) => set({ selectedCode: code }),

  // Chat state
  chatMessages: [],
  chatLoading: false,
  chatError: null,

  addChatMessage: (message) =>
    set((state) => ({
      chatMessages: [...state.chatMessages, message],
    })),

  clearChatMessages: () => set({ chatMessages: [] }),

  setChatLoading: (loading) => set({ chatLoading: loading }),

  setChatError: (error) => set({ chatError: error }),

  // UI state
  sidebarOpen: true,
  explorerExpanded: new Map(),

  toggleSidebar: () =>
    set((state) => ({
      sidebarOpen: !state.sidebarOpen,
    })),

  toggleExplorerNode: (path) =>
    set((state) => {
      const newExpanded = new Map(state.explorerExpanded);
      newExpanded.set(path, !(newExpanded.get(path) ?? false));
      return { explorerExpanded: newExpanded };
    }),

  // File explorer state
  expandedFolders: new Set(),
  toggleFolder: (path) =>
    set((state) => {
      const newExpanded = new Set(state.expandedFolders);
      if (newExpanded.has(path)) {
        newExpanded.delete(path);
      } else {
        newExpanded.add(path);
      }
      return { expandedFolders: newExpanded };
    }),
}));

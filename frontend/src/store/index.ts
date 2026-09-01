import { create } from 'zustand';
import type {
  Repository,
  RepositoryFile,
  FileContent,
  ChatMessage,
  IndexingStatus,
  ProposedEdit,
  AppliedEditSnapshot,
  AgentPlan,
  AgentTodo,
  TerminalLog,
} from '../types';
import { apiClient, LOCAL_SESSION_ID } from '../api/client';
import { getMonacoLanguage } from '../utils/language';
import {
  loadLlmSettings,
  saveLlmSettings,
  type LlmSettings,
} from '../utils/llmSettings';

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
  createLocalFile: (file: FileContent) => void;
  localFiles: FileContent[];
  removeLocalFile: (path: string) => void;

  // Chat state
  chatMessages: ChatMessage[];
  chatLoading: boolean;
  chatError: string | null;
  streamingContent: string;
  isStreaming: boolean;
  statusLine: string | null;
  agentPlan: AgentPlan | null;
  terminalLogs: TerminalLog[];
  agentStep: string | null;
  enablePlanning: boolean;
  setEnablePlanning: (enabled: boolean) => void;

  addChatMessage: (message: ChatMessage) => void;
  clearChatMessages: () => void;
  setChatLoading: (loading: boolean) => void;
  setChatError: (error: string | null) => void;
  startChatStream: () => void;
  handleChatWsMessage: (message: {
    type?: string;
    content?: string;
    error?: string;
    tool?: string;
    args?: Record<string, unknown>;
    request_id?: string;
    edits?: ProposedEdit[];
    applied?: boolean;
    goal?: string;
    todos?: AgentTodo[];
    id?: string;
    status?: string;
    note?: string;
    plan?: AgentPlan;
    command?: string;
    returncode?: number | null;
    stdout?: string;
    stderr?: string;
    step?: number;
    max_steps?: number;
  }) => void;

  // Edit proposals
  pendingEdits: ProposedEdit[] | null;
  activeRequestId: string | null;
  lastAppliedRequest: AppliedEditSnapshot | null;
  editApplying: boolean;
  applyPendingEdits: () => Promise<void>;
  rejectPendingEdits: () => void;
  undoLastApply: () => Promise<void>;

  // UI state
  sidebarOpen: boolean;
  explorerExpanded: Map<string, boolean>;

  toggleSidebar: () => void;
  toggleExplorerNode: (path: string) => void;

  llmSettings: LlmSettings;
  setLlmSettings: (settings: LlmSettings) => void;
  settingsOpen: boolean;
  setSettingsOpen: (open: boolean) => void;

  // File explorer state
  expandedFolders: Set<string>;
  toggleFolder: (path: string) => void;
}

function overviewMessage(
  verb: string,
  edits: ProposedEdit[],
): ChatMessage {
  const lines = edits.map((e) => {
    const name = e.file_path.split('/').pop() || e.file_path;
    const note = e.rationale?.trim() || (e.is_new_file ? 'new file' : 'updated');
    return `• ${name}: ${note}`;
  });
  return {
    role: 'assistant',
    content: `${verb}\n${lines.join('\n')}`,
    type: 'message',
    timestamp: new Date().toISOString(),
  };
}

function applyEditsToOpenTabs(
  state: {
    openFiles: Map<string, FileContent>;
    localFiles: FileContent[];
    activeFile: string | null;
  },
  edits: ProposedEdit[],
  useProposed: boolean,
): Partial<AppStore> {
  const newOpenFiles = new Map(state.openFiles);
  let localFiles = [...state.localFiles];
  let activeFile = state.activeFile;

  for (const edit of edits) {
    const path = edit.file_path.replace(/\\/g, '/');
    const content = useProposed ? edit.proposed : edit.original;
    const existing = newOpenFiles.get(path);
    const language = existing?.language || getMonacoLanguage(path);
    const file: FileContent = { path, content, language };
    newOpenFiles.set(path, file);

    const localIdx = localFiles.findIndex((f) => f.path === path);
    if (localIdx >= 0) {
      localFiles[localIdx] = file;
    } else if (!useProposed && edit.is_new_file) {
      // Undoing a new file: remove from local list if it was created
      localFiles = localFiles.filter((f) => f.path !== path);
      newOpenFiles.delete(path);
      if (activeFile === path) {
        const remaining = Array.from(newOpenFiles.keys());
        activeFile = remaining.length ? remaining[remaining.length - 1] : null;
      }
      continue;
    } else if (useProposed && !existing) {
      localFiles = [...localFiles, file];
    }
  }

  return { openFiles: newOpenFiles, localFiles, activeFile };
}

export const useAppStore = create<AppStore>((set, get) => ({
  // Repository state
  currentRepository: null,
  repositoryFiles: [],
  indexingStatus: null,
  setCurrentRepository: (repo) =>
    set({
      currentRepository: repo,
      indexingStatus: null,
      repositoryFiles: [],
    }),
  setRepositoryFiles: (files) =>
    set({
      repositoryFiles: files.map((file) => ({
        ...file,
        path: file.path.replace(/\\/g, '/'),
      })),
    }),
  setIndexingStatus: (status) => set({ indexingStatus: status }),

  // Editor state
  openFiles: new Map(),
  activeFile: null,
  selectedCode: null,
  localFiles: [],

  openFile: (file) =>
    set((state) => {
      const newOpenFiles = new Map(state.openFiles);
      newOpenFiles.set(file.path, file);
      return {
        openFiles: newOpenFiles,
        activeFile: file.path,
      };
    }),

  createLocalFile: (file) =>
    set((state) => {
      const newOpenFiles = new Map(state.openFiles);
      newOpenFiles.set(file.path, file);
      const exists = state.localFiles.some((f) => f.path === file.path);
      return {
        openFiles: newOpenFiles,
        activeFile: file.path,
        localFiles: exists
          ? state.localFiles.map((f) => (f.path === file.path ? file : f))
          : [...state.localFiles, file],
      };
    }),

  removeLocalFile: (path) =>
    set((state) => {
      const newOpenFiles = new Map(state.openFiles);
      newOpenFiles.delete(path);
      const remaining = Array.from(newOpenFiles.keys());
      return {
        localFiles: state.localFiles.filter((f) => f.path !== path),
        openFiles: newOpenFiles,
        activeFile:
          state.activeFile === path
            ? remaining.length > 0
              ? remaining[remaining.length - 1]
              : null
            : state.activeFile,
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
      return {
        openFiles: newOpenFiles,
        localFiles: state.localFiles.map((f) =>
          f.path === path ? { ...f, content } : f
        ),
      };
    }),

  setSelectedCode: (code) => set({ selectedCode: code }),

  // Chat state
  chatMessages: [],
  chatLoading: false,
  chatError: null,
  streamingContent: '',
  isStreaming: false,
  statusLine: null,
  agentPlan: null,
  terminalLogs: [],
  agentStep: null,
  enablePlanning: false,
  setEnablePlanning: (enabled) => set({ enablePlanning: enabled }),

  addChatMessage: (message) =>
    set((state) => ({
      chatMessages: [...state.chatMessages, message],
    })),

  clearChatMessages: () =>
    set({
      chatMessages: [],
      streamingContent: '',
      isStreaming: false,
      statusLine: null,
      pendingEdits: null,
      activeRequestId: null,
      agentPlan: null,
      terminalLogs: [],
      agentStep: null,
    }),

  setChatLoading: (loading) => set({ chatLoading: loading }),

  setChatError: (error) => set({ chatError: error }),

  startChatStream: () =>
    set({
      streamingContent: '',
      isStreaming: true,
      statusLine: null,
      agentPlan: null,
      terminalLogs: [],
      agentStep: null,
    }),

  handleChatWsMessage: (message) =>
    set((state) => {
      const timestamp = new Date().toISOString();

      if (message.type === 'content') {
        return {
          streamingContent: state.streamingContent + (message.content ?? ''),
          isStreaming: true,
          statusLine: null,
        };
      }

      if (message.type === 'response') {
        return { isStreaming: true, statusLine: null };
      }

      if (message.type === 'planning') {
        return {
          statusLine: message.content || 'Planning…',
          isStreaming: true,
        };
      }

      if (message.type === 'step') {
        const label =
          message.content ||
          (message.step != null
            ? `Step ${message.step}/${message.max_steps ?? '?'}`
            : 'Working…');
        return {
          agentStep: label,
          statusLine: label,
          isStreaming: true,
        };
      }

      if (message.type === 'plan') {
        const plan: AgentPlan = {
          goal: message.goal || '',
          todos: (message.todos || []).map((t) => ({
            id: t.id,
            title: t.title,
            status: t.status || 'pending',
            note: t.note,
          })),
        };
        return {
          agentPlan: plan,
          statusLine: plan.goal ? `Plan: ${plan.goal}` : 'Plan created',
          isStreaming: true,
        };
      }

      if (message.type === 'todo_update') {
        const incoming = message.plan;
        let plan = state.agentPlan;
        if (incoming?.todos) {
          plan = {
            goal: incoming.goal || plan?.goal || '',
            todos: incoming.todos,
          };
        } else if (plan && message.id) {
          plan = {
            ...plan,
            todos: plan.todos.map((t) =>
              t.id === message.id
                ? {
                    ...t,
                    status: message.status || t.status,
                    note: message.note ?? t.note,
                  }
                : t
            ),
          };
        }
        const active = plan?.todos.find((t) => t.status === 'in_progress');
        return {
          agentPlan: plan,
          statusLine: active
            ? `Working: ${active.title}`
            : message.status
              ? `Todo ${message.id}: ${message.status}`
              : state.statusLine,
          isStreaming: true,
        };
      }

      if (message.type === 'terminal') {
        const entry: TerminalLog = {
          command: message.command || '',
          returncode: message.returncode,
          stdout: message.stdout,
          stderr: message.stderr,
          status: message.status,
          error: message.error,
          timestamp,
        };
        const ok = message.returncode === 0;
        return {
          terminalLogs: [...state.terminalLogs.slice(-9), entry],
          statusLine: ok
            ? `✓ ${entry.command}`
            : `✗ ${entry.command} (exit ${message.returncode ?? '?'})`,
          isStreaming: true,
        };
      }

      if (message.type === 'tool_call') {
        return {
          statusLine: `Running ${message.tool ?? 'tool'}…`,
          isStreaming: true,
        };
      }

      if (message.type === 'tool_result') {
        return {
          statusLine: message.tool ? `Finished ${message.tool}` : null,
          isStreaming: true,
        };
      }

      if (message.type === 'edit_proposal') {
        const edits = (message.edits ?? []).map((e) => ({
          ...e,
          file_path: (e.file_path || '').replace(/\\/g, '/'),
          validation: e.validation ?? { ok: true, errors: [] },
          // Keep full content for diff UI — may already be applied on disk
          original: e.original ?? '',
          proposed: e.proposed ?? '',
          diff: e.diff ?? '',
        }));
        const applied = Boolean(message.applied);
        const tabUpdates = applied
          ? applyEditsToOpenTabs(state, edits, true)
          : {};
        return {
          ...tabUpdates,
          pendingEdits: edits,
          activeRequestId: message.request_id ?? null,
          lastAppliedRequest: applied
            ? { request_id: message.request_id ?? '', edits }
            : state.lastAppliedRequest,
          isStreaming: true,
          statusLine: edits.length
            ? applied
              ? `Applied ${edits.length} file${edits.length === 1 ? '' : 's'} — review / undo below`
              : `Proposed ${edits.length} edit${edits.length === 1 ? '' : 's'} — review below`
            : null,
        };
      }

      if (message.type === 'message') {
        return {
          streamingContent: '',
          isStreaming: false,
          statusLine: null,
          chatMessages: [
            ...state.chatMessages,
            {
              role: 'assistant',
              content: message.content ?? '',
              type: 'message',
              timestamp,
            },
          ],
        };
      }

      if (message.type === 'end') {
        if (!state.streamingContent) {
          return { streamingContent: '', isStreaming: false, statusLine: null };
        }

        return {
          streamingContent: '',
          isStreaming: false,
          statusLine: null,
          chatMessages: [
            ...state.chatMessages,
            {
              role: 'assistant',
              content: state.streamingContent,
              type: 'message',
              timestamp,
            },
          ],
        };
      }

      if (message.type === 'error') {
        if (!state.isStreaming && !state.streamingContent) {
          return state;
        }
        return {
          streamingContent: '',
          isStreaming: false,
          statusLine: null,
          chatMessages: [
            ...state.chatMessages,
            {
              role: 'assistant',
              content: `Error: ${message.error ?? 'Unknown error'}`,
              type: 'error',
              timestamp,
            },
          ],
        };
      }

      return state;
    }),

  // Edit proposals
  pendingEdits: null,
  activeRequestId: null,
  lastAppliedRequest: null,
  editApplying: false,

  applyPendingEdits: async () => {
    const state = get();
    const edits = state.pendingEdits;
    const requestId = state.activeRequestId;
    if (!edits?.length || !requestId || state.editApplying) return;

    const hasInvalid = edits.some((e) => e.validation && e.validation.ok === false);
    if (hasInvalid) return;

    set({ editApplying: true });
    const repoId = state.currentRepository?.id;
    const isLocal = !repoId || repoId === LOCAL_SESSION_ID;

    // Prefer live editor/disk originals for accurate undo (chat buffer may be truncated)
    const editsForUndo: ProposedEdit[] = edits.map((e) => {
      const path = e.file_path.replace(/\\/g, '/');
      const open = state.openFiles.get(path);
      const local = state.localFiles.find((f) => f.path === path);
      const liveOriginal = open?.content ?? local?.content;
      if (liveOriginal !== undefined) {
        return { ...e, original: liveOriginal, is_new_file: false };
      }
      return e;
    });

    try {
      if (!isLocal) {
        await apiClient.applyEdits(repoId, {
          request_id: requestId,
          edits: edits.map((e) => ({
            file_path: e.file_path,
            proposed: e.proposed,
          })),
        });
      }

      set((s) => {
        const tabUpdates = applyEditsToOpenTabs(s, editsForUndo, true);
        return {
          ...tabUpdates,
          pendingEdits: null,
          activeRequestId: null,
          lastAppliedRequest: { request_id: requestId, edits: editsForUndo },
          editApplying: false,
          chatMessages: [...s.chatMessages, overviewMessage('Applied changes:', editsForUndo)],
        };
      });
    } catch (error) {
      console.error('Failed to apply edits:', error);
      set((s) => ({
        editApplying: false,
        chatMessages: [
          ...s.chatMessages,
          {
            role: 'assistant',
            content: `Failed to apply edits: ${error instanceof Error ? error.message : 'Unknown error'}`,
            type: 'error',
            timestamp: new Date().toISOString(),
          },
        ],
      }));
    }
  },

  rejectPendingEdits: () => {
    const state = get();
    const edits = state.pendingEdits;
    if (!edits?.length) {
      set({ pendingEdits: null, activeRequestId: null });
      return;
    }
    set((s) => ({
      pendingEdits: null,
      activeRequestId: null,
      chatMessages: [...s.chatMessages, overviewMessage('Rejected proposed changes:', edits)],
    }));
  },

  undoLastApply: async () => {
    const state = get();
    const last = state.lastAppliedRequest;
    if (!last || state.editApplying) return;

    set({ editApplying: true });
    const repoId = state.currentRepository?.id;
    const isLocal = !repoId || repoId === LOCAL_SESSION_ID;

    try {
      if (!isLocal) {
        await apiClient.undoEdits(repoId, last.request_id);
      }

      set((s) => {
        const tabUpdates = applyEditsToOpenTabs(s, last.edits, false);
        return {
          ...tabUpdates,
          lastAppliedRequest: null,
          editApplying: false,
          chatMessages: [
            ...s.chatMessages,
            overviewMessage('Undid applied changes:', last.edits),
          ],
        };
      });
    } catch (error) {
      console.error('Failed to undo edits:', error);
      set((s) => ({
        editApplying: false,
        chatMessages: [
          ...s.chatMessages,
          {
            role: 'assistant',
            content: `Failed to undo: ${error instanceof Error ? error.message : 'Unknown error'}`,
            type: 'error',
            timestamp: new Date().toISOString(),
          },
        ],
      }));
    }
  },

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

  llmSettings: loadLlmSettings(),
  setLlmSettings: (settings) => {
    saveLlmSettings(settings);
    set({ llmSettings: settings });
  },
  settingsOpen: false,
  setSettingsOpen: (open) => set({ settingsOpen: open }),

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

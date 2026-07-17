export interface Repository {
  id: string;
  name: string;
  path: string;
  created_at: string;
  indexing_status?: IndexingStatus;
}

export interface IndexingStatus {
  status: "initializing" | "indexing" | "completed" | "failed";
  files_processed: number;
  total_files: number;
  errors: string[];
}

export interface RepositoryFile {
  path: string;
  language: string;
  size: number;
  ast?: any;
}

export interface FileContent {
  path: string;
  content: string;
  language: string;
}

export interface ChatMessage {
  id?: string;
  role: "user" | "assistant" | "system";
  content: string;
  type?: "message" | "tool_call" | "tool_result" | "error";
  timestamp?: string;
}

export interface CodeCompletion {
  text: string;
  imports?: string[];
}

export interface SearchResult {
  file_path: string;
  chunk_index: number;
  content: string;
  similarity: number;
}

export interface ToolCall {
  tool: string;
  args: Record<string, any>;
}

export interface ToolResult {
  status: "success" | "error";
  result?: any;
  error?: string;
}

export interface DiffLine {
  type: "add" | "remove" | "context";
  content: string;
  lineNumber?: number;
}

export interface Diff {
  file_path: string;
  original: string;
  modified: string;
  lines: DiffLine[];
}

export interface ContextWindow {
  currentFile?: string;
  selectedCode?: string;
  repositoryContext?: RepositoryContext;
}

export interface RepositoryContext {
  files: RepositoryFile[];
  total_files: number;
  languages: string[];
  dependencies?: Record<string, string[]>;
}

export interface EditorState {
  openFiles: Map<string, FileContent>;
  activeFile?: string;
  cursorPosition?: { line: number; column: number };
}
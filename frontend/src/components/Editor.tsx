import { useRef, useCallback, useEffect } from 'react';
import { useAppStore } from '../store';
import EditorTabs from './EditorTabs';
import MonacoEditor from '@monaco-editor/react';
import type { OnMount } from '@monaco-editor/react';
import type * as Monaco from 'monaco-editor';
import { apiClient, LOCAL_SESSION_ID } from '../api/client';
import { getMonacoLanguage } from '../utils/language';

const COMPLETION_LANGUAGES = [
  'python', 'javascript', 'typescript', 'json', 'html', 'css', 'java', 'go',
  'rust', 'ruby', 'php', 'c', 'cpp', 'csharp', 'shell', 'markdown', 'yaml',
  'xml', 'plaintext', 'sql',
];

const DEBOUNCE_MS = 280;
const MIN_PREFIX_CHARS = 2;
const PREFIX_LINES = 40;
const SUFFIX_LINES = 15;

let completionRequestId = 0;

interface EditorProps {
  onRequestNewFile?: () => void;
}

function cleanCompletionText(text: string, prefix: string): string {
  let cleaned = text.replace(/\r\n/g, '\n').replace(/\r/g, '');
  cleaned = cleaned.replace(/^```[\w+-]*\n?/, '').replace(/\n?```\s*$/, '');
  cleaned = cleaned.replace(/<CURSOR>/g, '');

  const lastLine = prefix.includes('\n')
    ? prefix.slice(prefix.lastIndexOf('\n') + 1)
    : prefix;
  if (lastLine && cleaned.startsWith(lastLine)) {
    cleaned = cleaned.slice(lastLine.length);
  }

  const lines = cleaned.split('\n');
  if (lines.length > 12) {
    cleaned = lines.slice(0, 12).join('\n');
  }
  return cleaned;
}

export default function Editor({ onRequestNewFile }: EditorProps) {
  const {
    openFiles,
    activeFile,
    updateFileContent,
    currentRepository,
  } = useAppStore();

  const editorRef = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<typeof Monaco | null>(null);
  const inlineProviderRef = useRef<Monaco.IDisposable | null>(null);
  const debounceTimerRef = useRef<number | null>(null);

  const currentFile = activeFile ? openFiles.get(activeFile) : null;
  const sessionId = currentRepository?.id || LOCAL_SESSION_ID;

  const handleEditorChange = (value: string | undefined) => {
    if (value !== undefined && activeFile) {
      updateFileContent(activeFile, value);
    }
  };

  const requestLlmCompletion = useCallback(async (
    model: Monaco.editor.ITextModel,
    position: Monaco.Position,
    filePath: string,
    language: string,
    signal?: AbortSignal,
  ) => {
    const prefix = model.getValueInRange({
      startLineNumber: Math.max(1, position.lineNumber - PREFIX_LINES),
      startColumn: 1,
      endLineNumber: position.lineNumber,
      endColumn: position.column,
    });

    const suffix = model.getValueInRange({
      startLineNumber: position.lineNumber,
      startColumn: position.column,
      endLineNumber: Math.min(
        model.getLineCount(),
        position.lineNumber + SUFFIX_LINES
      ),
      endColumn: model.getLineMaxColumn(
        Math.min(model.getLineCount(), position.lineNumber + SUFFIX_LINES)
      ),
    });

    if (prefix.trim().length < MIN_PREFIX_CHARS) return null;
    if (signal?.aborted) return null;

    const requestId = ++completionRequestId;
    try {
      const text = await apiClient.requestCompletion(
        sessionId,
        prefix,
        filePath,
        language,
        useAppStore.getState().llmSettings,
        suffix,
      );

      if (!text?.trim() || requestId !== completionRequestId || signal?.aborted) {
        return null;
      }

      const cleaned = cleanCompletionText(text, prefix);
      return cleaned.trim() ? cleaned : null;
    } catch (error) {
      if ((error as Error)?.name === 'AbortError') return null;
      console.error('LLM completion failed:', error);
      return null;
    }
  }, [sessionId]);

  const registerCompletionProviders = useCallback((
    monaco: typeof Monaco,
    filePath: string,
    language: string,
  ) => {
    inlineProviderRef.current?.dispose();

    if (!monaco.languages.registerInlineCompletionsProvider) {
      return;
    }

    inlineProviderRef.current = monaco.languages.registerInlineCompletionsProvider(
      language,
      {
        provideInlineCompletions: async (model, position, _context, token) => {
          if (token.isCancellationRequested) {
            return { items: [] };
          }

          // Debounce: wait briefly so rapid typing doesn't spam the API
          await new Promise<void>((resolve) => {
            if (debounceTimerRef.current != null) {
              window.clearTimeout(debounceTimerRef.current);
            }
            debounceTimerRef.current = window.setTimeout(() => {
              debounceTimerRef.current = null;
              resolve();
            }, DEBOUNCE_MS);
          });

          if (token.isCancellationRequested) {
            return { items: [] };
          }

          const completionText = await requestLlmCompletion(
            model,
            position,
            filePath,
            language,
          );
          if (!completionText || token.isCancellationRequested) {
            return { items: [] };
          }

          return {
            items: [{
              insertText: completionText,
              range: new monaco.Range(
                position.lineNumber,
                position.column,
                position.lineNumber,
                position.column,
              ),
            }],
          };
        },
        freeInlineCompletions: () => {},
      }
    );
  }, [requestLlmCompletion]);

  useEffect(() => {
    return () => {
      inlineProviderRef.current?.dispose();
      if (debounceTimerRef.current != null) {
        window.clearTimeout(debounceTimerRef.current);
      }
    };
  }, []);

  const handleEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    if (currentFile) {
      const language = currentFile.language || getMonacoLanguage(currentFile.path);
      registerCompletionProviders(monaco, currentFile.path, language);
    }
  };

  const handleBeforeMount = (monaco: typeof Monaco) => {
    COMPLETION_LANGUAGES.forEach((lang) => {
      monaco.languages.register({ id: lang });
    });
    monaco.editor.defineTheme('vs-dark-black', {
      base: 'vs-dark',
      inherit: true,
      rules: [],
      colors: {
        'editor.background': '#141414',
        'editorGutter.background': '#141414',
      },
    });
  };

  const language = currentFile
    ? (currentFile.language || getMonacoLanguage(currentFile.path))
    : 'plaintext';

  return (
    <div className="h-full flex flex-col bg-gray-900">
      <EditorTabs />

      <div className="flex-1 overflow-hidden">
        {currentFile ? (
          <MonacoEditor
            key={currentFile.path}
            path={currentFile.path}
            height="100%"
            language={language}
            value={currentFile.content}
            onChange={handleEditorChange}
            theme="vs-dark-black"
            beforeMount={handleBeforeMount}
            onMount={(editor, monaco) => {
              handleEditorMount(editor, monaco);
              registerCompletionProviders(monaco, currentFile.path, language);
            }}
            options={{
              minimap: { enabled: false },
              fontSize: 13,
              fontFamily: 'Menlo, Monaco, Courier New, monospace',
              lineNumbers: 'on',
              wordWrap: 'on',
              automaticLayout: true,
              scrollBeyondLastLine: false,
              smoothScrolling: true,
              cursorStyle: 'line',
              tabSize: 2,
              insertSpaces: true,
              // Prefer ghost-text inline suggest; keep native word suggest light
              quickSuggestions: { other: true, comments: false, strings: false },
              suggestOnTriggerCharacters: true,
              acceptSuggestionOnEnter: 'on',
              tabCompletion: 'on',
              inlineSuggest: {
                enabled: true,
                mode: 'subwordSmart',
                suppressSuggestions: false,
              },
              suggest: {
                preview: true,
                showIcons: true,
                snippetsPreventQuickSuggestions: false,
              },
            }}
          />
        ) : (
          <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-3 px-6 text-center">
            <p className="text-sm">No file open</p>
            <p className="text-xs text-gray-500 max-w-sm">
              Create a new file to start coding with AI completions, or upload a folder for repo context.
            </p>
            {onRequestNewFile && (
              <button
                onClick={onRequestNewFile}
                className="mt-2 px-4 py-2 rounded bg-blue-600 hover:bg-blue-700 text-white text-sm"
              >
                New file
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

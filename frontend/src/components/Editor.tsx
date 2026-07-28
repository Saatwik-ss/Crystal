import { useRef, useCallback } from 'react';
import { useAppStore } from '../store';
import EditorTabs from './EditorTabs';
import MonacoEditor from '@monaco-editor/react';
import type { OnMount } from '@monaco-editor/react';
import type * as Monaco from 'monaco-editor';
import { apiClient } from '../api/client';
import { getMonacoLanguage } from '../utils/language';

const COMPLETION_LANGUAGES = [
  'python', 'javascript', 'typescript', 'json', 'html', 'css', 'java', 'go', 'rust', 'ruby', 'php', 'c', 'cpp', 'csharp', 'shell', 'markdown', 'yaml', 'xml', 'plaintext',
];

let completionRequestId = 0;

export default function Editor() {
  const {
    openFiles,
    activeFile,
    updateFileContent,
    currentRepository,
  } = useAppStore();

  const editorRef = useRef<Monaco.editor.IStandaloneCodeEditor | null>(null);
  const monacoRef = useRef<typeof Monaco | null>(null);
  const completionProviderRef = useRef<Monaco.IDisposable | null>(null);
  const inlineProviderRef = useRef<Monaco.IDisposable | null>(null);

  const currentFile = activeFile ? openFiles.get(activeFile) : null;

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
  ) => {
    if (!currentRepository?.id) return null;

    const prefix = model.getValueInRange({
      startLineNumber: Math.max(1, position.lineNumber - 30),
      startColumn: 1,
      endLineNumber: position.lineNumber,
      endColumn: position.column,
    });

    if (!prefix.trim()) return null;

    const requestId = ++completionRequestId;
    try {
      const text = await apiClient.requestCompletion(
        currentRepository.id,
        prefix,
        filePath,
        language,
      );

      if (!text?.trim() || requestId !== completionRequestId) {
        return null;
      }

      return text.replace(/^```[\w]*\n?/, '').replace(/\n?```$/, '').trim();
    } catch (error) {
      console.error('LLM completion failed:', error);
      return null;
    }
  }, [currentRepository?.id]);

  const registerCompletionProviders = useCallback((
    monaco: typeof Monaco,
    filePath: string,
    language: string,
  ) => {
    completionProviderRef.current?.dispose();
    inlineProviderRef.current?.dispose();

    completionProviderRef.current = monaco.languages.registerCompletionItemProvider(language, {
      triggerCharacters: ['.', '(', '[', '{', ':', ' ', '\n', '"', "'"],
      provideCompletionItems: async (model, position) => {
        if (!currentRepository?.id) {
          return { suggestions: [] };
        }

        const completionText = await requestLlmCompletion(model, position, filePath, language);
        if (!completionText) {
          return { suggestions: [] };
        }

        const word = model.getWordUntilPosition(position);
        const range = {
          startLineNumber: position.lineNumber,
          endLineNumber: position.lineNumber,
          startColumn: word.startColumn,
          endColumn: position.column,
        };

        return {
          suggestions: [{
            label: '✨ AI suggestion',
            kind: monaco.languages.CompletionItemKind.Snippet,
            insertText: completionText,
            range,
            sortText: '0',
            detail: 'Groq AI completion',
          }],
        };
      },
    });

    if (monaco.languages.registerInlineCompletionsProvider) {
      inlineProviderRef.current = monaco.languages.registerInlineCompletionsProvider(language, {
        provideInlineCompletions: async (model, position, _context, token) => {
          if (!currentRepository?.id || token.isCancellationRequested) {
            return { items: [] };
          }

          const completionText = await requestLlmCompletion(model, position, filePath, language);
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
      });
    }
  }, [currentRepository?.id, requestLlmCompletion]);

  const handleEditorMount: OnMount = (editor, monaco) => {
    editorRef.current = editor;
    monacoRef.current = monaco;

    if (currentFile) {
      const language = getMonacoLanguage(currentFile.path);
      registerCompletionProviders(monaco, currentFile.path, language);
    }
  };

  const handleBeforeMount = (monaco: typeof Monaco) => {
    COMPLETION_LANGUAGES.forEach((lang) => {
      monaco.languages.register({ id: lang });
    });
  };

  const language = currentFile ? getMonacoLanguage(currentFile.path) : 'plaintext';

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
            theme="vs-dark"
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
              quickSuggestions: { other: true, comments: false, strings: true },
              suggestOnTriggerCharacters: true,
              acceptSuggestionOnEnter: 'on',
              inlineSuggest: { enabled: true },
              suggest: {
                preview: true,
                showIcons: true,
              },
            }}
          />
        ) : (
          <div className="h-full flex items-center justify-center text-gray-500 text-sm">
            Select a file from the Explorer to start editing
          </div>
        )}
      </div>
    </div>
  );
}

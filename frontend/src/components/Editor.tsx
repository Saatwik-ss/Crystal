import { useState } from 'react';
import { useAppStore } from '../store';
import EditorTabs from './EditorTabs';
import MonacoEditor from '@monaco-editor/react';
import type { OnMount } from '@monaco-editor/react';

export default function Editor() {
  const {
    openFiles,
    activeFile,
    updateFileContent,
  } = useAppStore();

  const currentFile = activeFile ? openFiles.get(activeFile) : null;
  const [scratchContent, setScratchContent] = useState('// Start coding here\n');

  const handleEditorChange = (value: string | undefined) => {
    if (value !== undefined && activeFile) {
      updateFileContent(activeFile, value);
    }
  };

  const handleEditorMount: OnMount = (_editor, monaco) => {
    monaco.languages.registerCompletionItemProvider('javascript', {
      provideCompletionItems: (model, position) => {
        const word = model.getWordUntilPosition(position);
        const range = {
          startLineNumber: position.lineNumber, endLineNumber: position.lineNumber,
          startColumn: word.startColumn, endColumn: word.endColumn,
        };
        return { suggestions: [
          { label: 'console.log', kind: monaco.languages.CompletionItemKind.Function, insertText: 'console.log(${1:value});', insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, range },
          { label: 'function', kind: monaco.languages.CompletionItemKind.Keyword, insertText: 'function ${1:name}(${2:args}) {\n  ${3}\n}', insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, range },
          { label: 'async function', kind: monaco.languages.CompletionItemKind.Keyword, insertText: 'async function ${1:name}(${2:args}) {\n  ${3}\n}', insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, range },
          { label: 'import', kind: monaco.languages.CompletionItemKind.Keyword, insertText: "import { ${1:name} } from '${2:module}';", insertTextRules: monaco.languages.CompletionItemInsertTextRule.InsertAsSnippet, range },
        ] };
      },
    });
  };

  return (
    <div className="h-full flex flex-col bg-gray-900">
      {/* Tabs */}
      <EditorTabs />

      <div className="flex-1 overflow-hidden">
        <MonacoEditor
          height="100%"
          language={currentFile?.language === 'python' ? 'python' : 'javascript'}
          value={currentFile?.content ?? scratchContent}
          onChange={currentFile ? handleEditorChange : (value) => setScratchContent(value ?? '')}
          theme="vs-dark"
          onMount={handleEditorMount}
          options={{
            minimap: { enabled: false }, fontSize: 13, fontFamily: 'Menlo, Monaco, Courier New',
            lineNumbers: 'on', wordWrap: 'on', automaticLayout: true,
            scrollBeyondLastLine: false, smoothScrolling: true, cursorStyle: 'line',
            tabSize: 2, insertSpaces: true, quickSuggestions: true,
            suggestOnTriggerCharacters: true, acceptSuggestionOnEnter: 'on',
          }}
        />
      </div>
    </div>
  );
}

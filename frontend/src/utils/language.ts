export function normalizePath(path: string): string {
  return path.replace(/\\/g, '/');
}

export const LANGUAGE_OPTIONS: { id: string; label: string; extension: string; starter: string }[] = [
  { id: 'javascript', label: 'JavaScript', extension: 'js', starter: '// Start coding\n' },
  { id: 'typescript', label: 'TypeScript', extension: 'ts', starter: '// Start coding\n' },
  { id: 'python', label: 'Python', extension: 'py', starter: '# Start coding\n' },
  { id: 'html', label: 'HTML', extension: 'html', starter: '<!DOCTYPE html>\n<html>\n<head>\n  <title>Document</title>\n</head>\n<body>\n  \n</body>\n</html>\n' },
  { id: 'css', label: 'CSS', extension: 'css', starter: '/* Start styling */\n' },
  { id: 'json', label: 'JSON', extension: 'json', starter: '{\n  \n}\n' },
  { id: 'markdown', label: 'Markdown', extension: 'md', starter: '# Title\n\n' },
  { id: 'java', label: 'Java', extension: 'java', starter: 'public class Main {\n  public static void main(String[] args) {\n    \n  }\n}\n' },
  { id: 'go', label: 'Go', extension: 'go', starter: 'package main\n\nfunc main() {\n  \n}\n' },
  { id: 'rust', label: 'Rust', extension: 'rs', starter: 'fn main() {\n  \n}\n' },
  { id: 'cpp', label: 'C++', extension: 'cpp', starter: '#include <iostream>\n\nint main() {\n  return 0;\n}\n' },
  { id: 'c', label: 'C', extension: 'c', starter: '#include <stdio.h>\n\nint main() {\n  return 0;\n}\n' },
  { id: 'csharp', label: 'C#', extension: 'cs', starter: 'using System;\n\nclass Program {\n  static void Main() {\n    \n  }\n}\n' },
  { id: 'ruby', label: 'Ruby', extension: 'rb', starter: '# Start coding\n' },
  { id: 'php', label: 'PHP', extension: 'php', starter: '<?php\n\n' },
  { id: 'shell', label: 'Shell', extension: 'sh', starter: '#!/usr/bin/env bash\n\n' },
  { id: 'sql', label: 'SQL', extension: 'sql', starter: '-- Start querying\n' },
  { id: 'yaml', label: 'YAML', extension: 'yaml', starter: '# config\n' },
  { id: 'plaintext', label: 'Plain text', extension: 'txt', starter: '' },
];

export function getMonacoLanguage(filePath: string): string {
  const ext = normalizePath(filePath).split('.').pop()?.toLowerCase();
  const map: Record<string, string> = {
    py: 'python',
    js: 'javascript',
    jsx: 'javascript',
    ts: 'typescript',
    tsx: 'typescript',
    json: 'json',
    html: 'html',
    htm: 'html',
    css: 'css',
    scss: 'scss',
    md: 'markdown',
    java: 'java',
    go: 'go',
    rs: 'rust',
    rb: 'ruby',
    php: 'php',
    cpp: 'cpp',
    c: 'c',
    h: 'c',
    cs: 'csharp',
    sql: 'sql',
    yaml: 'yaml',
    yml: 'yaml',
    xml: 'xml',
    sh: 'shell',
    txt: 'plaintext',
  };
  return map[ext || ''] || 'plaintext';
}

export function extensionForLanguage(languageId: string): string {
  return LANGUAGE_OPTIONS.find((o) => o.id === languageId)?.extension || 'txt';
}

export function starterForLanguage(languageId: string): string {
  return LANGUAGE_OPTIONS.find((o) => o.id === languageId)?.starter ?? '';
}

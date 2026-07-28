export function normalizePath(path: string): string {
  return path.replace(/\\/g, '/');
}

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
  };
  return map[ext || ''] || 'plaintext';
}

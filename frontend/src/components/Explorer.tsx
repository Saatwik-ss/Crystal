import { useState, useEffect, useMemo, useRef } from 'react';
import { useAppStore } from '../store';
import { apiClient } from '../api/client';
import { ChevronRight, ChevronDown, File, Folder, Download } from 'lucide-react';
import { getMonacoLanguage, normalizePath } from '../utils/language';

interface FileTree {
  [key: string]: FileTree | boolean;
}

function expandParentFolders(path: string, expanded: Set<string>): Set<string> {
  const parts = normalizePath(path).split('/');
  const next = new Set(expanded);
  for (let i = 1; i < parts.length; i += 1) {
    next.add(parts.slice(0, i).join('/'));
  }
  return next;
}

export default function Explorer() {
  const {
    currentRepository,
    repositoryFiles,
    expandedFolders,
    toggleFolder,
    openFile,
    setActiveFile,
    openFiles,
    activeFile,
    localFiles,
  } = useAppStore();

  const [loadingPath, setLoadingPath] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [searchTerm, setSearchTerm] = useState('');
  const [fileTree, setFileTree] = useState<FileTree>({});
  const autoExpandedRepo = useRef<string | null>(null);

  useEffect(() => {
    autoExpandedRepo.current = null;
  }, [currentRepository?.id]);

  useEffect(() => {
    if (!repositoryFiles.length) {
      setFileTree({});
      return;
    }

    const tree: FileTree = {};

    repositoryFiles.forEach((file) => {
      const parts = normalizePath(file.path).split('/').filter(Boolean);
      let current = tree;

      for (let i = 0; i < parts.length - 1; i++) {
        const part = parts[i];
        if (!current[part] || current[part] === true) {
          current[part] = {};
        }
        current = current[part] as FileTree;
      }

      current[parts[parts.length - 1]] = true;
    });

    setFileTree(tree);

    const repoId = currentRepository?.id;
    if (!repoId || autoExpandedRepo.current === repoId) {
      return;
    }
    const firstNested = repositoryFiles
      .map((file) => normalizePath(file.path).split('/').filter(Boolean))
      .find((parts) => parts.length > 1);
    if (firstNested) {
      const top = firstNested[0];
      if (!expandedFolders.has(top)) {
        toggleFolder(top);
      }
    }
    autoExpandedRepo.current = repoId;
  }, [repositoryFiles, currentRepository?.id, toggleFolder]);

  
  const handleDownload = async (e: React.MouseEvent, filePath: string) => {
    e.stopPropagation();
    
    // Check openFiles or localFiles first
    let content = openFiles.get(filePath)?.content || localFiles.find((f) => f.path === filePath)?.content;
    
    // If not local, try fetching from repo
    if (content === undefined && currentRepository?.id) {
      try {
        content = await apiClient.readFile(currentRepository.id, filePath);
      } catch (err) {
        console.error("Download failed:", err);
        return;
      }
    }
    
    if (content !== undefined) {
      const blob = new Blob([content], { type: 'text/plain' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = filePath.split('/').pop() || 'download';
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }
  };

  const handleLocalFileClick = (path: string) => {
    const file = localFiles.find((f) => f.path === path) || openFiles.get(path);
    if (file) {
      openFile(file);
      setError(null);
    }
  };

  const handleRepoFileClick = async (filePath: string) => {
    const normalizedPath = normalizePath(filePath);

    if (!currentRepository?.id) {
      setError('No repository loaded');
      return;
    }

    const cached = openFiles.get(normalizedPath);
    if (cached) {
      setActiveFile(normalizedPath);
      setError(null);
      return;
    }

    try {
      setLoadingPath(normalizedPath);
      setError(null);
      const content = await apiClient.readFile(currentRepository.id, normalizedPath);

      openFile({
        path: normalizedPath,
        content,
        language: getMonacoLanguage(normalizedPath),
      });

      const expanded = expandParentFolders(normalizedPath, expandedFolders);
      expanded.forEach((folder) => {
        if (!expandedFolders.has(folder)) {
          toggleFolder(folder);
        }
      });
    } catch (err) {
      console.error('Failed to open file:', err);
      setError(`Could not open ${normalizedPath}`);
    } finally {
      setLoadingPath(null);
    }
  };

  const filteredTree = useMemo(() => {
    if (!searchTerm) return fileTree;

    const isMatching = (path: string): boolean =>
      path.toLowerCase().includes(searchTerm.toLowerCase());

    const filterTree = (tree: FileTree, prefix = ''): FileTree => {
      const result: FileTree = {};

      Object.entries(tree).forEach(([key, value]) => {
        const fullPath = prefix ? `${prefix}/${key}` : key;

        if (typeof value === 'boolean') {
          if (isMatching(fullPath)) {
            result[key] = true;
          }
        } else {
          const filteredSubtree = filterTree(value, fullPath);
          if (Object.keys(filteredSubtree).length > 0 || isMatching(fullPath)) {
            result[key] = filteredSubtree;
          }
        }
      });

      return result;
    };

    return filterTree(fileTree);
  }, [fileTree, searchTerm]);

  const filteredLocalFiles = useMemo(() => {
    if (!searchTerm) return localFiles;
    const q = searchTerm.toLowerCase();
    return localFiles.filter((f) => f.path.toLowerCase().includes(q));
  }, [localFiles, searchTerm]);

  const renderTree = (tree: FileTree, prefix = '') => {
    return Object.entries(tree)
      .sort(([aKey, aVal], [bKey, bVal]) => {
        const aIsFile = aVal === true;
        const bIsFile = bVal === true;
        if (aIsFile !== bIsFile) return aIsFile ? 1 : -1;
        return aKey.localeCompare(bKey);
      })
      .map(([key, value]) => {
        const fullPath = prefix ? `${prefix}/${key}` : key;
        const isFile = value === true;
        const isExpanded = expandedFolders.has(fullPath);
        const isActive = activeFile === fullPath;
        const isLoading = loadingPath === fullPath;

        return (
          <div key={fullPath}>
            <div
              className={`flex items-center gap-1 px-2 py-1 cursor-pointer text-sm group ${
                isActive ? 'bg-gray-700 text-white' : 'text-gray-300 hover:bg-gray-700'
              }`}
              onClick={() => {
                if (isFile) {
                  handleRepoFileClick(fullPath);
                } else {
                  toggleFolder(fullPath);
                }
              }}
            >
              {!isFile && (
                <span className="w-4 h-4 flex items-center justify-center">
                  {isExpanded ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </span>
              )}

              {isFile ? (
                <File size={14} className={isLoading ? 'text-blue-300 animate-pulse' : 'text-gray-400'} />
              ) : (
                <Folder size={14} className="text-blue-400" />
              )}

              
              <span className="flex-1 truncate">{key}</span>
              {isFile && (
                <button
                  onClick={(e) => handleDownload(e, fullPath)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-white"
                  title="Download file"
                >
                  <Download size={14} />
                </button>
              )}
            </div>


            {!isFile && isExpanded && (
              <div className="pl-4">
                {renderTree(value as FileTree, fullPath)}
              </div>
            )}
          </div>
        );
      });
  };

  return (
    <div className="flex-1 flex flex-col overflow-hidden">
      <div className="p-3 border-b border-gray-700">
        <input
          type="text"
          placeholder="Search files..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full bg-gray-700 text-white placeholder-gray-500 text-sm px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
        />
      </div>

      {error && (
        <div className="px-3 py-2 text-xs text-red-300 bg-red-900/30 border-b border-red-800">
          {error}
        </div>
      )}

      <div className="flex-1 overflow-y-auto">
        {filteredLocalFiles.length > 0 && (
          <div className="py-2 border-b border-gray-700">
            <p className="px-3 py-1 text-[10px] uppercase tracking-wide text-gray-500">
              Local files
            </p>
            {filteredLocalFiles.map((file) => (
              <div
                key={file.path}
                className={`flex items-center gap-1 px-2 py-1 cursor-pointer text-sm ${
                  activeFile === file.path
                    ? 'bg-gray-700 text-white'
                    : 'text-gray-300 hover:bg-gray-700'
                }`}
                onClick={() => handleLocalFileClick(file.path)}
              >
                <File size={14} className="text-emerald-400" />
                
                <span className="flex-1 truncate">{file.path}</span>
                <button
                  onClick={(e) => handleDownload(e, file.path)}
                  className="opacity-0 group-hover:opacity-100 p-1 text-gray-400 hover:text-white"
                  title="Download file"
                >
                  <Download size={14} />
                </button>
              </div>

            ))}
          </div>
        )}

        {repositoryFiles.length === 0 && localFiles.length === 0 ? (
          <div className="flex items-center justify-center h-full p-4 text-center">
            <p className="text-gray-400 text-sm">
              Create a new file or upload a folder to get started
            </p>
          </div>
        ) : repositoryFiles.length > 0 ? (
          <div className="py-2">
            <p className="px-3 py-1 text-[10px] uppercase tracking-wide text-gray-500">
              Repository
            </p>
            {renderTree(filteredTree)}
          </div>
        ) : null}
      </div>
    </div>
  );
}

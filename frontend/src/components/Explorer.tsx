import { useState, useEffect, useMemo } from 'react';
import { useAppStore } from '../store';
import { apiClient } from '../api/client';
import { ChevronRight, ChevronDown, File, Folder } from 'lucide-react';

interface FileTree {
  [key: string]: FileTree | boolean;
}

export default function Explorer() {
  const {
    currentRepository,
    repositoryFiles,
    expandedFolders,
    toggleFolder,
    openFile,
  } = useAppStore();

  const [loading, setLoading] = useState(false);
  const [searchTerm, setSearchTerm] = useState('');
  const [fileTree, setFileTree] = useState<FileTree>({});

  // Build file tree from flat file list
  useEffect(() => {
    if (!repositoryFiles) return;

    const tree: FileTree = {};

    repositoryFiles.forEach((file) => {
      const parts = file.path.split('/');
      let current = tree;

      for (let i = 0; i < parts.length - 1; i++) {
        const part = parts[i];
        if (!current[part]) {
          current[part] = {};
        }
        current = current[part] as FileTree;
      }

      // Mark file as true (leaf node)
      current[parts[parts.length - 1]] = true;
    });

    setFileTree(tree);
  }, [repositoryFiles]);

  const handleFileClick = async (filePath: string) => {
    try {
      setLoading(true);
      const content = await apiClient.readFile(currentRepository!.id, filePath);

      openFile({
        path: filePath,
        content,
        language: filePath.split('.').pop() || 'unknown',
      });
    } catch (error) {
      console.error('Failed to open file:', error);
    } finally {
      setLoading(false);
    }
  };

  const filteredTree = useMemo(() => {
    if (!searchTerm) return fileTree;

    const isMatching = (path: string): boolean => {
      return path.toLowerCase().includes(searchTerm.toLowerCase());
    };

    const filterTree = (tree: FileTree, prefix = ''): FileTree => {
      const result: FileTree = {};

      Object.entries(tree).forEach(([key, value]) => {
        const fullPath = prefix ? `${prefix}/${key}` : key;

        if (typeof value === 'boolean') {
          // It's a file
          if (isMatching(fullPath)) {
            result[key] = true;
          }
        } else {
          // It's a folder
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

  const renderTree = (tree: FileTree, prefix = '') => {
    return Object.entries(tree).map(([key, value]) => {
      const fullPath = prefix ? `${prefix}/${key}` : key;
      const isFile = typeof value === 'boolean';
      const isExpanded = expandedFolders.has(fullPath);

      return (
        <div key={fullPath}>
          <div
            className="flex items-center gap-1 px-2 py-1 hover:bg-gray-700 cursor-pointer text-sm text-gray-300 group"
            onClick={() => {
              if (isFile) {
                handleFileClick(fullPath);
              } else {
                toggleFolder(fullPath);
              }
            }}
          >
            {!isFile && (
              <span className="w-4 h-4 flex items-center justify-center">
                {isExpanded ? (
                  <ChevronDown size={14} />
                ) : (
                  <ChevronRight size={14} />
                )}
              </span>
            )}

            {isFile ? (
              <File size={14} className="text-gray-400" />
            ) : (
              <Folder size={14} className="text-blue-400" />
            )}

            <span className="flex-1 truncate">{key}</span>
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
      {/* Search */}
      <div className="p-3 border-b border-gray-700">
        <input
          type="text"
          placeholder="Search files..."
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          className="w-full bg-gray-700 text-white placeholder-gray-500 text-sm px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none"
        />
      </div>

      {/* File tree */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-full">
            <p className="text-gray-400 text-sm">Loading...</p>
          </div>
        ) : (
          <div className="py-2">
            {renderTree(filteredTree)}
          </div>
        )}
      </div>
    </div>
  );
}

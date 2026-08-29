import { useAppStore } from '../store';
import { X } from 'lucide-react';
import clsx from 'clsx';

export default function EditorTabs() {
  const { openFiles, activeFile, setActiveFile, closeFile } = useAppStore();

  if (openFiles.size === 0) {
    return (
      <div className="bg-gray-800 border-b border-gray-700 px-4 py-3 text-center text-gray-500 text-sm">
        No files open
      </div>
    );
  }

  const files = Array.from(openFiles.values());

  return (
    <div className="bg-gray-800 border-b border-gray-700 flex items-center overflow-x-auto">
      {files.map((file) => (
        <div
          key={file.path}
          className={clsx(
            'flex items-center gap-2 px-4 py-3 border-r border-gray-700 cursor-pointer transition-colors',
            activeFile === file.path
              ? 'bg-gray-900 text-white border-b-2 border-blue-500'
              : 'bg-gray-800 text-gray-400 hover:bg-gray-750'
          )}
          onClick={() => setActiveFile(file.path)}
        >
          <span className="text-sm font-medium truncate">
            {file.path.split('/').pop()}
          </span>
          <button
            onClick={(e) => {
              e.stopPropagation();
              closeFile(file.path);
            }}
            className="text-gray-400 hover:text-gray-200 transition-colors"
            title="Close tab"
          >
            <X size={14} />
          </button>
        </div>
      ))}
    </div>
  );
}

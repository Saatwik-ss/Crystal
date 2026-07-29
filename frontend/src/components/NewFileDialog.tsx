import { useState } from 'react';
import { useAppStore } from '../store';
import {
  LANGUAGE_OPTIONS,
  extensionForLanguage,
  starterForLanguage,
} from '../utils/language';

interface NewFileDialogProps {
  onClose: () => void;
}

export default function NewFileDialog({ onClose }: NewFileDialogProps) {
  const createLocalFile = useAppStore((s) => s.createLocalFile);
  const localFiles = useAppStore((s) => s.localFiles);
  const openFiles = useAppStore((s) => s.openFiles);

  const [name, setName] = useState('untitled');
  const [language, setLanguage] = useState('javascript');
  const [error, setError] = useState<string | null>(null);

  const handleCreate = () => {
    const base = name.trim().replace(/[\\/]/g, '') || 'untitled';
    const ext = extensionForLanguage(language);
    const hasExt = /\.[a-z0-9]+$/i.test(base);
    const path = hasExt ? base : `${base}.${ext}`;

    if (localFiles.some((f) => f.path === path) || openFiles.has(path)) {
      setError(`A file named "${path}" is already open`);
      return;
    }

    createLocalFile({
      path,
      content: starterForLanguage(language),
      language,
    });
    onClose();
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
      <div className="bg-gray-800 rounded-lg p-6 w-full max-w-md mx-4 border border-gray-700 shadow-xl">
        <h2 className="text-lg font-semibold text-white mb-4">New file</h2>

        <label className="block text-xs text-gray-400 mb-1">File name</label>
        <input
          autoFocus
          value={name}
          onChange={(e) => {
            setName(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleCreate();
            if (e.key === 'Escape') onClose();
          }}
          className="w-full bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none mb-4"
          placeholder="untitled"
        />

        <label className="block text-xs text-gray-400 mb-1">Language</label>
        <select
          value={language}
          onChange={(e) => setLanguage(e.target.value)}
          className="w-full bg-gray-700 text-white px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none mb-4"
        >
          {LANGUAGE_OPTIONS.map((opt) => (
            <option key={opt.id} value={opt.id}>
              {opt.label} (.{opt.extension})
            </option>
          ))}
        </select>

        {error && <p className="text-sm text-red-300 mb-3">{error}</p>}

        <div className="flex justify-end gap-2">
          <button
            onClick={onClose}
            className="px-4 py-2 rounded bg-gray-700 hover:bg-gray-600 text-white text-sm"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            className="px-4 py-2 rounded bg-blue-600 hover:bg-blue-700 text-white text-sm"
          >
            Create
          </button>
        </div>
      </div>
    </div>
  );
}

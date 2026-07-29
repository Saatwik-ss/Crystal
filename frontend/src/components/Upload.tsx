import React, { useState, useRef } from 'react';
import { useAppStore } from '../store';
import { apiClient } from '../api/client';
import { Upload as UploadIcon, AlertCircle } from 'lucide-react';

interface UploadProps {
  onUploadComplete: () => void;
  compact?: boolean;
}

function withRelativePath(file: File, relativePath: string): File {
  const named = new File([file], file.name, {
    type: file.type,
    lastModified: file.lastModified,
  });
  Object.defineProperty(named, 'webkitRelativePath', {
    value: relativePath.replace(/\\/g, '/'),
    writable: false,
  });
  return named;
}

export default function Upload({ onUploadComplete, compact = false }: UploadProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const folderInputRef = useRef<HTMLInputElement>(null);

  const setCurrentRepository = useAppStore((s) => s.setCurrentRepository);

  const handleDragEnter = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  };

  const handleDragOver = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const traverseDirectory = async (
    directory: FileSystemDirectoryEntry,
    pathPrefix = ''
  ): Promise<File[]> => {
    const reader = directory.createReader();
    const collected: File[] = [];

    const readAllEntries = (): Promise<FileSystemEntry[]> =>
      new Promise((resolve, reject) => {
        const all: FileSystemEntry[] = [];
        const readBatch = () => {
          reader.readEntries((batch) => {
            if (!batch.length) {
              resolve(all);
              return;
            }
            all.push(...batch);
            readBatch();
          }, reject);
        };
        readBatch();
      });

    const entries = await readAllEntries();
    for (const entry of entries) {
      const nextPrefix = pathPrefix ? `${pathPrefix}/${entry.name}` : entry.name;
      if (entry.isFile) {
        const file = await new Promise<File | null>((resolve) => {
          (entry as FileSystemFileEntry).file(resolve, () => resolve(null));
        });
        if (file) {
          collected.push(withRelativePath(file, nextPrefix));
        }
      } else if (entry.isDirectory) {
        collected.push(
          ...(await traverseDirectory(entry as FileSystemDirectoryEntry, nextPrefix))
        );
      }
    }
    return collected;
  };

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const items = Array.from(e.dataTransfer.items || []);
    const files: File[] = [];

    try {
      for (const item of items) {
        if (item.kind !== 'file') continue;
        const entry = item.webkitGetAsEntry?.();
        if (entry?.isDirectory) {
          files.push(
            ...(await traverseDirectory(entry as FileSystemDirectoryEntry, entry.name))
          );
        } else {
          const file = item.getAsFile();
          if (file) {
            const relative =
              (file as File & { webkitRelativePath?: string }).webkitRelativePath ||
              file.name;
            files.push(withRelativePath(file, relative));
          }
        }
      }

      // Fallback for browsers that don't expose entries
      if (files.length === 0 && e.dataTransfer.files?.length) {
        files.push(...Array.from(e.dataTransfer.files));
      }

      await uploadFiles(files);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to process dropped items';
      setError(message);
    }
  };

  const uploadFiles = async (files: File[]) => {
    if (files.length === 0) {
      setError('No files to upload. Try "Add files" or "Add folder".');
      return;
    }

    try {
      setIsUploading(true);
      setError(null);

      const repository = await apiClient.uploadRepository(files);
      if (!repository?.id) {
        throw new Error('Upload response missing repository id');
      }

      setCurrentRepository(repository);
      onUploadComplete();
    } catch (err) {
      const message =
        err instanceof Error && 'response' in err
          ? String(
              (err as { response?: { data?: { detail?: string } } }).response?.data
                ?.detail || err.message
            )
          : err instanceof Error
            ? err.message
            : 'Upload failed';
      setError(message);
    } finally {
      setIsUploading(false);
    }
  };

  const handleFileInput = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    e.target.value = '';
    await uploadFiles(files);
  };

  return (
    <div
      className={
        compact
          ? ''
          : 'bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 rounded-lg flex items-center justify-center p-4'
      }
    >
      <div className={compact ? 'w-full' : 'max-w-2xl w-full'}>
        {!compact && (
          <div className="mb-8 text-center">
            <h1 className="text-4xl font-bold text-white mb-2">AI Coding Assistant</h1>
            <p className="text-gray-400 text-lg">
              Optional: upload a repository for codebase-aware chat and search
            </p>
          </div>
        )}

        <div
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg text-center transition-colors ${
            compact ? 'p-6' : 'p-12'
          } ${
            isDragging
              ? 'border-blue-500 bg-blue-500 bg-opacity-10'
              : 'border-gray-600 bg-gray-800 hover:border-gray-500'
          } ${isUploading ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          <UploadIcon size={compact ? 32 : 48} className="mx-auto mb-4 text-gray-400" />
          <h2 className={`${compact ? 'text-lg' : 'text-2xl'} font-semibold text-white mb-2`}>
            Drag and drop files or a folder
          </h2>
          <p className="text-gray-400 mb-6 text-sm">
            Or choose files / a folder below
          </p>

          <input
            ref={fileInputRef}
            type="file"
            multiple
            onChange={handleFileInput}
            disabled={isUploading}
            className="hidden"
          />

          <input
            ref={(el) => {
              (folderInputRef as React.MutableRefObject<HTMLInputElement | null>).current = el;
              if (el) {
                el.setAttribute('webkitdirectory', '');
                el.setAttribute('directory', '');
              }
            }}
            type="file"
            multiple
            onChange={handleFileInput}
            disabled={isUploading}
            className="hidden"
          />

          <div className="flex flex-wrap justify-center gap-3">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-semibold py-2.5 px-5 rounded-lg transition-colors"
            >
              {isUploading ? 'Uploading...' : 'Add files'}
            </button>
            <button
              type="button"
              onClick={() => folderInputRef.current?.click()}
              disabled={isUploading}
              className="bg-gray-700 hover:bg-gray-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-semibold py-2.5 px-5 rounded-lg transition-colors"
            >
              Add folder
            </button>
          </div>
        </div>

        {isUploading && (
          <div className="mt-4 p-3 bg-blue-900 bg-opacity-30 border border-blue-600 rounded-lg">
            <p className="text-blue-300 text-sm">
              Uploading... Indexing continues in the background.
            </p>
          </div>
        )}

        {error && (
          <div className="mt-4 p-3 bg-red-900 bg-opacity-30 border border-red-600 rounded-lg flex items-start gap-3">
            <AlertCircle size={20} className="text-red-400 mt-0.5 flex-shrink-0" />
            <div>
              <p className="text-red-300 font-semibold text-sm">Error</p>
              <p className="text-red-200 text-sm">{error}</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

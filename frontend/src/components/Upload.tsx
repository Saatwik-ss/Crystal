import React, { useState, useRef } from 'react';
import { useAppStore } from '../store';
import { apiClient } from '../api/client';
import { Upload as UploadIcon, AlertCircle } from 'lucide-react';

interface UploadProps {
  onUploadComplete: () => void;
}

export default function Upload({ onUploadComplete }: UploadProps) {
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

  const handleDrop = async (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);

    const items = e.dataTransfer.items;
    const files: File[] = [];

    const processEntries = async (entries: DataTransferItem[]) => {
      for (const entry of entries) {
        const item = entry.webkitGetAsEntry();
        if (item?.isFile) {
          const file = entry.getAsFile();
          if (file) files.push(file);
        } else if (item?.isDirectory) {
          await traverseDirectory(item as FileSystemDirectoryEntry);
        }
      }
    };

    const traverseDirectory = async (directory: FileSystemDirectoryEntry) => {
      const reader = directory.createReader();
      const entries = await new Promise<FileSystemEntry[]>((resolve) => {
        reader.readEntries(resolve);
      });

      for (const entry of entries) {
        if (entry.isFile) {
          const file = await new Promise<File | null>((resolve) => {
            (entry as FileSystemFileEntry).file(resolve);
          });
          if (file) files.push(file);
        } else if (entry.isDirectory) {
          await traverseDirectory(entry as FileSystemDirectoryEntry);
        }
      }
    };

    try {
      await processEntries(Array.from(items));
      await uploadFiles(files);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to process dropped items';
      setError(message);
    }
  };

  const uploadFiles = async (files: File[]) => {
    if (files.length === 0) {
      setError('No files to upload');
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
      const message = err instanceof Error && 'response' in err
        ? String((err as { response?: { data?: { detail?: string } } }).response?.data?.detail || err.message)
        : err instanceof Error ? err.message : 'Upload failed';
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
    <div className="bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900 rounded-lg flex items-center justify-center p-4">
      <div className="max-w-2xl w-full">
        <div className="mb-8 text-center">
          <h1 className="text-4xl font-bold text-white mb-2">
            AI Coding Assistant
          </h1>
          <p className="text-gray-400 text-lg">
            Upload your repository to get started with intelligent code analysis
          </p>
        </div>

        <div
          onDragEnter={handleDragEnter}
          onDragLeave={handleDragLeave}
          onDragOver={handleDragOver}
          onDrop={handleDrop}
          className={`border-2 border-dashed rounded-lg p-12 text-center transition-colors cursor-pointer ${
            isDragging
              ? 'border-blue-500 bg-blue-500 bg-opacity-10'
              : 'border-gray-600 bg-gray-800 hover:border-gray-500'
          } ${isUploading ? 'opacity-50 cursor-not-allowed' : ''}`}
        >
          <UploadIcon
            size={48}
            className="mx-auto mb-4 text-gray-400"
          />
          <h2 className="text-2xl font-semibold text-white mb-2">
            Drag and drop your repository
          </h2>
          <p className="text-gray-400 mb-6">
            Drop files or a folder, or choose what to add below
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
            ref={(input) => {
              (folderInputRef as React.MutableRefObject<HTMLInputElement | null>).current = input;
              input?.setAttribute('webkitdirectory', '');
              input?.setAttribute('directory', '');
            }}
            type="file"
            multiple
            onChange={handleFileInput}
            disabled={isUploading}
            className="hidden"
          />

          <div className="flex flex-wrap justify-center gap-3">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading}
              className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-semibold py-3 px-5 rounded-lg transition-colors"
            >
              {isUploading ? 'Uploading...' : 'Add files'}
            </button>
            <button
              onClick={() => folderInputRef.current?.click()}
              disabled={isUploading}
              className="bg-gray-700 hover:bg-gray-600 disabled:bg-gray-600 disabled:cursor-not-allowed text-white font-semibold py-3 px-5 rounded-lg transition-colors"
            >
              Add folder
            </button>
          </div>
        </div>

        {isUploading && (
          <div className="mt-8 p-4 bg-blue-900 bg-opacity-30 border border-blue-600 rounded-lg">
            <p className="text-blue-300 text-sm">
              Uploading repository... Indexing will continue in the background.
            </p>
          </div>
        )}

        {error && (
          <div className="mt-8 p-4 bg-red-900 bg-opacity-30 border border-red-600 rounded-lg flex items-start gap-3">
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

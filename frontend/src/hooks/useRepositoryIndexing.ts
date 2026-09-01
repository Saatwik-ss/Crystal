import { useEffect } from 'react';
import { useAppStore } from '../store';
import { apiClient } from '../api/client';

export function useRepositoryIndexing() {
  const currentRepository = useAppStore((s) => s.currentRepository);
  const setIndexingStatus = useAppStore((s) => s.setIndexingStatus);
  const setRepositoryFiles = useAppStore((s) => s.setRepositoryFiles);

  useEffect(() => {
    if (!currentRepository) return;

    const repoId = currentRepository.id;
    let cancelled = false;

    const loadFiles = async () => {
      try {
        const files = await apiClient.listRepositoryFiles(repoId);
        if (cancelled) return;
        if (Array.isArray(files)) {
          setRepositoryFiles(files);
        }
      } catch (error) {
        console.error('Error listing repository files:', error);
      }
    };

    loadFiles();

    const poll = async () => {
      try {
        const status = await apiClient.getRepositoryStatus(repoId);
        if (cancelled) return true;

        setIndexingStatus(status);

        const finished =
          status.status === 'completed' ||
          status.status === 'failed' ||
          (status.total_files > 0 && status.files_processed >= status.total_files);
        if (finished) {
          await loadFiles();
          return true;
        }
      } catch (error) {
        console.error('Error polling indexing status:', error);
      }

      return false;
    };

    poll();
    const interval = setInterval(async () => {
      const done = await poll();
      if (done) {
        clearInterval(interval);
      }
    }, 1000);

    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [currentRepository, setIndexingStatus, setRepositoryFiles]);
}

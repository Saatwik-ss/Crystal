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

    const poll = async () => {
      try {
        const status = await apiClient.getRepositoryStatus(repoId);
        if (cancelled) return;

        setIndexingStatus(status);

        if (status.status === 'completed') {
          const files = await apiClient.listRepositoryFiles(repoId);
          if (!cancelled) {
            setRepositoryFiles(files);
          }
          return true;
        }

        if (status.status === 'failed') {
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

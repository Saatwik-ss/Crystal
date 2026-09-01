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

    // Immediately fetch repository files so the sidebar populates right away
    apiClient
      .listRepositoryFiles(repoId)
      .then((files) => {
        if (!cancelled && files && files.length > 0) {
          setRepositoryFiles(files);
        }
      })
      .catch(() => undefined);

    let pollCount = 0;
    const MAX_POLLS = 120; // 2 minutes max polling

    const poll = async () => {
      try {
        pollCount++;
        const status = await apiClient.getRepositoryStatus(repoId);
        if (cancelled) return false;

        setIndexingStatus(status);

        if (
          status.status === 'completed' ||
          (status.total_files > 0 && status.files_processed >= status.total_files)
        ) {
          const files = await apiClient.listRepositoryFiles(repoId);
          if (!cancelled && files && files.length > 0) {
            setRepositoryFiles(files);
          }
          if (status.status === 'completed') {
            return true;
          }
        }

        if (status.status === 'failed' || pollCount >= MAX_POLLS) {
          const files = await apiClient.listRepositoryFiles(repoId);
          if (!cancelled && files && files.length > 0) {
            setRepositoryFiles(files);
          }
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

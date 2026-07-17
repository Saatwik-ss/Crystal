import { useEffect } from 'react';
import { useAppStore } from '../store';
import { apiClient } from '../api/client';
import { CheckCircle, AlertCircle, Loader } from 'lucide-react';

export default function IndexingStatus() {
  const { currentRepository, indexingStatus, setIndexingStatus } = useAppStore();

  useEffect(() => {
    if (!currentRepository) return;

    // Poll for indexing status
    const interval = setInterval(async () => {
      try {
        const status = await apiClient.getRepositoryStatus(currentRepository.id);
        setIndexingStatus(status);

        // Stop polling when completed or failed
        if (status.status === 'completed' || status.status === 'failed') {
          clearInterval(interval);
        }
      } catch (error) {
        console.error('Error fetching status:', error);
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [currentRepository, setIndexingStatus]);

  if (!indexingStatus) return null;

  const { status, files_processed, total_files } = indexingStatus;
  const percentage =
    total_files > 0 ? Math.round((files_processed / total_files) * 100) : 0;

  return (
    <div className="flex items-center gap-2">
      {status === 'indexing' && (
        <>
          <Loader size={14} className="animate-spin text-blue-400" />
          <span className="text-xs text-gray-400">
            Indexing {files_processed}/{total_files}
          </span>
          <div className="w-32 h-2 bg-gray-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 transition-all duration-300"
              style={{ width: `${percentage}%` }}
            />
          </div>
        </>
      )}

      {status === 'completed' && (
        <>
          <CheckCircle size={14} className="text-green-400" />
          <span className="text-xs text-green-400">Indexed</span>
        </>
      )}

      {status === 'failed' && (
        <>
          <AlertCircle size={14} className="text-red-400" />
          <span className="text-xs text-red-400">Indexing failed</span>
        </>
      )}
    </div>
  );
}

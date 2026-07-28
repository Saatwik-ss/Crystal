import { useAppStore } from '../store';
import { CheckCircle, AlertCircle, Loader } from 'lucide-react';

export default function IndexingStatus() {
  const indexingStatus = useAppStore((s) => s.indexingStatus);

  if (!indexingStatus) return null;

  const { status, files_processed, total_files } = indexingStatus;
  const percentage =
    total_files > 0 ? Math.round((files_processed / total_files) * 100) : 0;

  return (
    <div className="flex items-center gap-2">
      {(status === 'initializing' || status === 'indexing') && (
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

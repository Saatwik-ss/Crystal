import { useState, useEffect } from 'react';
import { useAppStore } from './store';
import { apiClient, LOCAL_SESSION_ID } from './api/client';
import { useRepositoryIndexing } from './hooks/useRepositoryIndexing';
import Upload from './components/Upload';
import Editor from './components/Editor';
import Explorer from './components/Explorer';
import ChatSidebar from './components/ChatSidebar';
import IndexingStatus from './components/IndexingStatus';
import NewFileDialog from './components/NewFileDialog';
import { Menu, FolderPlus, FilePlus } from 'lucide-react';

export default function App() {
  const currentRepository = useAppStore((s) => s.currentRepository);
  const handleChatWsMessage = useAppStore((s) => s.handleChatWsMessage);
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const [showUpload, setShowUpload] = useState(false);
  const [showNewFile, setShowNewFile] = useState(false);

  useRepositoryIndexing();

  useEffect(() => {
    if (currentRepository) {
      setShowUpload(false);
    }
  }, [currentRepository]);

  // Always keep chat + completion sockets open (local session if no repo)
  useEffect(() => {
    const sessionId = currentRepository?.id || LOCAL_SESSION_ID;

    apiClient.connectChat(
      sessionId,
      handleChatWsMessage,
      (error) => {
        console.error('Chat error:', error);
      }
    );

    apiClient.connectCompletion(
      sessionId,
      () => undefined,
      (error) => {
        console.error('Completion error:', error);
      }
    );

    return () => {
      apiClient.closeConnections();
    };
  }, [currentRepository, handleChatWsMessage]);

  return (
    <div className="flex h-screen bg-gray-900 text-gray-100">
      {/* Explorer Sidebar */}
      <div className="w-64 bg-gray-800 border-r border-gray-700 flex flex-col overflow-hidden">
        <div className="p-4 border-b border-gray-700 flex items-center justify-between">
          <h2 className="font-semibold text-sm">Explorer</h2>
          <div className="flex gap-1">
            <button
              onClick={() => setShowNewFile(true)}
              className="p-1 text-gray-300 hover:bg-gray-700 rounded"
              title="New file"
            >
              <FilePlus size={16} />
            </button>
            <button
              onClick={() => setShowUpload(true)}
              className="p-1 text-gray-300 hover:bg-gray-700 rounded"
              title="Add repository files or folders"
            >
              <FolderPlus size={16} />
            </button>
          </div>
        </div>
        <Explorer />
      </div>

      {/* Editor Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        <div className="bg-gray-800 border-b border-gray-700 px-4 py-2 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <span className="text-gray-400">Workspace:</span>
            <span className="font-mono">
              {currentRepository?.name || 'Local (no repository)'}
            </span>
          </div>
          <IndexingStatus />
        </div>

        <div className="flex-1 overflow-hidden">
          <Editor onRequestNewFile={() => setShowNewFile(true)} />
        </div>
      </div>

      {sidebarOpen && (
        <div className="w-96 bg-gray-800 border-l border-gray-700 flex flex-col overflow-hidden">
          <ChatSidebar />
        </div>
      )}

      {!sidebarOpen && (
        <button
          onClick={toggleSidebar}
          className="fixed bottom-6 right-6 p-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
          title="Open AI Chat"
        >
          <Menu size={20} />
        </button>
      )}

      {showUpload && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-xl font-bold">Add repository context</h2>
              <button
                onClick={() => setShowUpload(false)}
                className="text-gray-400 hover:text-white text-sm"
              >
                Close
              </button>
            </div>
            <Upload
              compact
              onUploadComplete={() => {
                setShowUpload(false);
              }}
            />
          </div>
        </div>
      )}

      {showNewFile && <NewFileDialog onClose={() => setShowNewFile(false)} />}
    </div>
  );
}

import { useState, useEffect } from 'react';
import { useAppStore } from './store';
import { apiClient } from './api/client';
import { useRepositoryIndexing } from './hooks/useRepositoryIndexing';
import Upload from './components/Upload';
import Editor from './components/Editor';
import Explorer from './components/Explorer';
import ChatSidebar from './components/ChatSidebar';
import IndexingStatus from './components/IndexingStatus';
import { Menu, FolderPlus, FilePlus } from 'lucide-react';

export default function App() {
  const currentRepository = useAppStore((s) => s.currentRepository);
  const handleChatWsMessage = useAppStore((s) => s.handleChatWsMessage);
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const [showUpload, setShowUpload] = useState(false);

  useRepositoryIndexing();

  useEffect(() => {
    if (currentRepository) {
      setShowUpload(false);
    }
  }, [currentRepository]);

  useEffect(() => {
    if (!currentRepository) return;

    apiClient.connectChat(
      currentRepository.id,
      handleChatWsMessage,
      (error) => {
        console.error('Chat error:', error);
      }
    );

    apiClient.connectCompletion(
      currentRepository.id,
      (message) => {
        console.log('Completion message:', message);
      },
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
            <button onClick={() => setShowUpload(true)} className="p-1 text-gray-300 hover:bg-gray-700 rounded" title="Add repository files or folders"><FolderPlus size={16} /></button>
            <button onClick={() => setShowUpload(true)} className="p-1 text-gray-300 hover:bg-gray-700 rounded" title="Add file context"><FilePlus size={16} /></button>
          </div>
        </div>
        <Explorer />
      </div>

      {/* Editor Area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* Top status bar */}
        <div className="bg-gray-800 border-b border-gray-700 px-4 py-2 flex items-center justify-between text-xs">
          <div className="flex items-center gap-2">
            <span className="text-gray-400">Repository:</span>
            <span className="font-mono">{currentRepository?.name || 'No repository loaded'}</span>
          </div>
          <IndexingStatus />
        </div>

        {/* Main editor */}
        <div className="flex-1 overflow-hidden">
          <Editor />
        </div>
      </div>

      {/* Right Sidebar - Chat */}
      {sidebarOpen && (
        <div className="w-96 bg-gray-800 border-l border-gray-700 flex flex-col overflow-hidden">
          <ChatSidebar />
        </div>
      )}

      {/* Toggle sidebar button */}
      {!sidebarOpen && (
        <button
          onClick={toggleSidebar}
          className="fixed bottom-6 right-6 p-2 bg-blue-600 hover:bg-blue-700 rounded-lg transition-colors"
          title="Open AI Chat"
        >
          <Menu size={20} />
        </button>
      )}

      {/* Upload dialog */}
      {showUpload && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-gray-800 rounded-lg p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
            <h2 className="text-xl font-bold mb-4">Add repository context</h2>
            <Upload
              onUploadComplete={() => {
                setShowUpload(false);
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}

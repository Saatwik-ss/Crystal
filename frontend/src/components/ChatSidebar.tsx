import { useState, useRef, useEffect } from 'react';
import { useAppStore } from '../store';
import { apiClient, LOCAL_SESSION_ID } from '../api/client';
import EditProposalCard from './EditProposalCard';
import { Send, Trash2, X } from 'lucide-react';
import clsx from 'clsx';

export default function ChatSidebar() {
  const {
    currentRepository,
    chatMessages,
    streamingContent,
    isStreaming,
    statusLine,
    pendingEdits,
    addChatMessage,
    clearChatMessages,
    startChatStream,
    toggleSidebar,
    activeFile,
    selectedCode,
    openFiles,
  } = useAppStore();

  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [chatMessages, streamingContent, pendingEdits, statusLine]);

  const handleSendMessage = async () => {
    if (!input.trim() || isStreaming) return;

    const userMessage = input.trim();
    setInput('');

    addChatMessage({
      role: 'user',
      content: userMessage,
      type: 'message',
      timestamp: new Date().toISOString(),
    });

    startChatStream();

    const activeContent = activeFile ? openFiles.get(activeFile)?.content : undefined;
    // Prefer full open file for edit proposals; fall back to selection / truncated buffer
    const codeContext =
      selectedCode ||
      (activeContent
        ? activeContent.length > 12000
          ? activeContent.slice(0, 12000)
          : activeContent
        : undefined);

    try {
      await apiClient.sendChatMessage(
        currentRepository?.id || LOCAL_SESSION_ID,
        userMessage,
        activeFile || undefined,
        codeContext
      );
    } catch (error) {
      console.error('Failed to send message:', error);
      addChatMessage({
        role: 'assistant',
        content: 'Failed to send message. Please try again.',
        type: 'error',
        timestamp: new Date().toISOString(),
      });
      useAppStore.setState({ isStreaming: false, streamingContent: '' });
    }
  };

  return (
    <div className="h-full flex flex-col bg-gray-800 border-l border-gray-700">
      <div className="p-4 border-b border-gray-700 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-white">AI Assistant</h3>
          <p className="text-xs text-gray-400 mt-1">
            {currentRepository ? 'Chat with your codebase' : 'General coding chat'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={clearChatMessages}
            className="text-gray-400 hover:text-gray-200 transition-colors"
            title="Clear chat"
          >
            <Trash2 size={16} />
          </button>
          <button
            onClick={() => toggleSidebar()}
            className="text-gray-400 hover:text-gray-200 transition-colors"
            title="Close sidebar"
          >
            <X size={16} />
          </button>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {chatMessages.length === 0 && !isStreaming && !pendingEdits && (
          <div className="h-full flex items-center justify-center">
            <div className="text-center text-gray-400">
              <p className="text-sm">Ask anything about code</p>
              <p className="text-xs mt-2 text-gray-500">
                Upload a folder for codebase-aware answers.
              </p>
            </div>
          </div>
        )}

        {chatMessages.map((message, idx) => (
          <div
            key={idx}
            className={clsx(
              'flex gap-3',
              message.role === 'user' ? 'justify-end' : 'justify-start'
            )}
          >
            <div
              className={clsx(
                'max-w-xs px-4 py-2 rounded-lg text-sm',
                message.role === 'user'
                  ? 'bg-blue-600 text-white'
                  : message.type === 'error'
                  ? 'bg-red-900 text-red-100'
                  : 'bg-gray-700 text-gray-100'
              )}
            >
              <p className="whitespace-pre-wrap break-words">{message.content}</p>
              {message.timestamp && (
                <p className="text-xs opacity-50 mt-1">
                  {new Date(message.timestamp).toLocaleTimeString()}
                </p>
              )}
            </div>
          </div>
        ))}

        {isStreaming && streamingContent && (
          <div className="flex gap-3 justify-start">
            <div className="max-w-xs px-4 py-2 rounded-lg text-sm bg-gray-700 text-gray-100">
              <p className="whitespace-pre-wrap break-words">
                {streamingContent}
              </p>
              <div className="flex gap-1 mt-2">
                <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" />
                <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-100" />
                <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-200" />
              </div>
            </div>
          </div>
        )}

        {isStreaming && !streamingContent && statusLine && (
          <p className="text-xs text-gray-500 px-1">{statusLine}</p>
        )}

        <div ref={messagesEndRef} />
      </div>

      <EditProposalCard />

      <div className="p-4 border-t border-gray-700">
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSendMessage();
              }
            }}
            placeholder="Ask about your code..."
            disabled={isStreaming}
            className="flex-1 bg-gray-700 text-white placeholder-gray-500 px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed"
          />
          <button
            onClick={handleSendMessage}
            disabled={isStreaming || !input.trim()}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-4 py-2 rounded transition-colors flex items-center gap-2"
          >
            <Send size={16} />
          </button>
        </div>

        {activeFile && (
          <p className="text-xs text-gray-400 mt-2">
            Current file: {activeFile.split('/').pop()}
          </p>
        )}

        {selectedCode && (
          <p className="text-xs text-gray-400 mt-1">
            Code selected: {selectedCode.split('\n').length} lines
          </p>
        )}
      </div>
    </div>
  );
}

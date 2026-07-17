import { useState, useRef, useEffect } from 'react';
import { useAppStore } from '../store';
import { apiClient } from '../api/client';
import { Send, Trash2, X } from 'lucide-react';
import clsx from 'clsx';

export default function ChatSidebar() {
  const {
    currentRepository,
    chatMessages,
    addChatMessage,
    clearChatMessages,
    toggleSidebar,
    activeFile,
    selectedCode,
  } = useAppStore();

  const [input, setInput] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const [streaming, setStreaming] = useState(false);
  const [currentStreamingMessage, setCurrentStreamingMessage] = useState('');
  const streamingMessageRef = useRef('');

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  useEffect(() => {
    scrollToBottom();
  }, [chatMessages, currentStreamingMessage]);

  const handleSendMessage = async () => {
    if (!input.trim() || !currentRepository) return;

    const userMessage = input.trim();
    setInput('');

    // Add user message
    addChatMessage({
      role: 'user',
      content: userMessage,
      type: 'message',
      timestamp: new Date().toISOString(),
    });

    // Start streaming response
    setStreaming(true);
    streamingMessageRef.current = '';
    setCurrentStreamingMessage('');

    try {
      await apiClient.sendChatMessage(
        currentRepository.id,
        userMessage,
        activeFile || undefined,
        selectedCode || undefined
      );
    } catch (error) {
      console.error('Failed to send message:', error);
      addChatMessage({
        role: 'assistant',
        content: 'Failed to send message. Please try again.',
        type: 'error',
        timestamp: new Date().toISOString(),
      });
      setStreaming(false);
    }
  };

  // Handle incoming chat messages from WebSocket
  useEffect(() => {
    // This should be connected in main App.tsx
    const handleChatMessage = (message: any) => {
      if (message.type === 'content') {
        setCurrentStreamingMessage((prev) => prev + message.content);
      } else if (message.type === 'message') {
        addChatMessage({
          role: 'assistant', content: message.content, type: 'message', timestamp: new Date().toISOString(),
        });
        setStreaming(false);
      } else if (message.type === 'end') {
        if (currentStreamingMessage) {
          addChatMessage({
            role: 'assistant',
            content: currentStreamingMessage,
            type: 'message',
            timestamp: new Date().toISOString(),
          });
          setCurrentStreamingMessage('');
        }
        setStreaming(false);
      } else if (message.type === 'error') {
        addChatMessage({
          role: 'assistant',
          content: `Error: ${message.error}`,
          type: 'error',
          timestamp: new Date().toISOString(),
        });
        setStreaming(false);
      } else if (message.type === 'tool_call') {
        setCurrentStreamingMessage(
          (prev) =>
            prev +
            `\n📞 Calling tool: ${message.tool}\n Args: ${JSON.stringify(
              message.args
            )}\n`
        );
      }
    };

    const listener = (event: Event) => handleChatMessage((event as CustomEvent).detail);
    window.addEventListener('ai-chat-message', listener);
    return () => window.removeEventListener('ai-chat-message', listener);
  }, [currentStreamingMessage, addChatMessage]);

  return (
    <div className="h-full flex flex-col bg-gray-800 border-l border-gray-700">
      {/* Header */}
      <div className="p-4 border-b border-gray-700 flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-white">AI Assistant</h3>
          <p className="text-xs text-gray-400 mt-1">Chat with your codebase</p>
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

      {/* Messages */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {chatMessages.length === 0 && !streaming && (
          <div className="h-full flex items-center justify-center">
            <div className="text-center text-gray-400">
              <p className="text-sm">Start a conversation to analyze your code</p>
              <p className="text-xs mt-2 text-gray-500">
                The AI will use repository context and selected code
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

        {streaming && currentStreamingMessage && (
          <div className="flex gap-3 justify-start">
            <div className="max-w-xs px-4 py-2 rounded-lg text-sm bg-gray-700 text-gray-100">
              <p className="whitespace-pre-wrap break-words">
                {currentStreamingMessage}
              </p>
              <div className="flex gap-1 mt-2">
                <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce" />
                <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-100" />
                <div className="w-2 h-2 bg-gray-500 rounded-full animate-bounce delay-200" />
              </div>
            </div>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Input */}
      <div className="p-4 border-t border-gray-700">
        {!currentRepository && (
          <p className="text-xs text-amber-300 mb-2">Add a repository from the Explorer first, then I can answer with its code context.</p>
        )}
        <div className="flex gap-2">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyPress={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSendMessage();
              }
            }}
            placeholder="Ask about your code..."
            disabled={streaming || !currentRepository}
            className="flex-1 bg-gray-700 text-white placeholder-gray-500 px-3 py-2 rounded border border-gray-600 focus:border-blue-500 focus:outline-none disabled:opacity-50 disabled:cursor-not-allowed"
          />
          <button
            onClick={handleSendMessage}
            disabled={streaming || !input.trim() || !currentRepository}
            className="bg-blue-600 hover:bg-blue-700 disabled:bg-gray-600 disabled:cursor-not-allowed text-white px-4 py-2 rounded transition-colors flex items-center gap-2"
          >
            <Send size={16} />
          </button>
        </div>

        {activeFile && (
          <p className="text-xs text-gray-400 mt-2">
            📄 Current file: {activeFile.split('/').pop()}
          </p>
        )}

        {selectedCode && (
          <p className="text-xs text-gray-400 mt-1">
            ✂️ Code selected: {selectedCode.split('\n').length} lines
          </p>
        )}
      </div>
    </div>
  );
}

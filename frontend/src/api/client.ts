/// <reference types="vite/client" />
import axios, { AxiosInstance } from 'axios';
import type {
  Repository,
  IndexingStatus,
  RepositoryFile,
  SearchResult,
} from '../types';

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const WS_BASE_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000';

class APIClient {
  private client: AxiosInstance;
  private wsConnections: Map<string, WebSocket> = new Map();
  private pendingCompletion: {
    resolve: (text: string) => void;
    reject: (error: Error) => void;
    buffer: string;
  } | null = null;

  constructor() {
    this.client = axios.create({
      baseURL: API_BASE_URL,
    });
  }

  // Repository endpoints
  async uploadRepository(files: File[]): Promise<Repository> {
    const formData = new FormData();
    files.forEach((file) => {
      // Preserve a selected folder's relative path for the backend file tree.
      const relativePath = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name;
      formData.append('files', file, relativePath);
    });

    const response = await this.client.post('/api/upload-repository', formData);

    const responseData = response.data as any;
    const repository = responseData.repository ?? responseData;

    return {
      ...repository,
      id: repository.id ?? repository.repository_id,
    } as Repository;
  }

  async getRepositoryStatus(repoId: string): Promise<IndexingStatus> {
    const response = await this.client.get(
      `/api/repositories/${repoId}/status`
    );
    return response.data;
  }

  async listRepositoryFiles(repoId: string): Promise<RepositoryFile[]> {
    const response = await this.client.get(
      `/api/repositories/${repoId}/files`
    );
    return response.data.files;
  }

  async readFile(repoId: string, filePath: string): Promise<string> {
    const normalizedPath = filePath.replace(/\\/g, '/');
    const response = await this.client.get(
      `/api/repositories/${repoId}/file/${normalizedPath}`
    );
    return response.data.content;
  }

  async writeFile(
    repoId: string,
    filePath: string,
    content: string
  ): Promise<{ status: string }> {
    const response = await this.client.post(
      `/api/repositories/${repoId}/file/${filePath}`,
      { content }
    );
    return response.data;
  }

  // Chat WebSocket
  connectChat(
    repoId: string,
    onMessage: (message: any) => void,
    onError: (error: any) => void
  ): void {
    const key = `chat_${repoId}`;
    this.closeConnection(key);

    const wsUrl = `${WS_BASE_URL}/ws/chat/${repoId}`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        onMessage(message);
      } catch (error) {
        console.error('Failed to parse chat message:', error);
      }
    };

    ws.onerror = (event) => {
      console.error('Chat WebSocket error:', event);
      onError(event);
    };

    ws.onclose = () => {
      if (this.wsConnections.get(key) === ws) {
        this.wsConnections.delete(key);
      }
    };

    this.wsConnections.set(key, ws);
  }

  async sendChatMessage(
    repoId: string,
    message: string,
    selectedFile?: string,
    selectedCode?: string
  ): Promise<void> {
    let ws = this.wsConnections.get(`chat_${repoId}`);
    if (!ws) {
      this.connectChat(repoId, () => undefined, () => undefined);
      ws = this.wsConnections.get(`chat_${repoId}`);
    }
    if (!ws) throw new Error('Unable to create a chat connection');

    if (ws.readyState === WebSocket.CONNECTING) {
      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error('Chat connection timed out')), 8000);
        ws!.addEventListener('open', () => { window.clearTimeout(timeout); resolve(); }, { once: true });
        ws!.addEventListener('error', () => { window.clearTimeout(timeout); reject(new Error('Chat connection failed')); }, { once: true });
      });
    }
    if (ws.readyState !== WebSocket.OPEN) throw new Error('Chat connection is closed');
    ws.send(JSON.stringify({ message, selected_file: selectedFile, selected_code: selectedCode }));
  }

  // Completion WebSocket
  connectCompletion(
    repoId: string,
    onMessage: (message: any) => void,
    onError: (error: any) => void
  ): void {
    const key = `completion_${repoId}`;
    this.closeConnection(key);

    const wsUrl = `${WS_BASE_URL}/ws/completion/${repoId}`;
    const ws = new WebSocket(wsUrl);

    ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        if (this.pendingCompletion) {
          if (message.type === 'completion' && message.text) {
            this.pendingCompletion.buffer += message.text;
          } else if (message.type === 'end') {
            const text = this.pendingCompletion.buffer;
            const { resolve } = this.pendingCompletion;
            this.pendingCompletion = null;
            resolve(text);
          } else if (message.type === 'error') {
            const { reject } = this.pendingCompletion;
            this.pendingCompletion = null;
            reject(new Error(message.error || 'Completion failed'));
          }
        }
        onMessage(message);
      } catch (error) {
        console.error('Failed to parse completion message:', error);
      }
    };

    ws.onerror = (event) => {
      console.error('Completion WebSocket error:', event);
      onError(event);
    };

    ws.onclose = () => {
      if (this.wsConnections.get(key) === ws) {
        this.wsConnections.delete(key);
      }
    };

    this.wsConnections.set(key, ws);
  }

  async requestCompletion(
    repoId: string,
    prompt: string,
    filePath?: string,
    language?: string
  ): Promise<string> {
    let ws = this.wsConnections.get(`completion_${repoId}`);
    if (!ws) {
      this.connectCompletion(repoId, () => undefined, () => undefined);
      ws = this.wsConnections.get(`completion_${repoId}`);
    }
    if (!ws) throw new Error('Unable to create a completion connection');

    if (ws.readyState === WebSocket.CONNECTING) {
      await new Promise<void>((resolve, reject) => {
        const timeout = window.setTimeout(() => reject(new Error('Completion connection timed out')), 8000);
        ws!.addEventListener('open', () => { window.clearTimeout(timeout); resolve(); }, { once: true });
        ws!.addEventListener('error', () => { window.clearTimeout(timeout); reject(new Error('Completion connection failed')); }, { once: true });
      });
    }
    if (ws.readyState !== WebSocket.OPEN) {
      throw new Error('Completion connection is closed');
    }
    if (this.pendingCompletion) {
      throw new Error('Another completion request is in progress');
    }

    return new Promise<string>((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        if (this.pendingCompletion) {
          const partial = this.pendingCompletion.buffer;
          this.pendingCompletion = null;
          if (partial) {
            resolve(partial);
          } else {
            reject(new Error('Completion timed out'));
          }
        }
      }, 12000);

      this.pendingCompletion = {
        buffer: '',
        resolve: (text) => {
          window.clearTimeout(timeout);
          resolve(text);
        },
        reject: (error) => {
          window.clearTimeout(timeout);
          reject(error);
        },
      };

      ws.send(
        JSON.stringify({
          prompt,
          file_path: filePath,
          language: language || 'javascript',
        })
      );
    });
  }

  // Search
  async search(
    repoId: string,
    query: string,
    searchType: 'semantic' | 'keyword' | 'hybrid' = 'semantic',
    topK: number = 5
  ): Promise<SearchResult[]> {
    const response = await this.client.get(
      `/api/search/${repoId}`,
      {
        params: {
          query,
          search_type: searchType,
          top_k: topK,
        },
      }
    );
    return response.data.results;
  }

  // Cleanup
  closeConnections(): void {
    this.wsConnections.forEach((ws) => {
      if (
        ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING
      ) {
        try {
          ws.close();
        } catch {
          // ignore close errors during cleanup
        }
      }
    });
    this.wsConnections.clear();
  }

  closeConnection(key: string): void {
    const ws = this.wsConnections.get(key);
    if (
      ws &&
      (ws.readyState === WebSocket.OPEN ||
        ws.readyState === WebSocket.CONNECTING)
    ) {
      try {
        ws.close();
      } catch {
        // ignore close errors during cleanup
      }
    }
    this.wsConnections.delete(key);
  }
}

export const apiClient = new APIClient();

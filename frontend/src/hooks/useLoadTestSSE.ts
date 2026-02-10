import { useState, useEffect, useRef } from 'react';

// Use relative URL to leverage Vite proxy
const API_BASE_URL = '';

interface SSEMessage {
  type: string;
  data: any;
}

// Global SSE connection manager - persists across component mounts/unmounts
class SSEConnectionManager {
  private static instance: SSEConnectionManager;
  private eventSource: EventSource | null = null;
  private sessionId: string | null = null;
  private listeners: Set<(message: SSEMessage) => void> = new Set();
  private connectionListeners: Set<(connected: boolean) => void> = new Set();
  private isConnected: boolean = false;

  private constructor() {}

  static getInstance(): SSEConnectionManager {
    if (!SSEConnectionManager.instance) {
      SSEConnectionManager.instance = new SSEConnectionManager();
    }
    return SSEConnectionManager.instance;
  }

  connect(sessionId: string) {
    // If already connected to the same session, do nothing
    if (this.sessionId === sessionId && this.eventSource) {
      console.log('SSE already connected to session:', sessionId);
      return;
    }

    // Close existing connection if different session
    if (this.eventSource && this.sessionId !== sessionId) {
      console.log('Closing previous SSE connection:', this.sessionId);
      this.disconnect();
    }

    console.log('Creating persistent SSE connection for:', sessionId);
    this.sessionId = sessionId;

    const eventSource = new EventSource(`${API_BASE_URL}/api/v1/sse/${sessionId}`);
    this.eventSource = eventSource;

    eventSource.onopen = () => {
      console.log('Persistent SSE connected:', sessionId);
      this.isConnected = true;
      this.notifyConnectionListeners(true);
    };

    eventSource.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);

        if (message.type === 'connected') {
          console.log('SSE connection confirmed:', message);
          return;
        }

        // Notify all listeners
        this.listeners.forEach(listener => listener(message));
      } catch (error) {
        console.error('Failed to parse SSE message:', error);
      }
    };

    eventSource.onerror = (error) => {
      console.error('Persistent SSE error:', error);
      this.isConnected = false;
      this.notifyConnectionListeners(false);

      if (eventSource.readyState === EventSource.CLOSED) {
        console.log('Persistent SSE connection closed');
      }
    };
  }

  disconnect() {
    if (this.eventSource) {
      console.log('Disconnecting persistent SSE:', this.sessionId);
      this.eventSource.close();
      this.eventSource = null;
      this.sessionId = null;
      this.isConnected = false;
      this.notifyConnectionListeners(false);
    }
  }

  addListener(listener: (message: SSEMessage) => void) {
    this.listeners.add(listener);
  }

  removeListener(listener: (message: SSEMessage) => void) {
    this.listeners.delete(listener);
  }

  addConnectionListener(listener: (connected: boolean) => void) {
    this.connectionListeners.add(listener);
    // Immediately notify of current state
    listener(this.isConnected);
  }

  removeConnectionListener(listener: (connected: boolean) => void) {
    this.connectionListeners.delete(listener);
  }

  private notifyConnectionListeners(connected: boolean) {
    this.connectionListeners.forEach(listener => listener(connected));
  }

  getConnectionStatus(): boolean {
    return this.isConnected;
  }
}

export const useLoadTestSSE = (sessionId: string, enabled: boolean = true) => {
  const [messages, setMessages] = useState<SSEMessage[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const managerRef = useRef(SSEConnectionManager.getInstance());

  useEffect(() => {
    if (!enabled || !sessionId) {
      return;
    }

    const manager = managerRef.current;

    // Message listener
    const handleMessage = (message: SSEMessage) => {
      setMessages((prev) => [...prev, message]);
    };

    // Connection status listener
    const handleConnectionChange = (connected: boolean) => {
      setIsConnected(connected);
    };

    // Connect to SSE
    manager.connect(sessionId);
    manager.addListener(handleMessage);
    manager.addConnectionListener(handleConnectionChange);

    // Cleanup: Remove listeners but DON'T disconnect (connection persists)
    return () => {
      console.log('Component unmounting, removing listeners (connection persists)');
      manager.removeListener(handleMessage);
      manager.removeConnectionListener(handleConnectionChange);
      // DON'T call manager.disconnect() - let connection persist!
    };
  }, [sessionId, enabled]);

  // Method to clear messages
  const clearMessages = () => {
    setMessages([]);
  };

  // Method to manually close persistent connection (call when really needed)
  const disconnect = () => {
    managerRef.current.disconnect();
  };

  return {
    messages,
    isConnected,
    clearMessages,
    disconnect,
  };
};

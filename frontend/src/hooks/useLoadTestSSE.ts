import { useState, useEffect, useRef } from 'react';

// Use relative URL to leverage Vite proxy
const API_BASE_URL = '';

interface SSEMessage {
  type: string;
  data: any;
}

export const useLoadTestSSE = (sessionId: string, enabled: boolean = true) => {
  const [messages, setMessages] = useState<SSEMessage[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!enabled || !sessionId) {
      return;
    }

    // Create SSE connection
    const eventSource = new EventSource(`${API_BASE_URL}/api/v1/sse/${sessionId}`);
    eventSourceRef.current = eventSource;

    eventSource.onopen = () => {
      console.log('SSE connected for load test:', sessionId);
      setIsConnected(true);
    };

    eventSource.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);

        // Handle different message types
        if (message.type === 'connected') {
          console.log('SSE connection confirmed:', message);
          return;
        }

        // Add message to state
        setMessages((prev) => [...prev, message]);
      } catch (error) {
        console.error('Failed to parse SSE message:', error);
      }
    };

    eventSource.onerror = (error) => {
      console.error('SSE error:', error);
      setIsConnected(false);

      // EventSource automatically reconnects, but we can handle errors here
      if (eventSource.readyState === EventSource.CLOSED) {
        console.log('SSE connection closed');
      }
    };

    // Cleanup on unmount or when sessionId changes
    return () => {
      console.log('Closing SSE connection for:', sessionId);
      eventSource.close();
      eventSourceRef.current = null;
      setIsConnected(false);
    };
  }, [sessionId, enabled]);

  // Method to clear messages
  const clearMessages = () => {
    setMessages([]);
  };

  // Method to manually close connection
  const disconnect = () => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
      setIsConnected(false);
    }
  };

  return {
    messages,
    isConnected,
    clearMessages,
    disconnect,
  };
};

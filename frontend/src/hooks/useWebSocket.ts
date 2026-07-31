/**
 * PREDICT — WebSocket Hook
 * Connects to the backend WebSocket for real-time dashboard updates.
 * Receives telemetry, alert, work order, and health events via Redis pub/sub.
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import type { WSMessage } from '../types';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws';

type MessageHandler = (msg: WSMessage) => void;

export function useWebSocket(onMessage?: MessageHandler) {
  const [connected, setConnected] = useState(false);
  const [lastMessage, setLastMessage] = useState<WSMessage | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const intentionalClose = useRef(false);
  const handlerRef = useRef(onMessage);

  useEffect(() => {
    handlerRef.current = onMessage;
  }, [onMessage]);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    intentionalClose.current = false;

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => {
        setConnected(true);
        console.log('[WS] Connected to', WS_URL);
      };

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data);
          setLastMessage(msg);
          handlerRef.current?.(msg);
        } catch (e) {
          console.error('[WS] Failed to parse message:', e);
        }
      };

      ws.onerror = (error) => {
        console.error('[WS] Error:', error);
      };

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (intentionalClose.current) return;
        console.log('[WS] Disconnected, will retry in 3s...');
        reconnectTimer.current = window.setTimeout(() => {
          connect();
        }, 3000);
      };
    } catch (e) {
      console.error('[WS] Connection failed:', e);
      if (!intentionalClose.current) {
        reconnectTimer.current = window.setTimeout(() => connect(), 3000);
      }
    }
  }, []);

  useEffect(() => {
    connect();

    return () => {
      intentionalClose.current = true;
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  const sendMessage = useCallback((msg: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(msg);
    }
  }, []);

  return { connected, lastMessage, sendMessage };
}

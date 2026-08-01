/**
 * PREDICT — WebSocket context
 * Single connection shared by the whole app. Components subscribe to the
 * channels they care about and receive every message exactly once — this
 * replaces the old grow-and-slice message array whose index bookkeeping
 * silently stopped delivering updates after 100 messages.
 */
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from 'react';
import type { WSMessage } from '../types';

const WS_URL = import.meta.env.VITE_WS_URL || 'ws://localhost:8000/ws';

type Handler = (msg: WSMessage) => void;

interface WsContextValue {
  connected: boolean;
  subscribe: (channels: string[], handler: Handler) => () => void;
}

const WsContext = createContext<WsContextValue>({
  connected: false,
  subscribe: () => () => {},
});

export function WsProvider({ children }: { children: ReactNode }) {
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<number | null>(null);
  const intentionalClose = useRef(false);
  // channel -> set of handlers ('*' receives everything)
  const handlersRef = useRef<Map<string, Set<Handler>>>(new Map());

  const dispatch = useCallback((msg: WSMessage) => {
    const exact = handlersRef.current.get(msg.channel);
    exact?.forEach((h) => h(msg));
    const wildcard = handlersRef.current.get('*');
    wildcard?.forEach((h) => h(msg));
  }, []);

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return;
    intentionalClose.current = false;

    try {
      const ws = new WebSocket(WS_URL);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);

      ws.onmessage = (event) => {
        try {
          const msg: WSMessage = JSON.parse(event.data);
          dispatch(msg);
        } catch (e) {
          console.error('[WS] Failed to parse message:', e);
        }
      };

      ws.onerror = (error) => console.error('[WS] Error:', error);

      ws.onclose = () => {
        setConnected(false);
        wsRef.current = null;
        if (intentionalClose.current) return;
        reconnectTimer.current = window.setTimeout(() => connect(), 3000);
      };
    } catch (e) {
      console.error('[WS] Connection failed:', e);
      if (!intentionalClose.current) {
        reconnectTimer.current = window.setTimeout(() => connect(), 3000);
      }
    }
  }, [dispatch]);

  useEffect(() => {
    connect();
    return () => {
      intentionalClose.current = true;
      if (reconnectTimer.current) {
        clearTimeout(reconnectTimer.current);
        reconnectTimer.current = null;
      }
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [connect]);

  const subscribe = useCallback((channels: string[], handler: Handler) => {
    for (const ch of channels) {
      let set = handlersRef.current.get(ch);
      if (!set) {
        set = new Set();
        handlersRef.current.set(ch, set);
      }
      set.add(handler);
    }
    return () => {
      for (const ch of channels) {
        handlersRef.current.get(ch)?.delete(handler);
      }
    };
  }, []);

  return (
    <WsContext.Provider value={{ connected, subscribe }}>
      {children}
    </WsContext.Provider>
  );
}

export function useWsConnected(): boolean {
  return useContext(WsContext).connected;
}

/**
 * Subscribe to WebSocket channels. The handler ref is kept current so
 * callers don't need to memoize it.
 */
export function useWsSubscription(channels: string[], handler: Handler) {
  const { subscribe } = useContext(WsContext);
  const handlerRef = useRef(handler);
  handlerRef.current = handler;

  const key = channels.join(',');
  useEffect(() => {
    const unsubscribe = subscribe(key.split(','), (msg) => handlerRef.current(msg));
    return unsubscribe;
  }, [subscribe, key]);
}

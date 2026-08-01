/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL: string;
  readonly VITE_WS_URL: string;
  /** Public IP/hostname for SMS setparam templates (not the TCP bind address). */
  readonly VITE_TRACKER_SERVER: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
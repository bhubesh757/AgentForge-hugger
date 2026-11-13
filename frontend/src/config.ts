const env = import.meta.env;

export const UI_VERSION = '1.0.0';
export const API_VERSION = 'v1';
export const DEMO_MODE = String(env.VITE_DEMO_MODE ?? 'false').toLowerCase() === 'true';
export const API_BASE_URL = String(
  env.VITE_API_BASE_URL || (DEMO_MODE ? 'https://demo.agentforge.local/api/v1' : 'http://localhost:8000/api/v1'),
).replace(/\/+$/, '');
export const ROUTER_MODE: 'hash' | 'browser' = env.VITE_ROUTER_MODE === 'hash' ? 'hash' : 'browser';
export const BASE_PATH = env.BASE_URL || '/';

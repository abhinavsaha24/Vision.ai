import { useState, useCallback } from 'react';
import axios from 'axios';

// Render backend URL (with fallback for local dev)
const API_URL = process.env.REACT_APP_API || 'https://vision-ai-5qm1.onrender.com';

const apiClient = axios.create({
  baseURL: API_URL,
  timeout: 10000,
});

/**
 * Custom hook for interacting with the Vision-AI backend.
 * Provides loading states, error handling, and safe fallback behaviors.
 */
export function useApi() {
  const [loading, setLoading] = useState({});
  const [error, setError] = useState({});

  const request = useCallback(async (method, endpoint, data = null, config = {}) => {
    const reqId = `${method}-${endpoint}`;
    setLoading(prev => ({ ...prev, [reqId]: true }));
    setError(prev => ({ ...prev, [reqId]: null }));

    try {
      const response = await apiClient({
        method,
        url: endpoint,
        data,
        ...config
      });
      return response.data;
    } catch (err) {
      const errorMsg = err.response?.data?.message || err.message || 'Network error';
      setError(prev => ({ ...prev, [reqId]: errorMsg }));
      // Return null or undefined on error to avoid crashing the UI, allowing components to use fallbacks
      console.warn(`[VISION-AI API] ${method} ${endpoint} failed:`, errorMsg);
      throw err;
    } finally {
      setLoading(prev => ({ ...prev, [reqId]: false }));
    }
  }, []);

  // API Methods
  const get = useCallback((endpoint, config) => request('get', endpoint, null, config), [request]);
  const post = useCallback((endpoint, data, config) => request('post', endpoint, data, config), [request]);

  return { get, post, loading, error };
}

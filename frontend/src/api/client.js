import axios from 'axios';

const baseURL = import.meta.env.VITE_API_BASE_URL || '';

export const STORAGE_KEY = 'llmops_jwt';

export const api = axios.create({
  baseURL,
  withCredentials: false,
  timeout: 10000,
});

api.interceptors.request.use((config) => {
  const token = localStorage.getItem(STORAGE_KEY);
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem(STORAGE_KEY);
    }
    return Promise.reject(err);
  },
);

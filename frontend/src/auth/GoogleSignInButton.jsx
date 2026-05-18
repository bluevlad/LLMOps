import { useEffect, useRef } from 'react';
import { useAuth } from './AuthContext.jsx';

const CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || '';

export function GoogleSignInButton({ onSuccess, onError }) {
  const containerRef = useRef(null);
  const { loginWithGoogleCredential } = useAuth();

  useEffect(() => {
    if (!CLIENT_ID) return;

    let attempts = 0;
    let timer = null;

    function tryRender() {
      if (!window.google?.accounts?.id) {
        attempts += 1;
        if (attempts > 50) {
          onError?.('Google Identity Services 스크립트 로드 실패');
          return;
        }
        timer = setTimeout(tryRender, 100);
        return;
      }
      window.google.accounts.id.initialize({
        client_id: CLIENT_ID,
        callback: async (response) => {
          try {
            const user = await loginWithGoogleCredential(response.credential);
            onSuccess?.(user);
          } catch (err) {
            const msg = err.response?.data?.detail || err.message || 'Login failed';
            onError?.(msg);
          }
        },
      });
      if (containerRef.current) {
        window.google.accounts.id.renderButton(containerRef.current, {
          theme: 'filled_blue',
          size: 'large',
          text: 'signin_with',
          shape: 'rectangular',
          logo_alignment: 'left',
        });
      }
    }
    tryRender();

    return () => { if (timer) clearTimeout(timer); };
  }, [loginWithGoogleCredential, onSuccess, onError]);

  if (!CLIENT_ID) {
    return (
      <div className="error">
        VITE_GOOGLE_CLIENT_ID 미설정 — .env 확인
      </div>
    );
  }
  return <div ref={containerRef} />;
}

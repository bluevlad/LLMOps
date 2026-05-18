import { useState } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { GoogleSignInButton } from '../auth/GoogleSignInButton.jsx';
import { useAuth } from '../auth/AuthContext.jsx';

export default function LoginPage() {
  const { user } = useAuth();
  const location = useLocation();
  const [error, setError] = useState(null);

  if (user) {
    const from = location.state?.from || '/';
    return <Navigate to={from} replace />;
  }

  return (
    <div className="app">
      <header>
        <h1>LLMOps</h1>
        <p className="subtitle">로컬 LLM 사용 현황·ROI 통합 관제</p>
      </header>

      <section style={{ maxWidth: 520 }}>
        <h2>로그인</h2>
        <p className="muted">
          Google 계정으로 로그인하면 LLMOps 자체 JWT 가 발급됩니다.
          첫 가입자는 자동으로 <code>llmops_admin</code>, 이후는 <code>llmops_viewer</code> 입니다.
        </p>
        {error && <pre className="error">{error}</pre>}
        <div style={{ marginTop: 16 }}>
          <GoogleSignInButton
            onSuccess={() => setError(null)}
            onError={(msg) => setError(msg)}
          />
        </div>
        <dl className="kv">
          <dt>Provider</dt><dd>Google Identity Services (ID Token)</dd>
          <dt>JWT</dt><dd>HS256 / 12h expire</dd>
          <dt>Role</dt><dd>llmops_admin / llmops_viewer</dd>
        </dl>
      </section>
    </div>
  );
}

import { Navigate, useLocation } from 'react-router-dom';
import { useAuth } from './AuthContext.jsx';

export function RequireAuth({ children, adminOnly = false }) {
  const { user, loading } = useAuth();
  const location = useLocation();

  if (loading) return <div className="loading">세션 확인 중…</div>;
  if (!user) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  if (adminOnly && user.role !== 'llmops_admin') {
    return (
      <div className="error">
        admin 권한 필요 (현재: <code>{user.role}</code>)
      </div>
    );
  }
  return children;
}

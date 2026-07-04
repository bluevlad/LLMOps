import { Suspense, lazy } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext.jsx';
import { RequireAuth } from './auth/RequireAuth.jsx';
import HomePage from './pages/HomePage.jsx';
import LoginPage from './pages/LoginPage.jsx';
import ModelsPage from './pages/ModelsPage.jsx';

// recharts 가 무거워서 스코어보드만 코드 분할
const ComparisonsPage = lazy(() => import('./pages/ComparisonsPage.jsx'));

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<RequireAuth><HomePage /></RequireAuth>} />
        <Route path="/models" element={<RequireAuth><ModelsPage /></RequireAuth>} />
        <Route
          path="/comparisons"
          element={(
            <RequireAuth>
              <Suspense fallback={<div className="loading">불러오는 중…</div>}>
                <ComparisonsPage />
              </Suspense>
            </RequireAuth>
          )}
        />
      </Routes>
    </AuthProvider>
  );
}

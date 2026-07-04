import { Suspense, lazy } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext.jsx';
import { RequireAuth } from './auth/RequireAuth.jsx';
import HomePage from './pages/HomePage.jsx';
import LoginPage from './pages/LoginPage.jsx';
import ModelsPage from './pages/ModelsPage.jsx';

// recharts / react-flow 가 무거워서 차트 페이지는 코드 분할
const ComparisonsPage = lazy(() => import('./pages/ComparisonsPage.jsx'));
const UsagePage = lazy(() => import('./pages/UsagePage.jsx'));

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<RequireAuth><HomePage /></RequireAuth>} />
        <Route path="/models" element={<RequireAuth><ModelsPage /></RequireAuth>} />
        <Route
          path="/usage"
          element={(
            <RequireAuth>
              <Suspense fallback={<div className="loading">불러오는 중…</div>}>
                <UsagePage />
              </Suspense>
            </RequireAuth>
          )}
        />
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

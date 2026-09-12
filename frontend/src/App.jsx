import { Suspense, lazy } from 'react';
import { Route, Routes } from 'react-router-dom';
import { AuthProvider } from './auth/AuthContext.jsx';
import { RequireAuth } from './auth/RequireAuth.jsx';
import HomePage from './pages/HomePage.jsx';
import LoginPage from './pages/LoginPage.jsx';
import ModelsPage from './pages/ModelsPage.jsx';

// recharts 가 무거워서 상세 페이지는 코드 분할
const ModelDetailPage = lazy(() => import('./pages/ModelDetailPage.jsx'));

// v0.3.0 — 모델 관제 에이전트 한정. 파이프라인 뷰(Flow Map·usage·golden-set·comparisons)는
// DocPipeline /admin 으로 이관 (정본: Ai-Legacy-bluevlad/services/llmops/MODEL_MONITOR_AGENT_PLAN.md)
export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/" element={<HomePage />} />
        <Route path="/models" element={<RequireAuth adminOnly><ModelsPage /></RequireAuth>} />
        <Route
          path="/models/:provider/*"
          element={(
            <RequireAuth adminOnly>
              <Suspense fallback={<div className="loading">불러오는 중…</div>}>
                <ModelDetailPage />
              </Suspense>
            </RequireAuth>
          )}
        />
      </Routes>
    </AuthProvider>
  );
}

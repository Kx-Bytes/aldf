import { useState, useEffect } from 'react';
import LandingPage from './pages/LandingPage';
import Dashboard from './pages/Dashboard';
import { getToken, clearToken } from './services/api';

function App() {
  const [userEmail, setUserEmail] = useState(() => {
    // Check for verified=true redirect from backend email verification
    const params = new URLSearchParams(window.location.search);
    if (params.get('verified') === 'true') {
      window.history.replaceState({}, '', '/');
    }
    return localStorage.getItem('aldf_email') || null;
  });

  useEffect(() => {
    // Intercept the link from the email and redirect to the backend API to process the verification
    const path = window.location.pathname;
    const params = new URLSearchParams(window.location.search);
    const token = params.get('token');
    
    if (path === '/verify-email' && token) {
      window.location.href = `/api/auth/verify/${token}`;
    }
  }, []);

  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    return !!getToken() && !!localStorage.getItem('aldf_email');
  });

  const [theme, setTheme] = useState(() => {
    return localStorage.getItem('aldf_theme') || 'dark';
  });

  // Detect ?verified=true from backend redirect and show login hint
  const [justVerified, setJustVerified] = useState(() => {
    const params = new URLSearchParams(window.location.search);
    return params.get('verified') === 'true';
  });

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('aldf_theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  const handleLogin = (email) => {
    setUserEmail(email);
    setIsAuthenticated(true);
  };

  const handleLogout = () => {
    clearToken();
    setUserEmail(null);
    setIsAuthenticated(false);
  };

  return (
    <>
      {!isAuthenticated ? (
        <LandingPage
          onLogin={handleLogin}
          theme={theme}
          toggleTheme={toggleTheme}
          justVerified={justVerified}
          onVerifiedDismiss={() => setJustVerified(false)}
        />
      ) : (
        <Dashboard
          onLogout={handleLogout}
          theme={theme}
          toggleTheme={toggleTheme}
          userEmail={userEmail}
        />
      )}
    </>
  );
}

export default App;

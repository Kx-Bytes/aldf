import { useState, useEffect } from 'react';
import LandingPage from './pages/LandingPage';
import Dashboard from './pages/Dashboard';

function App() {
  const [isAuthenticated, setIsAuthenticated] = useState(() => {
    return localStorage.getItem('aldf_auth') === 'true';
  });
  const [theme, setTheme] = useState(() => {
    return localStorage.getItem('aldf_theme') || 'dark';
  });

  useEffect(() => {
    localStorage.setItem('aldf_auth', isAuthenticated);
  }, [isAuthenticated]);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('aldf_theme', theme);
  }, [theme]);

  const toggleTheme = () => {
    setTheme(prev => prev === 'dark' ? 'light' : 'dark');
  };

  return (
    <>
      {!isAuthenticated ? (
        <LandingPage onLogin={() => setIsAuthenticated(true)} theme={theme} toggleTheme={toggleTheme} />
      ) : (
        <Dashboard onLogout={() => setIsAuthenticated(false)} theme={theme} toggleTheme={toggleTheme} />
      )}
    </>
  );
}

export default App;

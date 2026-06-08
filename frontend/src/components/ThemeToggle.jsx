import { Moon, Sun } from 'lucide-react';
import './ThemeToggle.css';

export function ThemeToggle({ theme, toggleTheme }) {
  const isDark = theme === 'dark';

  return (
    <div
      className={`theme-toggle ${isDark ? 'is-dark' : 'is-light'}`}
      onClick={toggleTheme}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter') toggleTheme(); }}
    >
      <div className="theme-toggle-inner">
        <div className={`theme-icon-bg ${isDark ? 'bg-dark' : 'bg-light'}`}>
          {isDark ? (
            <Moon className="icon-white" strokeWidth={1.5} size={16} />
          ) : (
            <Sun className="icon-dark" strokeWidth={1.5} size={16} />
          )}
        </div>
        <div className={`theme-icon-bg ${isDark ? 'bg-transparent' : 'bg-transparent-light'}`}>
          {isDark ? (
            <Sun className="icon-grey" strokeWidth={1.5} size={16} />
          ) : (
            <Moon className="icon-black" strokeWidth={1.5} size={16} />
          )}
        </div>
      </div>
    </div>
  );
}

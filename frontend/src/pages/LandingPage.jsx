import { useState } from 'react';
import { ThemeToggle } from '../components/ThemeToggle';
import { Sparkles, ArrowRight, X, Download, Brain, FileSearch, Mail, Scale, Target, LineChart } from 'lucide-react';
import './LandingPage.css';

export default function LandingPage({ onLogin, theme, toggleTheme }) {
  const [authMode, setAuthMode] = useState('login'); // 'login', 'signup'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(false);
  const [errorMsg, setErrorMsg] = useState('');

  const scrollToAuth = (mode) => {
    setAuthMode(mode);
    setTimeout(() => {
      document.getElementById('auth-section')?.scrollIntoView({ behavior: 'smooth' });
    }, 50);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    const storedUsers = JSON.parse(localStorage.getItem('aldf_users') || '[]');

    if (authMode === 'signup') {
      const userExists = storedUsers.find(u => u.email === email);
      if (userExists) {
        setError(true); setErrorMsg('Email already exists.');
        setTimeout(() => setError(false), 3000);
        return;
      }
      localStorage.setItem('aldf_users', JSON.stringify([...storedUsers, { email, password }]));
      onLogin();
    } else if (authMode === 'login') {
      const user = storedUsers.find(u => u.email === email);
      if (user && user.password === password) {
        onLogin();
      } else {
        setError(true); setErrorMsg('Invalid email or password.');
        setTimeout(() => setError(false), 3000);
      }
    }
  };

  return (
    <div className="page-wrapper">
      <div className="bg-grid"></div>
      <div className="hero-glow"></div>

      <nav className="landing-nav">
        <div className="nav-logo" style={{ cursor: 'pointer' }} onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}>
          <Scale className="nav-logo-icon" size={24} strokeWidth={2.5} />
          <span>ALDF</span>
        </div>
        <div className="nav-links">
          <a href="#features" className="nav-link">Features</a>
          <a href="#how-it-works" className="nav-link">How it Works</a>
          <ThemeToggle theme={theme} toggleTheme={toggleTheme} />
          <a className="nav-link" onClick={() => scrollToAuth('login')}>Sign In</a>
        </div>
      </nav>

      <section className="hero-section">
        <div className="hero-badge">
          <Sparkles className="badge-icon" size={14} />
          AI-powered legislative monitoring! <ArrowRight size={14} />
        </div>
        <h1 className="hero-title">
          Track Legislation.<br />Preserve Animal Welfare.
        </h1>
        <p className="hero-subtitle">
          AI-powered monitoring, semantic filtering, and impact analysis of federal animal welfare legislation. Automated entirely for the Animal Legal Defense Fund.
        </p>
        <div className="hero-actions">
          <button className="btn-secondary-lg" onClick={() => document.getElementById('how-it-works').scrollIntoView({behavior: 'smooth'})}>
            Learn More
          </button>
          <button className="btn-primary-lg" onClick={() => scrollToAuth('signup')}>
            Get Started <ArrowRight size={18} />
          </button>
        </div>
      </section>

      <section id="features" className="section-wrapper" style={{ paddingTop: '80px', paddingBottom: '40px' }}>
        <div className="section-header">
          <h2 className="section-title">Everything you need to track legislation</h2>
          <p className="section-subtitle">From automated ingestion to semantic analysis — the ALDF agent handles every step.</p>
        </div>

        <div className="features-grid">
          <div className="feature-cell">
            <Brain className="feature-icon" size={28} />
            <h3 className="feature-title">AI Bill Analysis</h3>
            <p className="feature-desc">Instantly get AI-powered breakdowns of complex legal jargon and understand the direct impact on animal welfare initiatives.</p>
          </div>
          <div className="feature-cell">
            <FileSearch className="feature-icon" size={28} />
            <h3 className="feature-title">Vector Search</h3>
            <p className="feature-desc">Go beyond keyword matching. Our semantic search understands the meaning behind your queries to find highly relevant legislation.</p>
          </div>
          <div className="feature-cell">
            <LineChart className="feature-icon" size={28} />
            <h3 className="feature-title">Progress Tracking</h3>
            <p className="feature-desc">Visually track every bill's journey through the House and Senate with our automated, real-time legislative progress trackers.</p>
          </div>
          <div className="feature-cell">
            <Target className="feature-icon" size={28} />
            <h3 className="feature-title">Smart Filtering</h3>
            <p className="feature-desc">Filter thousands of bills by specific animal subjects (e.g., Wildlife, Agriculture, Testing) to focus strictly on your jurisdiction.</p>
          </div>
          <div className="feature-cell">
            <Mail className="feature-icon" size={28} />
            <h3 className="feature-title">Digest Generation</h3>
            <p className="feature-desc">Automatically compile tracked legislation into executive summaries and daily digests for rapid stakeholder distribution.</p>
          </div>
          <div className="feature-cell">
            <Sparkles className="feature-icon" size={28} />
            <h3 className="feature-title">AI-Powered Everything</h3>
            <p className="feature-desc">Powered by cutting-edge AI models for legal text comprehension, semantic embeddings, and automated content generation.</p>
          </div>
        </div>
      </section>

      <section id="how-it-works" className="section-wrapper" style={{ paddingTop: '40px', paddingBottom: '120px' }}>
        <div className="section-header">
          <h2 className="section-title">How it works</h2>
          <p className="section-subtitle">From scattered congressional data to curated digests in four simple steps — powered by cutting-edge AI.</p>
        </div>
        
        <div className="how-grid">
          <div className="how-card">
            <div className="step-number-float">1</div>
            <div className="how-icon-wrapper"><Download size={24} /></div>
            <h3 className="how-title">Congress.gov Fetch</h3>
            <p className="how-desc">Automatically monitors Congress.gov daily, filtering out the noise and securely downloading only bills that have actively moved or changed status.</p>
          </div>
          <div className="how-card">
            <div className="step-number-float">2</div>
            <div className="how-icon-wrapper"><Brain size={24} /></div>
            <h3 className="how-title">AI Summarization</h3>
            <p className="how-desc">Our AI reads the full legal text and recent actions, generating a precise, plain-language summary focused strictly on animal welfare impacts.</p>
          </div>
          <div className="how-card">
            <div className="step-number-float">3</div>
            <div className="how-icon-wrapper"><Target size={24} /></div>
            <h3 className="how-title">Semantic Filtering</h3>
            <p className="how-desc">Converts custom prompts and bill content into vector embeddings, instantly matching legislation regardless of the exact keywords used in the text.</p>
          </div>
          <div className="how-card">
            <div className="step-number-float">4</div>
            <div className="how-icon-wrapper"><Mail size={24} /></div>
            <h3 className="how-title">Curated Delivery</h3>
            <p className="how-desc">Compiles only the most relevant, high-urgency bills into a beautifully formatted digest delivered directly to your command center dashboard.</p>
          </div>
        </div>
      </section>

      {/* Auth Section */}
      <section id="auth-section" className="section-wrapper auth-section">
        <div className="auth-card">
          <div className="auth-logo">
            <Scale size={20} strokeWidth={2.5} /> ALDF
          </div>
          <h2 className="auth-title">{authMode === 'login' ? 'Welcome back' : 'Create an account'}</h2>
          <p className="auth-subtitle">
            {authMode === 'login' ? 'Sign in to access your command center dashboard' : 'Join to track animal welfare legislation'}
          </p>

          <form onSubmit={handleSubmit} className="auth-form">
            <div className="input-group">
              <label>Email address</label>
              <input 
                type="email" 
                className={`input-field ${error ? 'error-shake' : ''}`}
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
              />
            </div>
            <div className="input-group">
              <div className="password-header">
                <label>Password</label>
                {authMode === 'login' && <a href="#" className="forgot-link">Forgot password?</a>}
              </div>
              <input 
                type="password" 
                className={`input-field ${error ? 'error-shake' : ''}`}
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
              {error && <span className="error-text">{errorMsg}</span>}
            </div>
            
            <button type="submit" className="btn-submit">
              {authMode === 'login' ? 'Sign in to Dashboard' : 'Sign Up'} <ArrowRight size={16} />
            </button>
          </form>

          <div className="auth-footer-divider">
            <span>OR</span>
          </div>

          <div className="auth-footer">
            {authMode === 'login' ? (
              <p>New to ALDF? <a onClick={() => setAuthMode('signup')}>Create an account</a></p>
            ) : (
              <p>Already have an account? <a onClick={() => setAuthMode('login')}>Sign in</a></p>
            )}
          </div>
        </div>
      </section>

    </div>
  );
}

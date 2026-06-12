import { useState, useEffect } from 'react';
import { ThemeToggle } from '../components/ThemeToggle';
import { Sparkles, ArrowRight, X, Download, Brain, FileSearch, Mail, Scale, Target, LineChart, CheckCircle, RefreshCw } from 'lucide-react';
import './LandingPage.css';
import { signup, login, resendVerification, verifyAndActivate, setToken } from '../services/api';

export default function LandingPage({ onLogin, theme, toggleTheme, justVerified, onVerifiedDismiss, activationToken, onActivationDismiss }) {
  const [authMode, setAuthMode] = useState(() => activationToken ? 'activate' : 'login'); // 'login', 'signup', 'activate'
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const [signupSuccess, setSignupSuccess] = useState(false); // "check your email" state
  const [resendLoading, setResendLoading] = useState(false);
  const [resendMsg, setResendMsg] = useState('');

  useEffect(() => {
    if (activationToken) {
      setTimeout(() => {
        document.getElementById('auth-section')?.scrollIntoView({ behavior: 'smooth' });
      }, 200);
    }
  }, [activationToken]);

  const scrollToAuth = (mode) => {
    setAuthMode(mode);
    setError('');
    setTimeout(() => {
      document.getElementById('auth-section')?.scrollIntoView({ behavior: 'smooth' });
    }, 50);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (authMode === 'signup') {
        await signup(email, password);
        setSignupSuccess(true); // Show "check your email" screen
      } else if (authMode === 'activate') {
        const res = await verifyAndActivate(email, password, activationToken);
        setToken(res.access_token);
        localStorage.setItem('aldf_email', res.email);
        onActivationDismiss();
        onLogin(res.email);
      } else {
        const res = await login(email, password);
        setToken(res.access_token);
        localStorage.setItem('aldf_email', res.email);
        onLogin(res.email);
      }
    } catch (err) {
      // Parse the error message from the API response
      const msg = err.message || '';
      if (authMode === 'activate') {
        if (msg.includes('404')) {
          setError('Invalid or expired verification link.');
        } else if (msg.includes('400')) {
          setError('Email address does not match this verification link.');
        } else if (msg.includes('401')) {
          setError('Incorrect password.');
        } else {
          setError('Activation failed. Please try again.');
        }
      } else {
        if (msg.includes('403')) {
          setError('Your email is not verified yet. Please check your inbox.');
        } else if (msg.includes('401')) {
          setError('Invalid email or password.');
        } else if (msg.includes('409')) {
          setError('An account with this email already exists.');
        } else if (msg.includes('400')) {
          setError('Password must be at least 6 characters.');
        } else {
          setError('Something went wrong. Please try again.');
        }
      }
    } finally {
      setLoading(false);
    }
  };

  const handleResend = async () => {
    setResendLoading(true);
    setResendMsg('');
    try {
      await resendVerification(email);
      setResendMsg('Verification email resent! Check your inbox.');
    } catch {
      setResendMsg('Failed to resend. Please try again.');
    } finally {
      setResendLoading(false);
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

          {/* ── Email Verified Banner ── */}
          {justVerified && (
            <div className="auth-verified-banner">
              <CheckCircle size={18} />
              <span>Email verified! You can now sign in.</span>
              <button onClick={onVerifiedDismiss} className="auth-banner-close"><X size={14} /></button>
            </div>
          )}

          {signupSuccess ? (
            /* ── Check Your Email Screen ── */
            <div className="auth-success-screen">
              <div className="auth-success-icon"><Mail size={40} /></div>
              <h2 className="auth-title">Check your inbox</h2>
              <p className="auth-subtitle">
                We sent a verification link to <strong>{email}</strong>. Click it to activate your account, then come back here to sign in.
              </p>
              <p className="auth-subtitle" style={{ fontSize: '0.8rem', marginTop: '0.5rem' }}>
                Didn't get it? Check your spam folder or resend below.
              </p>
              <button
                className="btn-submit"
                style={{ marginTop: '1.5rem', display: 'flex', alignItems: 'center', gap: '8px', justifyContent: 'center' }}
                onClick={handleResend}
                disabled={resendLoading}
              >
                <RefreshCw size={16} className={resendLoading ? 'spin' : ''} />
                {resendLoading ? 'Sending...' : 'Resend verification email'}
              </button>
              {resendMsg && <p className="auth-resend-msg">{resendMsg}</p>}
              <button
                className="forgot-link"
                style={{ marginTop: '1.5rem', background: 'none', border: 'none', cursor: 'pointer' }}
                onClick={() => { setSignupSuccess(false); setAuthMode('login'); }}
              >
                Back to sign in
              </button>
            </div>
          ) : (
            /* ── Login / Signup Form ── */
            <>
              <div className="auth-logo">
                <Scale size={20} strokeWidth={2.5} /> ALDF
              </div>
              <h2 className="auth-title">
                {authMode === 'login' ? 'Welcome back' : authMode === 'activate' ? 'Verify & Activate' : 'Create an account'}
              </h2>
              <p className="auth-subtitle">
                {authMode === 'login' 
                  ? 'Sign in to access your command center dashboard' 
                  : authMode === 'activate'
                    ? 'Confirm your email and password to activate your account'
                    : 'Join to track animal welfare legislation'}
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
                  </div>
                  <input
                    type="password"
                    className={`input-field ${error ? 'error-shake' : ''}`}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    required
                    minLength={6}
                  />
                  {error && <span className="error-text">{error}</span>}
                </div>

                <button type="submit" className="btn-submit" disabled={loading}>
                  {loading
                    ? 'Please wait...'
                    : authMode === 'login' 
                      ? 'Sign in to Dashboard' 
                      : authMode === 'activate' 
                        ? 'Activate & Login' 
                        : 'Create Account'}
                  {!loading && <ArrowRight size={16} />}
                </button>
              </form>

              {authMode !== 'activate' && (
                <div className="auth-footer-divider">
                  <span>OR</span>
                </div>
              )}

              <div className="auth-footer">
                {authMode === 'activate' ? (
                  <p><a onClick={() => { setAuthMode('login'); onActivationDismiss(); setError(''); }}>Back to sign in</a></p>
                ) : authMode === 'login' ? (
                  <p>New to ALDF? <a onClick={() => { setAuthMode('signup'); setError(''); }}>Create an account</a></p>
                ) : (
                  <p>Already have an account? <a onClick={() => { setAuthMode('login'); setError(''); }}>Sign in</a></p>
                )}
              </div>
            </>
          )}
        </div>
      </section>

    </div>
  );
}

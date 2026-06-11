import { useState, useEffect, useRef, useCallback } from 'react';
import {
  fetchBills,
  fetchStats,
  fetchBillDetails,
  fetchBillActions,
  fetchLiveSearch,
  triggerAIProcess,
  getUser,
  updateUser,
  createUser,
  fetchSubjectsGrouped,
  fetchReviewBills
} from '../services/api';
import { ThemeToggle } from '../components/ThemeToggle';
import './Dashboard.css';

const STATES = new Set([
  'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut',
  'Delaware', 'Florida', 'Georgia', 'Hawaii', 'Idaho', 'Illinois', 'Indiana', 'Iowa',
  'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland', 'Massachusetts', 'Michigan',
  'Minnesota', 'Mississippi', 'Missouri', 'Montana', 'Nebraska', 'Nevada', 'New Hampshire',
  'New Jersey', 'New Mexico', 'New York', 'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma',
  'Oregon', 'Pennsylvania', 'Rhode Island', 'South Carolina', 'South Dakota', 'Tennessee',
  'Texas', 'Utah', 'Vermont', 'Virginia', 'Washington', 'West Virginia', 'Wisconsin', 'Wyoming'
]);


const YESTERDAY_ISO = (() => {
  const d = new Date();
  d.setDate(d.getDate() - 1);
  return d.toISOString().split('T')[0];
})();

// Congress.gov updateDate lags action dates by 1-2 days, so the sync
// captures bills whose actions happened up to 2 days ago. Show that
// same window in the "yesterday" tab so nothing falls through the gap.
const TWO_DAYS_AGO_ISO = (() => {
  const d = new Date();
  d.setDate(d.getDate() - 2);
  return d.toISOString().split('T')[0];
})();

export default function Dashboard({ onLogout, theme, toggleTheme, userEmail }) {
  // ── Preferences / Auth State
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [prefPrompt, setPrefPrompt] = useState('');
  const [prefFrequency, setPrefFrequency] = useState('daily');
  const [prefScope, setPrefScope] = useState('federal');
  const [prefMinScore, setPrefMinScore] = useState(70);
  const [prefExpandedTopics, setPrefExpandedTopics] = useState([]);
  const [prefStatus, setPrefStatus] = useState('');
  
  const [activeTab, setActiveTab] = useState('yesterday'); // yesterday, recent, search, live, prefs
  const [searchFiltersOpen, setSearchFiltersOpen] = useState(false);
  
  // ── Search & Filter State
  const [filterKeyword, setFilterKeyword] = useState('');
  const [filterSubject, setFilterSubject] = useState('');
  const [filterChamber, setFilterChamber] = useState('');
  const [filterBillType, setFilterBillType] = useState('');
  const [filterDateFrom, setFilterDateFrom] = useState('');
  const [filterDateTo, setFilterDateTo] = useState('');
  const [filterByPrompt, setFilterByPrompt] = useState(false);
  const [filtersApplied, setFiltersApplied] = useState(false);
  const [subjectGroups, setSubjectGroups] = useState([]);

  // ── Live Search State
  const [liveSearchInput, setLiveSearchInput] = useState('');
  const [liveSearchTopics, setLiveSearchTopics] = useState([]);
  const [showPromptBanner, setShowPromptBanner] = useState(false);
  const [selectedDate, setSelectedDate] = useState(new Date().toISOString().split('T')[0]);
  const [isLiveSearchDateEnabled, setIsLiveSearchDateEnabled] = useState(false);

  // ── API state
  const [bills, setBills] = useState([]);
  const [isFallback, setIsFallback] = useState(false);
  const [totalBills, setTotalBills] = useState(0);
  const [matchingInterests, setMatchingInterests] = useState(0);
  const [yesterdayCount, setYesterdayCount] = useState(0);
  const [reviewedBills, setReviewedBills] = useState([]);
  const [loading, setLoading] = useState(true);

  // ── Modal State
  const [selectedBill, setSelectedBill] = useState(null);
  const [modalTab, setModalTab] = useState('overview'); // overview, ai, history, raw
  const [aiLoading, setAiLoading] = useState(false);

  const formatDisplayDate = (dateStr) => {
    if (!dateStr) return 'N/A';
    const d = new Date(dateStr + 'T00:00:00');
    return d.toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });
  };

  useEffect(() => {
    fetchStats()
      .then(data => {
        setTotalBills(data.total_active_bills || 0);
      })
      .catch(err => console.error('Failed to load stats:', err));
      
    fetchSubjectsGrouped().then(data => setSubjectGroups(data || []));


    // Load prefs
    getUser(userEmail).then(data => {
      if (data) {
        setPrefPrompt(data.prompt || '');
        setPrefFrequency(data.frequency || 'daily');
        setPrefScope(data.scope || 'federal');
        setPrefMinScore(data.min_relevance_score || 70);
        setPrefExpandedTopics(data.expanded_topics || []);
        setReviewedBills(data.review_bills || []);

        if (data.prompt) {
          fetchBills({ userPrompt: data.prompt, minScore: data.min_relevance_score, limit: 1 })
            .then(res => setMatchingInterests(res.total || 0));
        }
      }
    }).catch(e => console.log('No prefs found'));
  }, [userEmail]);

  useEffect(() => {
    if (activeTab === 'yesterday' || activeTab === 'recent' || activeTab === 'search' || activeTab === 'review') {
      loadBills(activeTab);
    }
  }, [activeTab]);

  const loadBillsRef = useRef(null);
  loadBillsRef.current = async (tab) => {
    setLoading(true);
    try {
      let params = { limit: 20, sortBy: 'last_action_date', order: 'desc' };

      if (tab === 'yesterday') {
        params.fromActionDate = TWO_DAYS_AGO_ISO;
        params.toActionDate = YESTERDAY_ISO;
      } else if (tab === 'recent') {
        params.limit = 40;
      } else if (tab === 'review') {
        if (!userEmail) { setBills([]); setLoading(false); return; }
        const data = await fetchReviewBills(userEmail);
        setBills(data.results || []);
        setIsFallback(false);
        setLoading(false);
        return;
      } else if (tab === 'search') {
        if (!filtersApplied) {
          setBills([]); setIsFallback(false); setLoading(false); return;
        }
        params.limit = 500;
        if (filterKeyword.trim()) params.keyword = filterKeyword.trim();
        if (filterSubject) params.subject = filterSubject;
        if (filterBillType) params.billType = filterBillType;
        if (filterDateFrom) params.fromActionDate = filterDateFrom;
        if (filterDateTo) params.toActionDate = filterDateTo;
        if (filterByPrompt && prefPrompt) {
          params.userPrompt = prefPrompt;
          params.minScore = prefMinScore;
        }
      }


      const data = await fetchBills(params);
      let results = data.results || [];

      if (tab === 'search' && filterChamber) {
        results = results.filter(b => (b.origin_chamber || 'House').toLowerCase() === filterChamber.toLowerCase());
      }

      setBills(results);
      setIsFallback(false);

      if (tab === 'yesterday') setYesterdayCount(data.total || 0);
    } catch (err) {
      setBills([]);
    } finally {
      setLoading(false);
    }
  };

  const loadBills = useCallback((tab) => loadBillsRef.current(tab), []);

  const handleTabClick = (tab) => {
    setActiveTab(tab);
    setSearchFiltersOpen(tab === 'search');
    setShowPromptBanner(false);
    if (tab !== 'search') {
      setFiltersApplied(false);
      setFilterByPrompt(false);
    }
    if (tab === 'live') {
      setBills([]);
    }
  };

  const handleApplyFilters = () => {
    setFiltersApplied(true);
    setFilterByPrompt(false);
    setTimeout(() => loadBills('search'), 0);
  };

  const handleLiveSearch = async () => {
    if (!liveSearchInput.trim()) return;
    setLoading(true);
    setIsFallback(false);
    try {
      const data = await fetchLiveSearch(liveSearchInput, isLiveSearchDateEnabled ? selectedDate : null, userEmail);
      const sorted = (data.results || [])
        .slice()
        .sort((a, b) => (b.prompt_score ?? b.relevance_score ?? 0) - (a.prompt_score ?? a.relevance_score ?? 0))
        .filter(b => (b.prompt_score ?? b.relevance_score ?? 0) >= 30)
        .slice(0, 20);
      setBills(sorted);
      setLiveSearchTopics(data.prompt_expansion?.topics || []);
      setShowPromptBanner(true);
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
    }
  };
  
  const handleSavePrefs = async () => {
    try {
      const payload = {
        email: userEmail,
        prompt: prefPrompt,
        frequency: prefFrequency,
        scope: prefScope,
        min_relevance_score: parseInt(prefMinScore, 10) || 70
      };
      const res = await createUser(payload); // Overwrites/updates
      setPrefExpandedTopics(res.expanded_topics || []);
      setPrefStatus('Preferences saved successfully!');
      setTimeout(() => setPrefStatus(''), 3000);
      
      // Update matching interests based on new prompt
      if (res.prompt) {
        fetchBills({ userPrompt: res.prompt, minScore: res.min_relevance_score, limit: 1 })
          .then(r => setMatchingInterests(r.total || 0));
      }
    } catch (e) {
      setPrefStatus('Failed to save preferences.');
      setTimeout(() => setPrefStatus(''), 3000);
    }
  };
  
  const handleBookmarkToggle = async (e, bill) => {
    e.stopPropagation();
    if (!userEmail) return;
    const isBookmarked = reviewedBills.includes(bill.source_id);
    const updated = isBookmarked
      ? reviewedBills.filter(id => id !== bill.source_id)
      : [...reviewedBills, bill.source_id];
    setReviewedBills(updated);
    try {
      await updateUser(userEmail, { review_bills: updated });
      if (activeTab === 'review') loadBills('review');
    } catch (e) {
      setReviewedBills(reviewedBills); // revert on failure
    }
  };

  const handleBillClick = async (bill) => {
    setSelectedBill(bill);
    setModalTab('overview');
    try {
      const [details, actionsData] = await Promise.all([
        fetchBillDetails(bill.source_id),
        fetchBillActions(bill.source_id),
      ]);
      const actionHistory = (actionsData.actions || []).map(a => ({
        date: a.actionDate,
        text: a.text,
        source: a.actionCode || a.sourceSystem?.name || '',
      }));
      setSelectedBill({ ...details, action_history: actionHistory });
    } catch (err) {}
  };
  
  const runAiAnalysis = async () => {
    setAiLoading(true);
    try {
      await triggerAIProcess(selectedBill.source_id);
      const updated = await fetchBillDetails(selectedBill.source_id);
      setSelectedBill(prev => ({ ...prev, ...updated }));
    } catch (e) {
      alert('AI Analysis failed.');
    } finally {
      setAiLoading(false);
    }
  };

  const getProgressTracker = (bill) => {
    let currentStep = 1; 
    const isSenate = (bill.origin_chamber || 'House').toLowerCase() === 'senate';
    const hist = bill.action_history || [];
    const passedHouse = hist.some(a => (a.text||'').toLowerCase().includes('passed house') || (a.text||'').toLowerCase().includes('agreed to in house'));
    const passedSenate = hist.some(a => (a.text||'').toLowerCase().includes('passed senate') || (a.text||'').toLowerCase().includes('agreed to in senate'));
    const toPresident = hist.some(a => (a.text||'').toLowerCase().includes('presented to president'));
    const becameLaw = hist.some(a => (a.text||'').toLowerCase().includes('became public law') || (a.text||'').toLowerCase().includes('signed by president'));

    if (becameLaw) currentStep = 5;
    else if (toPresident) currentStep = 4;
    else if (passedHouse && passedSenate) currentStep = 3;
    else if (isSenate && passedSenate) currentStep = 2;
    else if (!isSenate && passedHouse) currentStep = 2;

    return {
      currentStep,
      labels: [
        'INTRODUCED',
        isSenate ? 'PASSED SENATE' : 'PASSED HOUSE',
        isSenate ? 'PASSED HOUSE' : 'PASSED SENATE',
        'TO PRESIDENT',
        'BECAME LAW'
      ]
    };
  };

  return (
    <div className="dashboard-container">
      <div className="app-container">

        {/* ── Header ─────────────────────────────────────────────────────────── */}
        <header className="app-header">
          <div className="brand">
            <div className="logo-icon"><i className="fa-solid fa-shield-cat"></i></div>
            <div className="brand-text">
              <h1>Animal Legislation Tracker</h1>
              <span className="badge-label">ALDF Ingestion Module</span>
            </div>
          </div>
          <div className="header-right" style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
            <ThemeToggle theme={theme} toggleTheme={toggleTheme} />
            <div className="user-menu-container" style={{ position: 'relative' }}>
              <button 
                className="btn btn-user" 
                onClick={() => setUserMenuOpen(!userMenuOpen)}
              >
                <i className="fa-solid fa-user"></i>
              </button>

              {userMenuOpen && (
                <>
                  <div className="user-menu-backdrop" onClick={() => setUserMenuOpen(false)}></div>
                  <div className="user-menu-dropdown">
                    <div className="user-menu-email">{userEmail}</div>
                    <button className="user-menu-item" onClick={onLogout}>
                      <i className="fa-solid fa-right-from-bracket"></i> Sign out
                    </button>
                  </div>
                </>
              )}
            </div>
          </div>
        </header>

        {/* ── Stats Strip ────────────────────────────────────────────────────── */}
        <section className="stats-strip">
          <div className="stat-card" style={{cursor: 'pointer'}} onClick={() => handleTabClick('yesterday')}>
            <div className="stat-icon" style={{color: '#f59e0b'}}><i className="fa-solid fa-bolt"></i></div>
            <div className="stat-content">
              <p className="stat-label">Bills Tracked Today</p>
              <h3 className="stat-value">{yesterdayCount}</h3>
              <p className="stat-subtext">New legislative actions</p>
            </div>
          </div>
          <div className="stat-card" style={{cursor: 'pointer'}} onClick={() => { handleTabClick('search'); setFilterKeyword(''); setFilterSubject(''); setFilterChamber(''); setFilterBillType(''); setFilterDateFrom(''); setFilterDateTo(''); setFilterByPrompt(false); setFiltersApplied(true); setTimeout(() => loadBills('search'), 0); }}>
            <div className="stat-icon" style={{color: 'var(--c-teal-bright)'}}><i className="fa-solid fa-folder-open"></i></div>
            <div className="stat-content">
              <p className="stat-label">Total Active Bills</p>
              <h3 className="stat-value">{totalBills}</h3>
              <p className="stat-subtext">Stored in database</p>
            </div>
          </div>
          <div className="stat-card" style={{cursor: 'pointer'}} onClick={() => { handleTabClick('search'); setFilterKeyword(''); setFilterSubject(''); setFilterChamber(''); setFilterBillType(''); setFilterDateFrom(''); setFilterDateTo(''); setFilterByPrompt(true); setFiltersApplied(true); setTimeout(() => loadBills('search'), 0); }}>
            <div className="stat-icon" style={{color: '#8b5cf6'}}><i className="fa-solid fa-tags"></i></div>
            <div className="stat-content">
              <p className="stat-label">Matching Your Interests</p>
              <h3 className="stat-value">{matchingInterests}</h3>
              <p className="stat-subtext">Based on your prompt</p>
            </div>
          </div>
          <div className="stat-card" style={{cursor: 'pointer'}} onClick={() => handleTabClick('review')}>
            <div className="stat-icon" style={{color: '#ef4444'}}><i className="fa-solid fa-circle-exclamation"></i></div>
            <div className="stat-content">
              <p className="stat-label">Requiring Review</p>
              <h3 className="stat-value">{reviewedBills.length}</h3>
              <p className="stat-subtext">High relevance, unreviewed</p>
            </div>
          </div>
        </section>

        {/* ── Main Content ───────────────────────────────────────────────────── */}
        <main className="content-section">
          <div className="control-panel">
            <div className="tabs-container">
              <button className={`tab-btn ${activeTab === 'yesterday' ? 'active' : ''}`} onClick={() => handleTabClick('yesterday')}>
                <i className="fa-solid fa-calendar-day"></i> Yesterday
              </button>
              <button className={`tab-btn ${activeTab === 'recent' ? 'active' : ''}`} onClick={() => handleTabClick('recent')}>
                <i className="fa-solid fa-clock"></i> Recent
              </button>
              <button className={`tab-btn ${activeTab === 'search' ? 'active' : ''}`} onClick={() => handleTabClick('search')}>
                <i className="fa-solid fa-magnifying-glass"></i> Search
              </button>
              <button className={`tab-btn ${activeTab === 'review' ? 'active' : ''}`} onClick={() => handleTabClick('review')}>
                <i className="fa-solid fa-circle-exclamation"></i> Needs Review
              </button>
              <button className={`tab-btn ${activeTab === 'live' ? 'active' : ''}`} onClick={() => handleTabClick('live')}>
                <i className="fa-solid fa-bolt-lightning"></i> Live Search
              </button>
              <button className={`tab-btn ${activeTab === 'prefs' ? 'active' : ''}`} onClick={() => handleTabClick('prefs')}>
                <i className="fa-solid fa-sliders"></i> Preferences
              </button>
            </div>

            {/* Filters Dropdown */}
            {activeTab === 'search' && (
              <div className="filter-dropdown active">
                <div className="filter-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))' }}>
                  <div className="form-group">
                    <label>Keyword Search</label>
                    <div className="input-with-icon">
                      <i className="fa-solid fa-font"></i>
                      <input type="text" placeholder="Title, action text..." value={filterKeyword} onChange={e => setFilterKeyword(e.target.value)} />
                    </div>
                  </div>
                  <div className="form-group">
                    <label>Subject</label>
                    <div className="input-with-icon">
                      <i className="fa-solid fa-tag"></i>
                      <select value={filterSubject} onChange={e => setFilterSubject(e.target.value)}>
                        <option value="">All Subjects</option>
                        {subjectGroups.map(group => (
                          <optgroup key={group.category} label={group.category}>
                            {group.subjects.map(s => (
                              <option key={s.name} value={s.name}>{s.name}</option>
                            ))}
                          </optgroup>
                        ))}
                      </select>
                    </div>
                  </div>
                  <div className="form-group">
                    <label>Origin Chamber</label>
                    <div className="input-with-icon">
                      <i className="fa-solid fa-building-columns"></i>
                      <select value={filterChamber} onChange={e => setFilterChamber(e.target.value)}>
                        <option value="">All Chambers</option>
                        <option value="House">House</option>
                        <option value="Senate">Senate</option>
                      </select>
                    </div>
                  </div>
                  <div className="form-group">
                    <label>Bill Type</label>
                    <div className="input-with-icon">
                      <i className="fa-solid fa-file-lines"></i>
                      <select value={filterBillType} onChange={e => setFilterBillType(e.target.value)}>
                        <option value="">All Types</option>
                        <option value="HR">HR</option>
                        <option value="S">S</option>
                        <option value="HJRES">HJRES</option>
                        <option value="SJRES">SJRES</option>
                        <option value="HCONRES">HCONRES</option>
                        <option value="SCONRES">SCONRES</option>
                        <option value="HRES">HRES</option>
                        <option value="SRES">SRES</option>
                      </select>
                    </div>
                  </div>
                  <div className="form-group">
                    <label>From Date</label>
                    <div className="input-with-icon">
                      <i className="fa-solid fa-calendar-days" style={{pointerEvents: 'auto', cursor: 'pointer'}} onClick={e => e.target.nextElementSibling?.showPicker && e.target.nextElementSibling.showPicker()}></i>
                      <input type="date" value={filterDateFrom} onChange={e => setFilterDateFrom(e.target.value)} />
                    </div>
                  </div>
                  <div className="form-group">
                    <label>To Date</label>
                    <div className="input-with-icon">
                      <i className="fa-solid fa-calendar-days" style={{pointerEvents: 'auto', cursor: 'pointer'}} onClick={e => e.target.nextElementSibling?.showPicker && e.target.nextElementSibling.showPicker()}></i>
                      <input type="date" value={filterDateTo} onChange={e => setFilterDateTo(e.target.value)} />
                    </div>
                  </div>
                  <div className="form-group button-group" style={{gridColumn: '1 / -1', justifyContent: 'flex-end', marginTop: '0.5rem'}}>
                    <button className="btn btn-primary" onClick={handleApplyFilters} style={{padding: '0.6rem 1.5rem'}}><i className="fa-solid fa-filter"></i> Apply Filters</button>
                    <button className="btn btn-secondary" onClick={() => { setFilterKeyword(''); setFilterSubject(''); setFilterChamber(''); setFilterBillType(''); setFilterDateFrom(''); setFilterDateTo(''); setFiltersApplied(false); setBills([]); }} style={{padding: '0.6rem 1.5rem'}}><i className="fa-solid fa-rotate-left"></i> Reset</button>
                  </div>
                </div>
              </div>
            )}
          </div>
          
          {/* Live Search Panel */}
          {activeTab === 'live' && (
            <div className="panel-section visible" style={{marginBottom:'2rem'}}>
              <div className="prefs-header">
                  <h2><i className="fa-solid fa-satellite-dish"></i> Live Search</h2>
                  <p className="prefs-subtitle">Search Congress.gov directly for animal-related bills updated on a specific date matching your prompt.</p>
              </div>
              <div className="prefs-form">
                <div className="prefs-field">
                  <label>YOUR PROMPT</label>
                  <textarea rows="3" value={liveSearchInput} onChange={e=>setLiveSearchInput(e.target.value)} placeholder="e.g. factory farming, wildlife trafficking, animal testing"></textarea>
                </div>
                <div className="prefs-field" style={{maxWidth: '300px'}}>
                  <label style={{display:'flex', alignItems:'center', gap:'0.5rem', cursor:'pointer'}}>
                    <input type="checkbox" checked={isLiveSearchDateEnabled} onChange={e => setIsLiveSearchDateEnabled(e.target.checked)} style={{width:'1rem', height:'1rem', cursor:'pointer'}} />
                    Filter by action date
                  </label>
                  {isLiveSearchDateEnabled && (
                    <div className="input-with-icon" style={{marginTop:'0.5rem'}}>
                      <i className="fa-solid fa-calendar-days" style={{pointerEvents: 'auto', cursor: 'pointer'}} onClick={e => e.target.nextElementSibling?.showPicker && e.target.nextElementSibling.showPicker()}></i>
                      <input type="date" value={selectedDate} onChange={e => setSelectedDate(e.target.value)} />
                    </div>
                  )}
                </div>
                <div className="prefs-actions" style={{marginTop: '1.5rem'}}>
                  <button className="btn btn-primary" onClick={handleLiveSearch}><i className="fa-solid fa-magnifying-glass"></i> Search Live</button>
                </div>
              </div>
            </div>
          )}
          
          {/* Prompt Banner */}
          {showPromptBanner && (
            <div className="prompt-expansion-banner visible">
              <div className="peb-left">
                <i className="fa-solid fa-wand-magic-sparkles"></i>
                <span>Expanded prompt: <strong>"{liveSearchInput}"</strong></span>
              </div>
              <div className="peb-topics">
                {liveSearchTopics.map(t => <span key={t} className="peb-topic-pill">{t}</span>)}
              </div>
              <button className="peb-clear" onClick={() => setShowPromptBanner(false)}><i className="fa-solid fa-xmark"></i> Clear</button>
            </div>
          )}
          
          {/* Preferences Panel */}
          {activeTab === 'prefs' && (
            <div className="panel-section visible">
               <div className="prefs-header">
                  <h2><i className="fa-solid fa-sliders"></i> Tracking Preferences</h2>
                  <p className="prefs-subtitle">Configure what legislation you want to monitor. Your prompt is converted into structured tracking topics.</p>
              </div>
              <div className="prefs-form">
                  <div className="prefs-field">
                      <label>Your Email <span style={{color: 'var(--c-teal)'}}>*</span></label>
                      <div className="input-with-icon">
                        <i className="fa-solid fa-envelope"></i>
                        <input 
                           type="email" 
                           value={userEmail || ''} 
                           readOnly 
                           disabled 
                           style={{ opacity: 0.7, cursor: 'not-allowed' }} 
                        />
                      </div>
                  </div>
                  <div className="prefs-field">
                      <label>Tracking Prompt</label>
                      <p style={{fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-tertiary)', marginBottom: '0.5rem'}}>Describe what legislation you want to track. Examples: "Track farm animal welfare bills", "Track animal testing regulations".</p>
                      <textarea rows="3" value={prefPrompt} onChange={e=>setPrefPrompt(e.target.value)} placeholder="e.g. Track farm animal welfare bills and livestock protection legislation"></textarea>
                  </div>
                  <div className="prefs-row" style={{display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: '1rem'}}>
                      <div className="prefs-field">
                          <label>Digest Frequency</label>
                          <div className="input-with-icon">
                            <i className="fa-regular fa-calendar"></i>
                            <select value={prefFrequency} onChange={e=>setPrefFrequency(e.target.value)}>
                              <option value="daily">Daily</option>
                              <option value="weekly">Weekly</option>
                              <option value="realtime">Real-time</option>
                            </select>
                          </div>
                      </div>
                      <div className="prefs-field">
                          <label>Scope</label>
                          <div className="input-with-icon">
                            <i className="fa-solid fa-globe"></i>
                            <select value={prefScope} onChange={e=>setPrefScope(e.target.value)}>
                              <option value="federal">Federal</option>
                              <option value="state">State</option>
                              <option value="local">Local</option>
                            </select>
                          </div>
                      </div>
                      <div className="prefs-field">
                          <label>Minimum Relevance Score</label>
                          <div className="input-with-icon">
                            <i className="fa-solid fa-crosshairs"></i>
                            <input type="number" min="0" max="100" value={prefMinScore} onChange={e=>setPrefMinScore(e.target.value)} />
                          </div>
                          <p style={{fontFamily: 'var(--font-mono)', fontSize: '0.7rem', color: 'var(--text-tertiary)', marginTop: '0.5rem'}}>Bills scoring below this threshold are filtered out. Default: 70</p>
                      </div>
                  </div>
                  <div className="prefs-actions" style={{display:'flex', gap:'1rem', marginTop:'1.5rem'}}>
                      <button className="btn btn-primary" onClick={handleSavePrefs}><i className="fa-solid fa-floppy-disk"></i> Save Preferences</button>
                      <button className="btn btn-secondary" onClick={() => handleTabClick('search')}><i className="fa-solid fa-filter"></i> Apply to Current View</button>
                  </div>
                  {prefStatus && <div style={{marginTop:'1rem', color:'var(--c-teal)'}}>{prefStatus}</div>}
                  {prefExpandedTopics.length > 0 && (
                    <div style={{marginTop:'1.5rem'}}>
                      <label style={{fontFamily:'var(--font-mono)', fontSize:'0.72rem', color:'var(--text-secondary)'}}>AI EXPANDED TOPICS</label>
                      <div className="pill-container" style={{marginTop:'0.5rem'}}>
                        {prefExpandedTopics.map(t => <span key={t} className="subject-pill">{t}</span>)}
                      </div>
                    </div>
                  )}
              </div>
            </div>
          )}

          {/* Bills Feed */}
          {loading ? (
            <div style={{padding:'3rem', textAlign:'center', color:'var(--text-secondary)'}}><i className="fa-solid fa-spinner fa-spin"></i> Loading...</div>
          ) : activeTab !== 'prefs' && (
            <div>
              {bills.length === 0 && activeTab !== 'live' && (
                <div className="fallback-banner" style={{display:'flex'}}>
                  <i className="fa-solid fa-circle-info"></i>
                  <div className="fallback-text">
                    {activeTab === 'review' && !userEmail
                      ? <><strong>Sign in to use the review list.</strong><span>Log in to bookmark bills for review.</span></>
                      : activeTab === 'review'
                        ? <><strong>No bills in your review list.</strong><span>Click the <i className="fa-regular fa-bookmark"></i> icon on any bill to add it here.</span></>
                        : <><strong>No actions found.</strong><span>No legislative actions match your criteria.</span></>
                    }
                  </div>
                </div>
              )}
              
              <div className="bills-feed">
                {bills.map((bill, index) => {
                  const chamber = bill.origin_chamber?.toLowerCase() || 'house';
                  const stageClass = bill.current_stage?.toLowerCase().includes('signed') || bill.current_stage?.toLowerCase().includes('passed') ? 'passed' : bill.current_stage?.toLowerCase().includes('fail') ? 'failed' : '';
                  const allSubjects = bill.subjects?.flatMap(s => s.split(',').map(str => str.trim())).filter(Boolean) || [];
                  const displayScore = activeTab === 'live' ? (bill.prompt_score ?? bill.relevance_score) : bill.relevance_score;
                  const scoreLabel = activeTab === 'live' ? 'Relevance' : 'AI Score';

                  return (
                    <div key={bill.id || bill.source_id}>
                      <div className={`bill-card ${chamber}`} onClick={() => handleBillClick(bill)}>
                        <div className="bill-card-top">
                          <div className="bill-card-meta">
                            <div className="card-header">
                              <span className={`chamber-badge ${chamber}`}>{bill.origin_chamber}</span>
                              <span className="bill-id">{bill.source_id}</span>
                              <span className="bill-policy-area">{bill.policy_area}</span>
                            </div>
                            <h3 className="bill-title" title={bill.title}>{bill.title}</h3>
                            <div className="bill-sponsor">
                              <i className="fa-solid fa-user-tie"></i>
                              <span>{bill.sponsor_name ? `Sponsor: ${bill.sponsor_name}` : 'Sponsor: N/A'}</span>
                            </div>
                          </div>
                          <div className="bill-card-right">
                            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.25rem' }}>
                              {userEmail && (
                                <button
                                  onClick={(e) => handleBookmarkToggle(e, bill)}
                                  title={reviewedBills.includes(bill.source_id) ? 'Remove from review list' : 'Add to review list'}
                                  style={{ background: 'none', border: 'none', cursor: 'pointer', padding: '0.2rem 0.4rem', color: reviewedBills.includes(bill.source_id) ? '#ef4444' : 'var(--text-tertiary)', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '0.3rem' }}
                                >
                                  <i className={reviewedBills.includes(bill.source_id) ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark'}></i>
                                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: '0.7rem' }}>
                                    {reviewedBills.includes(bill.source_id) ? 'Reviewing' : 'Add for Review'}
                                  </span>
                                </button>
                              )}
                              {(displayScore !== null && displayScore !== undefined) && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: '0.4rem', padding: '0.2rem 0.5rem', background: 'rgba(0,0,0,0.2)', borderRadius: '4px', border: `1px solid ${displayScore >= 70 ? 'var(--c-teal)' : displayScore >= 40 ? '#f59e0b' : '#ef4444'}` }}>
                                  <i className="fa-solid fa-brain" style={{color: 'var(--c-teal)', fontSize: '0.7rem'}}></i>
                                  <span style={{fontFamily: 'var(--font-mono)', fontSize: '0.75rem', fontWeight: 'bold', color: displayScore >= 70 ? 'var(--c-teal-bright)' : displayScore >= 40 ? '#f59e0b' : '#ef4444'}}>
                                    {scoreLabel}: {displayScore}
                                  </span>
                                </div>
                              )}
                            </div>
                            <span className={`card-stage ${stageClass}`}>{bill.current_stage}</span>
                            <span className="card-more">Details <i className="fa-solid fa-arrow-right"></i></span>
                          </div>
                        </div>
                        <div className="bill-card-bottom">
                          <div className="card-action-block">
                            <div className="action-header">
                              <span className="action-title">LATEST ACTION</span>
                              <span className="action-time">{formatDisplayDate(bill.last_action_date)}</span>
                            </div>
                            <p className="action-text">{bill.last_action_text}</p>
                          </div>
                          <div className="pill-container">
                            {allSubjects.slice(0, 3).map((s, i) => <span key={i} className="subject-pill">{s}</span>)}
                            {allSubjects.length > 3 && <span className="subject-pill">+{allSubjects.length - 3} more</span>}
                          </div>
                        </div>
                      </div>
                      {index < bills.length - 1 && <div className="bill-divider"></div>}
                    </div>
                  );
                })}
              </div>
              
              {/* Exports */}
              <div style={{ textAlign: 'center', marginTop: '2rem' }}>
                <p style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', color: 'var(--text-tertiary)', marginBottom: '0.5rem', textTransform: 'uppercase' }}>Export Current View</p>
                <div style={{ display: 'flex', gap: '1rem', justifyContent: 'center' }}>
                    <a href={import.meta.env.PROD ? "/export/csv" : "/api/export/csv"} className="btn btn-secondary"><i className="fa-solid fa-file-csv"></i> CSV</a>
                    <a href={import.meta.env.PROD ? "/export/json" : "/api/export/json"} className="btn btn-secondary"><i className="fa-solid fa-code"></i> JSON</a>
                </div>
              </div>
            </div>
          )}
        </main>
      </div>

      {/* ── Detail Modal ──────────────────────────────────────────────────────── */}
      {selectedBill && (
        <div className="modal-overlay active" onClick={e => e.target.classList.contains('modal-overlay') && setSelectedBill(null)}>
          <div className="modal-container detail-modal-new">
            <button className="modal-close-btn" onClick={() => setSelectedBill(null)}>
              <i className="fa-solid fa-xmark"></i>
            </button>

            {/* Title */}
            <div className="modal-header-new">
              <h2 className="modal-title-new">{selectedBill.title}</h2>
            </div>

            {/* Tabs */}
            <div className="modal-tabs" style={{ display: 'flex', gap: '1rem', padding: '0 2rem', borderBottom: '1px solid var(--border-color)' }}>
              {[['overview', 'Overview'], ['ai', 'AI Analysis'], ['history', 'Action History']].map(([key, label]) => (
                <button
                  key={key}
                  style={{ background: 'none', border: 'none', padding: '0.75rem 1rem', color: modalTab === key ? 'var(--c-teal)' : 'var(--text-secondary)', borderBottom: modalTab === key ? '2px solid var(--c-teal)' : '2px solid transparent', cursor: 'pointer', fontWeight: '600' }}
                  onClick={() => setModalTab(key)}
                >{label}</button>
              ))}
            </div>

            <div className="modal-body-new">

              {/* ── Overview Tab ── */}
              {modalTab === 'overview' && (
                <>
                  {/* Bill Information */}
                  <div className="modal-section-new">
                    <h4 className="section-title-new">Bill Information</h4>
                    <div className="metadata-grid-new">
                      <div className="meta-row-new">
                        <span className="meta-key-new">Congress</span>
                        <span className="meta-value-new">{selectedBill.congress}th Congress</span>
                      </div>
                      <div className="meta-row-new">
                        <span className="meta-key-new">Introduced Date</span>
                        <span className="meta-value-new">{formatDisplayDate(selectedBill.introduced_date)}</span>
                      </div>
                      <div className="meta-row-new">
                        <span className="meta-key-new">Sponsor</span>
                        <span className="meta-value-new">{selectedBill.sponsor_name || 'N/A'}</span>
                      </div>
                      <div className="meta-row-new">
                        <span className="meta-key-new">Policy Area</span>
                        <span className="meta-value-new">{selectedBill.policy_area || 'N/A'}</span>
                      </div>
                      <div className="meta-row-new">
                        <span className="meta-key-new">Current Stage</span>
                        <span className="meta-value-new">{selectedBill.current_stage || 'N/A'}</span>
                      </div>
                    </div>
                  </div>

                  {/* Matched Subjects */}
                  {selectedBill.subjects?.length > 0 && (
                    <div className="modal-section-new">
                      <h4 className="section-title-new">Matched Subjects</h4>
                      <ul style={{ margin: 0, padding: 0, listStyle: 'none', display: 'flex', flexDirection: 'column', gap: '0.4rem' }}>
                        {selectedBill.subjects.map(s => (
                          <li key={s} style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', color: 'var(--text-primary)', fontSize: '0.9rem' }}>
                            <i className="fa-solid fa-circle-dot" style={{ color: 'var(--c-teal)', fontSize: '0.5rem' }}></i>
                            {s}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}

                  {/* Latest Legislative Action */}
                  <div className="modal-section-new">
                    <h4 className="section-title-new">Latest Legislative Action</h4>
                    <div style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: '0.8rem', marginBottom: '0.5rem' }}>
                      {formatDisplayDate(selectedBill.last_action_date)}
                    </div>
                    <p style={{ color: 'var(--text-primary)', lineHeight: '1.6', margin: '0 0 1.25rem 0' }}>
                      {selectedBill.last_action_text}
                    </p>
                    {selectedBill.source_url && (
                      <a href={selectedBill.source_url} target="_blank" rel="noreferrer" className="btn btn-secondary" style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', fontSize: '0.85rem' }}>
                        <i className="fa-solid fa-arrow-up-right-from-square"></i> Open in Congress.gov
                      </a>
                    )}
                  </div>
                </>
              )}

              {/* ── AI Analysis Tab ── */}
              {modalTab === 'ai' && (
                <div className="modal-section-new">
                  <h4 className="section-title-new">AI INTELLIGENCE REPORT</h4>
                  {aiLoading ? (
                    <div style={{ padding: '2rem', textAlign: 'center' }}><i className="fa-solid fa-spinner fa-spin"></i> Analyzing bill text...</div>
                  ) : !selectedBill.ai_generated_at ? (
                    <div style={{ padding: '2rem', textAlign: 'center', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                      <i className="fa-solid fa-brain" style={{ fontSize: '2rem', color: 'var(--c-teal)', marginBottom: '1rem', display: 'block' }}></i>
                      <p style={{ marginBottom: '1rem' }}>This bill hasn't been analyzed by our AI engine yet.</p>
                      <button className="btn btn-primary" onClick={runAiAnalysis}><i className="fa-solid fa-wand-magic-sparkles"></i> Run Full Analysis</button>
                    </div>
                  ) : (
                    <div>
                      <div style={{ display: 'flex', gap: '1.5rem', alignItems: 'center', marginBottom: '1.5rem' }}>
                        <div className={`ai-score-circle ${selectedBill.relevance_score >= 70 ? 'score-high' : selectedBill.relevance_score >= 40 ? 'score-mid' : 'score-low'}`} style={{ width: '60px', height: '60px', borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.5rem', fontWeight: '700', background: 'var(--bg-secondary)' }}>
                          {selectedBill.relevance_score}
                        </div>
                        <div>
                          <div style={{ fontFamily: 'var(--font-mono)', fontSize: '0.75rem', textTransform: 'uppercase', color: 'var(--text-secondary)' }}>Animal Relevance Score</div>
                          <div style={{ fontWeight: 'bold', color: 'var(--c-teal)' }}>{selectedBill.relevance_score >= 70 ? 'High Relevance' : 'Moderate Relevance'}</div>
                        </div>
                      </div>
                      <div style={{ marginBottom: '1.5rem' }}>
                        <h4 style={{ fontSize: '0.9rem', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Extracted Topics</h4>
                        <div className="pill-container">
                          {(selectedBill.relevance_topics || []).map(t => <span key={t} className="subject-pill">{t}</span>)}
                        </div>
                      </div>
                      <div style={{ marginBottom: '1.5rem' }}>
                        <h4 style={{ fontSize: '0.9rem', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Rationale</h4>
                        <p style={{ color: 'var(--text-primary)', lineHeight: '1.5' }}>{selectedBill.relevance_rationale}</p>
                      </div>
                      <div>
                        <h4 style={{ fontSize: '0.9rem', marginBottom: '0.5rem', color: 'var(--text-secondary)' }}>Summary</h4>
                        <p style={{ color: 'var(--text-primary)', lineHeight: '1.5' }}>{selectedBill.ai_summary}</p>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* ── Action History Tab ── */}
              {modalTab === 'history' && (
                <div className="modal-section-new">
                  <h4 className="section-title-new">ACTION HISTORY</h4>
                  <div className="action-history-list">
                    {(selectedBill.action_history?.length > 0 ? selectedBill.action_history : [{ date: selectedBill.last_action_date, text: selectedBill.last_action_text, source: selectedBill.origin_chamber }]).map((item, i) => (
                      <div key={i} className="history-item">
                        <div className="history-dot"></div>
                        <div className="history-content">
                          <div className="history-date">{formatDisplayDate(item.date)}</div>
                          <div className="history-desc">{item.text}</div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

            </div>
          </div>
        </div>
      )}
    </div>
  );
}

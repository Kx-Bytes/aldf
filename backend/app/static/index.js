document.addEventListener('DOMContentLoaded', () => {
    const today = new Date();
    const formatDateString = (d) => {
        return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
    };
    const yesterday = new Date(today);
    yesterday.setDate(today.getDate() - 1);
    const yesterdayStr = formatDateString(yesterday);

    // DOM refs — stats
    const currentDateEl = document.getElementById('current-date');
    const valYesterdayEl = document.getElementById('val-yesterday');
    const valTotalEl = document.getElementById('val-total');
    const valMatchingEl = document.getElementById('val-matching');
    const valReviewEl = document.getElementById('val-review');

    // DOM refs — feed
    const loaderEl = document.getElementById('loader');
    const billsListContainer = document.getElementById('bills-list-container');
    const emptyStateEl = document.getElementById('empty-state');
    const emptyTextEl = document.getElementById('empty-text');
    const tabButtons = document.querySelectorAll('.tab-btn');
    const searchFilterPanel = document.getElementById('search-filter-panel');
    const filterForm = document.getElementById('filter-form');
    const filterKeyword = document.getElementById('filter-keyword');
    const filterSubject = document.getElementById('filter-subject');
    const filterChamber = document.getElementById('filter-chamber');
    const filterBillType = document.getElementById('filter-billtype');
    const btnResetFilters = document.getElementById('btn-reset-filters');
    const btnSyncTrigger = document.getElementById('btn-sync-trigger');
    const alertBanner = document.getElementById('alert-banner');
    const alertText = document.getElementById('alert-text');
    const preferencesPanel = document.getElementById('preferences-panel');
    const livesearchPanel = document.getElementById('livesearch-panel');
    const paginationControls = document.getElementById('pagination-controls');

    // DOM refs — prompt expansion banner
    const promptBanner = document.getElementById('prompt-expansion-banner');
    const pebPromptText = document.getElementById('peb-prompt-text');
    const pebTopics = document.getElementById('peb-topics');
    const pebClear = document.getElementById('peb-clear');

    // DOM refs — preferences form
    const prefsForm = document.getElementById('prefs-form');
    const prefsEmail = document.getElementById('prefs-email');
    const prefsPrompt = document.getElementById('prefs-prompt');
    const prefsFrequency = document.getElementById('prefs-frequency');
    const prefsScope = document.getElementById('prefs-scope');
    const prefsMinScore = document.getElementById('prefs-min-score');
    const btnApplyPrompt = document.getElementById('btn-apply-prompt');
    const prefsSaveStatus = document.getElementById('prefs-save-status');
    const prefsExpandedTopics = document.getElementById('prefs-expanded-topics');
    const prefsTopicsPills = document.getElementById('prefs-topics-pills');

    // DOM refs — modal
    const detailModal = document.getElementById('detail-modal');
    const modalClose = document.getElementById('modal-close');
    const modalChamber = document.getElementById('modal-chamber');
    const modalBillId = document.getElementById('modal-bill-id');
    const modalBillTitle = document.getElementById('modal-bill-title');
    const modalCongress = document.getElementById('modal-congress');
    const modalIntroduced = document.getElementById('modal-introduced');
    const modalSponsor = document.getElementById('modal-sponsor');
    const modalPolicyArea = document.getElementById('modal-policy-area');
    const modalStage = document.getElementById('modal-stage');
    const modalSubjectsList = document.getElementById('modal-subjects-list');
    const modalActionDate = document.getElementById('modal-action-date');
    const modalActionDesc = document.getElementById('modal-action-desc');
    const modalExternalLink = document.getElementById('modal-external-link');
    const modalJsonBlock = document.getElementById('modal-json-block');
    const modalActionTimeline = document.getElementById('modal-action-timeline');
    const aiPanelContent = document.getElementById('ai-panel-content');
    const modalTabButtons = document.querySelectorAll('.modal-tab-btn');
    const modalContentPanels = document.querySelectorAll('.modal-content-panel');

    // State
    let currentTab = 'yesterday';
    let currentPage = 1;
    const limit = 40;
    let activeUserPrompt = localStorage.getItem('aldf_user_prompt') || '';
    let activeUserEmail = localStorage.getItem('aldf_user_email') || '';
    let activeMinScore = parseInt(localStorage.getItem('aldf_min_score') || '0', 10);
    let lastPromptExpansion = null;

    currentDateEl.textContent = today.toLocaleDateString('en-US', { weekday:'long', year:'numeric', month:'long', day:'numeric' });

    // Restore saved preferences into form
    if (activeUserEmail) prefsEmail.value = activeUserEmail;
    if (activeUserPrompt) prefsPrompt.value = activeUserPrompt;
    if (activeMinScore) prefsMinScore.value = activeMinScore;

    init();

    async function init() {
        showLoader(true);
        await loadOverviewStats();
        await loadSubjectsDropdown();
        await loadBillsFeed();
        showLoader(false);
        showPromptBannerIfActive();
    }

    // ── Stats ──────────────────────────────────────────────────────────────
    async function loadOverviewStats() {
        try {
            const [yesterdayRes, overviewRes] = await Promise.all([
                fetch(`/documents/search?from_action_date=${yesterdayStr}&to_action_date=${yesterdayStr}&limit=1`),
                fetch('/stats/overview')
            ]);
            const yesterdayData = await yesterdayRes.json();
            const overviewData = await overviewRes.json();

            valYesterdayEl.textContent = yesterdayData.total || 0;
            valTotalEl.textContent = overviewData.total_active_bills || 0;

            // "Matching your interests" — count bills above min_score threshold
            const matchingRes = await fetch(`/documents/search?limit=1${activeUserPrompt ? `&user_prompt=${encodeURIComponent(activeUserPrompt)}&user_email=${encodeURIComponent(activeUserEmail)}&min_score=${activeMinScore || 0}` : ''}`);
            const matchingData = await matchingRes.json();
            valMatchingEl.textContent = activeUserPrompt ? matchingData.total : overviewData.total_active_bills;

            // "Requiring review" — high relevance score bills (>=80) 
            const reviewRes = await fetch('/documents/search?limit=1&sort_by=last_action_date');
            const reviewData = await reviewRes.json();
            const highScore = (reviewData.results || []).filter(r => (r.relevance_score || 0) >= 80).length;
            valReviewEl.textContent = highScore;
        } catch (err) {
            console.error("Stats load error:", err);
            [valYesterdayEl, valTotalEl, valMatchingEl, valReviewEl].forEach(el => el.textContent = '-');
        }
    }

    async function loadSubjectsDropdown() {
        try {
            const res = await fetch('/subjects');
            const subjects = await res.json();
            filterSubject.innerHTML = '<option value="">All Subjects</option>';
            subjects.forEach(sub => {
                const opt = document.createElement('option');
                opt.value = sub.name;
                opt.textContent = `${sub.name} (${sub.document_count})`;
                filterSubject.appendChild(opt);
            });
        } catch (err) { console.error("Subjects load error:", err); }
    }

    // ── Feed ───────────────────────────────────────────────────────────────
    async function loadBillsFeed() {
        showLoader(true);
        billsListContainer.innerHTML = '';
        emptyStateEl.style.display = 'none';

        let url = `/documents/search?order=desc&limit=${limit}`;

        if (currentTab === 'yesterday') {
            url += `&from_action_date=${yesterdayStr}&to_action_date=${yesterdayStr}&sort_by=last_action_date`;
        } else if (currentTab === 'recent') {
            url += '&sort_by=last_action_date';
        } else if (currentTab === 'search') {
            url += '&sort_by=last_action_date';
            if (filterKeyword.value.trim()) url += `&keyword=${encodeURIComponent(filterKeyword.value.trim())}`;
            if (filterSubject.value) url += `&subject=${encodeURIComponent(filterSubject.value)}`;
            if (filterBillType.value) url += `&bill_type=${encodeURIComponent(filterBillType.value)}`;
        }

        // Inject active user prompt on all tabs
        if (activeUserPrompt) {
            url += `&user_prompt=${encodeURIComponent(activeUserPrompt)}`;
            if (activeUserEmail) url += `&user_email=${encodeURIComponent(activeUserEmail)}`;
            if (activeMinScore) url += `&min_score=${activeMinScore}`;
        }

        try {
            const res = await fetch(url);
            const data = await res.json();

            // Show prompt expansion if present
            if (data.prompt_expansion) {
                lastPromptExpansion = data.prompt_expansion;
                showPromptBanner(activeUserPrompt, data.prompt_expansion);
            }

            const results = data.results || [];
            if (results.length === 0) {
                emptyStateEl.style.display = 'block';
                emptyTextEl.textContent = currentTab === 'yesterday'
                    ? "No animal legislation actions recorded yesterday. Check 'All Recent Actions' for other updates."
                    : "Try adjusting your search criteria or tracking preferences.";
            } else {
                renderBills(results);
            }
        } catch (err) {
            console.error("Feed load error:", err);
            emptyStateEl.style.display = 'block';
            emptyTextEl.textContent = "Failed to connect to the backend. Please verify the API is running.";
        } finally {
            showLoader(false);
        }
    }

    // ── Render ─────────────────────────────────────────────────────────────
    function renderBills(bills) {
        bills.forEach(bill => {
            const chamber = (bill.origin_chamber || 'house').toLowerCase();
            const card = document.createElement('div');
            card.className = `bill-card glass-panel ${chamber}`;

            const subjectPills = bill.subjects.slice(0, 3).map(s => `<span class="subject-pill">${s}</span>`).join('');
            const moreSubjects = bill.subjects.length > 3 ? `<span class="subject-pill">+${bill.subjects.length - 3} more</span>` : '';
            const sponsorStr = bill.sponsor_name
                ? `${bill.sponsor_name}${bill.sponsor_party ? ` [${bill.sponsor_party}]` : ''}${bill.sponsor_state ? `-${bill.sponsor_state}` : ''}`
                : 'Unknown Sponsor';

            const actionRelative = bill.last_action_date === yesterdayStr ? "YESTERDAY" : bill.last_action_date;

            // Show prompt_score when a prompt is active, otherwise relevance_score
            const displayScore = activeUserPrompt ? bill.prompt_score : bill.relevance_score;
            let scoreBadge = '';
            if (displayScore !== null && displayScore !== undefined) {
                const sc = displayScore >= 70 ? 'score-high' : displayScore >= 40 ? 'score-mid' : 'score-low';
                const label = activeUserPrompt ? 'Prompt Match' : 'Relevance';
                scoreBadge = `<span class="relevance-score-badge ${sc}" title="${label} Score">${displayScore}</span>`;
            }

            card.innerHTML = `
                <div class="card-header">
                    <span class="chamber-badge ${chamber}">${bill.origin_chamber || 'House'}</span>
                    <span class="bill-id">${bill.source_id}</span>
                    ${scoreBadge}
                </div>
                <h3 class="bill-title" title="${bill.title}">${bill.title || 'No Title Provided'}</h3>
                <div class="bill-sponsor"><i class="fa-solid fa-user-tie"></i><span>Sponsor: ${sponsorStr}</span></div>
                <div class="card-action-block">
                    <div class="action-header">
                        <span class="action-title">LATEST ACTION</span>
                        <span class="action-time">${actionRelative}</span>
                    </div>
                    <p class="action-text" title="${bill.last_action_text}">${bill.last_action_text || 'No actions logged'}</p>
                </div>
                <div class="pill-container" style="margin-bottom:1.25rem;">${subjectPills}${moreSubjects}</div>
                <div class="card-footer">
                    <span class="card-stage">${bill.current_stage || 'Introduced'}</span>
                    <span class="card-more">Details <i class="fa-solid fa-arrow-right"></i></span>
                </div>
            `;
            card.addEventListener('click', () => openBillDetails(bill.source_id));
            billsListContainer.appendChild(card);
        });
    }

    // ── Prompt banner ──────────────────────────────────────────────────────
    function showPromptBanner(prompt, expansion) {
        if (!prompt || !expansion) return;
        pebPromptText.textContent = `"${prompt}"`;
        pebTopics.innerHTML = (expansion.topics || []).map(t => `<span class="peb-topic-pill">${t}</span>`).join('');
        promptBanner.style.display = 'flex';
    }

    function showPromptBannerIfActive() {
        if (activeUserPrompt && lastPromptExpansion) showPromptBanner(activeUserPrompt, lastPromptExpansion);
        else if (activeUserPrompt) promptBanner.style.display = 'flex', pebPromptText.textContent = `"${activeUserPrompt}"`;
    }

    pebClear.addEventListener('click', () => {
        activeUserPrompt = '';
        activeUserEmail = '';
        activeMinScore = 0;
        localStorage.removeItem('aldf_user_prompt');
        localStorage.removeItem('aldf_user_email');
        localStorage.removeItem('aldf_min_score');
        promptBanner.style.display = 'none';
        prefsPrompt.value = '';
        loadBillsFeed();
        loadOverviewStats();
    });

    // ── Preferences form ───────────────────────────────────────────────────
    // Load profile from API if email is saved
    if (activeUserEmail) {
        fetch(`/users/${encodeURIComponent(activeUserEmail)}`)
            .then(r => r.ok ? r.json() : null)
            .then(profile => {
                if (!profile) return;
                prefsPrompt.value = profile.prompt || '';
                prefsFrequency.value = profile.frequency || 'daily';
                prefsScope.value = profile.scope || 'federal';
                prefsMinScore.value = profile.min_relevance_score ?? 70;
                if (profile.expanded_topics?.topics?.length) showExpandedTopicsInForm(profile.expanded_topics.topics);
            })
            .catch(() => {});
    }

    prefsForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = prefsEmail.value.trim().toLowerCase();
        const prompt = prefsPrompt.value.trim();
        if (!email) { showPrefsStatus('Email is required.', 'error'); return; }

        const body = {
            email,
            prompt,
            frequency: prefsFrequency.value,
            scope: prefsScope.value,
            min_relevance_score: parseInt(prefsMinScore.value || '70', 10),
        };

        try {
            const res = await fetch('/users', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
            if (!res.ok) throw new Error(await res.text());
            const profile = await res.json();

            // Persist to localStorage
            activeUserEmail = email;
            activeUserPrompt = prompt;
            activeMinScore = body.min_relevance_score;
            localStorage.setItem('aldf_user_email', email);
            localStorage.setItem('aldf_user_prompt', prompt);
            localStorage.setItem('aldf_min_score', String(activeMinScore));

            if (profile.expanded_topics?.topics?.length) showExpandedTopicsInForm(profile.expanded_topics.topics);
            showPrefsStatus('Preferences saved successfully!', 'success');
        } catch (err) {
            showPrefsStatus(`Failed to save: ${err.message}`, 'error');
        }
    });

    btnApplyPrompt.addEventListener('click', () => {
        const prompt = prefsPrompt.value.trim();
        const email = prefsEmail.value.trim().toLowerCase();
        if (!prompt) { showPrefsStatus('Enter a prompt first.', 'error'); return; }
        activeUserPrompt = prompt;
        activeUserEmail = email;
        activeMinScore = parseInt(prefsMinScore.value || '0', 10);
        localStorage.setItem('aldf_user_prompt', prompt);
        if (email) localStorage.setItem('aldf_user_email', email);
        localStorage.setItem('aldf_min_score', String(activeMinScore));

        // Switch to feed tab and reload
        switchToTab('yesterday');
        loadBillsFeed();
        loadOverviewStats();
    });

    function showExpandedTopicsInForm(topics) {
        prefsTopicsPills.innerHTML = topics.map(t => `<span class="subject-pill" style="background:rgba(139,92,246,0.12);border-color:rgba(139,92,246,0.3);color:#c084fc;">${t}</span>`).join('');
        prefsExpandedTopics.style.display = 'block';
    }

    function showPrefsStatus(msg, type) {
        prefsSaveStatus.textContent = msg;
        prefsSaveStatus.className = `prefs-save-status ${type}`;
        prefsSaveStatus.style.display = 'block';
        setTimeout(() => { prefsSaveStatus.style.display = 'none'; }, 4000);
    }

    // ── Live Search ────────────────────────────────────────────────────────
    const livesearchForm = document.getElementById('livesearch-form');
    const lsPromptEl = document.getElementById('ls-prompt');
    const lsDateEl = document.getElementById('ls-date');
    const lsLoader = document.getElementById('ls-loader');
    const lsResults = document.getElementById('ls-results');
    const lsEmpty = document.getElementById('ls-empty');
    const lsExpansionBanner = document.getElementById('ls-expansion-banner');
    const lsTopics = document.getElementById('ls-topics');

    // Default date to yesterday
    const lsDefault = new Date();
    lsDefault.setDate(lsDefault.getDate() - 1);
    lsDateEl.value = formatDateString(lsDefault);

    livesearchForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const prompt = lsPromptEl.value.trim();
        const date = lsDateEl.value;
        if (!prompt) { alert('Please enter a prompt.'); return; }
        if (!date) { alert('Please select a date.'); return; }

        lsLoader.style.display = 'flex';
        lsResults.innerHTML = '';
        lsEmpty.style.display = 'none';
        lsExpansionBanner.style.display = 'none';

        try {
            const res = await fetch('/search/live', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt, date, user_email: activeUserEmail || null })
            });
            if (!res.ok) throw new Error(await res.text());
            const data = await res.json();

            if (data.prompt_expansion?.topics?.length) {
                lsTopics.innerHTML = data.prompt_expansion.topics.map(t => `<span class="peb-topic-pill">${t}</span>`).join('');
                lsExpansionBanner.style.display = 'flex';
            }

            if (!data.results?.length) {
                lsEmpty.style.display = 'block';
            } else {
                data.results.forEach(bill => {
                    const chamber = (bill.origin_chamber || 'house').toLowerCase();
                    const card = document.createElement('div');
                    card.className = `bill-card glass-panel ${chamber}`;
                    const sc = bill.prompt_score >= 70 ? 'score-high' : bill.prompt_score >= 40 ? 'score-mid' : 'score-low';
                    const subjectPills = (bill.subjects || []).slice(0, 3).map(s => `<span class="subject-pill">${s}</span>`).join('');
                    card.innerHTML = `
                        <div class="card-header">
                            <span class="chamber-badge ${chamber}">${bill.origin_chamber || 'House'}</span>
                            <span class="bill-id">${bill.source_id}</span>
                            <span class="relevance-score-badge ${sc}" title="Prompt Match">${bill.prompt_score}</span>
                        </div>
                        <h3 class="bill-title" title="${bill.title}">${bill.title || 'No Title'}</h3>
                        <div class="card-action-block">
                            <div class="action-header">
                                <span class="action-title">LATEST ACTION</span>
                                <span class="action-time">${bill.last_action_date || ''}</span>
                            </div>
                            <p class="action-text">${bill.last_action_text || 'No actions logged'}</p>
                        </div>
                        <div class="pill-container" style="margin-bottom:1.25rem;">${subjectPills}</div>
                        <div class="card-footer">
                            <span class="card-stage">${bill.current_stage || 'Introduced'}</span>
                            <span class="card-more">View <i class="fa-solid fa-arrow-right"></i></span>
                        </div>
                    `;
                    card.addEventListener('click', () => openBillDetails(bill.source_id));
                    lsResults.appendChild(card);
                });
            }
        } catch (err) {
            lsEmpty.style.display = 'block';
            lsEmpty.querySelector('p').textContent = `Error: ${err.message}`;
        } finally {
            lsLoader.style.display = 'none';
        }
    });

    // ── Tabs ───────────────────────────────────────────────────────────────
    function switchToTab(tabName) {
        tabButtons.forEach(b => b.classList.toggle('active', b.getAttribute('data-tab') === tabName));
        currentTab = tabName;
        const isPrefs = tabName === 'preferences';
        const isLive = tabName === 'livesearch';
        const isFeed = !isPrefs && !isLive;
        preferencesPanel.style.display = isPrefs ? 'block' : 'none';
        livesearchPanel.style.display = isLive ? 'block' : 'none';
        billsListContainer.style.display = isFeed ? 'grid' : 'none';
        emptyStateEl.style.display = 'none';
        loaderEl.style.display = 'none';
        paginationControls.style.display = 'none';
        searchFilterPanel.classList.toggle('active', tabName === 'search');
        promptBanner.style.display = (isFeed && activeUserPrompt) ? 'flex' : 'none';
    }

    tabButtons.forEach(btn => {
        btn.addEventListener('click', async () => {
            const tabName = btn.getAttribute('data-tab');
            switchToTab(tabName);
            if (tabName !== 'preferences' && tabName !== 'livesearch') await loadBillsFeed();
        });
    });

    filterForm.addEventListener('submit', (e) => { e.preventDefault(); loadBillsFeed(); });
    btnResetFilters.addEventListener('click', () => { filterForm.reset(); setTimeout(loadBillsFeed, 50); });

    // ── Sync button ────────────────────────────────────────────────────────
    btnSyncTrigger.addEventListener('click', async () => {
        if (!confirm("Trigger incremental sync for the 119th Congress? Runs in background.")) return;
        try {
            const res = await fetch('/sync/backfill/119?limit_bills=100', { method: 'POST' });
            const data = await res.json();
            alertBanner.style.display = 'flex';
            alertText.textContent = data.message || "Backfill started in background.";
            setTimeout(async () => { await loadOverviewStats(); await loadBillsFeed(); alertBanner.style.display = 'none'; }, 5000);
        } catch (err) { alert("Failed to connect to backfill service."); }
    });

    // ── Loader helper ──────────────────────────────────────────────────────
    function showLoader(show) {
        loaderEl.style.display = show ? 'flex' : 'none';
        if (currentTab !== 'livesearch') {
            billsListContainer.style.display = show ? 'none' : 'grid';
        }
    }

    // ── Modal ──────────────────────────────────────────────────────────────
    async function openBillDetails(sourceId) {
        modalBillId.textContent = 'Loading...';
        modalBillTitle.textContent = '';
        modalSubjectsList.innerHTML = '';
        modalActionTimeline.innerHTML = '';
        aiPanelContent.innerHTML = '';
        modalJsonBlock.textContent = '{}';
        modalTabButtons.forEach(b => b.classList.remove('active'));
        modalTabButtons[0].classList.add('active');
        modalContentPanels.forEach(p => p.classList.remove('active'));
        modalContentPanels[0].classList.add('active');
        detailModal.classList.add('active');

        try {
            const res = await fetch(`/documents/${sourceId}`);
            if (!res.ok) throw new Error("Detail request failed.");
            const doc = await res.json();

            modalBillId.textContent = doc.source_id;
            modalBillTitle.textContent = doc.title || 'No Title';
            modalCongress.textContent = `${doc.congress}th Congress`;
            modalIntroduced.textContent = doc.introduced_date ? new Date(doc.introduced_date).toLocaleDateString('en-US', {year:'numeric',month:'long',day:'numeric'}) : 'Unknown';
            modalSponsor.textContent = doc.sponsor_name ? `${doc.sponsor_name}${doc.sponsor_party?` [${doc.sponsor_party}]`:''}${doc.sponsor_state?`-${doc.sponsor_state}`:''}` : 'Unknown';
            modalPolicyArea.textContent = doc.policy_area || 'None';
            modalStage.textContent = doc.current_stage || 'Introduced';
            modalChamber.textContent = doc.origin_chamber || 'House';
            modalChamber.className = `chamber-badge ${(doc.origin_chamber || 'house').toLowerCase()}`;

            modalSubjectsList.innerHTML = doc.subjects?.length
                ? doc.subjects.map(s => `<span class="subject-pill">${s}</span>`).join('')
                : '<span class="text-muted">No subjects tagged.</span>';

            modalActionDate.textContent = doc.last_action_date ? new Date(doc.last_action_date).toLocaleDateString('en-US', {year:'numeric',month:'long',day:'numeric'}) : '';
            modalActionDesc.textContent = doc.last_action_text || 'No actions logged';

            if (doc.source_url) { modalExternalLink.href = doc.source_url; modalExternalLink.style.display = 'inline-flex'; }
            else { modalExternalLink.style.display = 'none'; }

            // AI panel
            if (doc.relevance_score !== null && doc.relevance_score !== undefined) {
                const s = doc.relevance_score;
                const sc = s >= 70 ? 'score-high' : s >= 40 ? 'score-mid' : 'score-low';
                const pills = (doc.relevance_topics || []).map(t => `<span class="subject-pill">${t}</span>`).join('');
                aiPanelContent.innerHTML = `
                    <div class="ai-score-row">
                        <div class="ai-score-circle ${sc}">${s}</div>
                        <div class="ai-score-meta">
                            <p class="ai-score-label">Relevance Score</p>
                            <p class="ai-score-sublabel">${s>=70?'High':s>=40?'Moderate':'Low'} relevance to animal welfare / wildlife</p>
                        </div>
                    </div>
                    ${pills ? `<div class="ai-topics-row"><h4>Matched Topics</h4><div class="pill-container">${pills}</div></div>` : ''}
                    ${doc.relevance_rationale ? `<div class="ai-section"><h4>Rationale</h4><p class="ai-text">${doc.relevance_rationale}</p></div>` : ''}
                    ${doc.ai_summary ? `<div class="ai-section"><h4>Impact Summary</h4><p class="ai-text">${doc.ai_summary}</p></div>` : ''}
                    <p class="ai-generated-note">Generated ${doc.ai_generated_at ? new Date(doc.ai_generated_at).toLocaleString() : 'unknown'} &middot; Model: claude-sonnet-4.5</p>
                `;
            } else {
                aiPanelContent.innerHTML = `
                    <div class="ai-pending">
                        <i class="fa-solid fa-robot"></i>
                        <p>AI analysis has not been run for this bill yet.</p>
                        <button class="btn btn-primary" id="btn-run-ai" data-source-id="${doc.source_id}">
                            <i class="fa-solid fa-wand-magic-sparkles"></i> Run AI Analysis
                        </button>
                    </div>
                `;
                document.getElementById('btn-run-ai')?.addEventListener('click', async (e) => {
                    const sid = e.currentTarget.getAttribute('data-source-id');
                    e.currentTarget.disabled = true;
                    e.currentTarget.textContent = 'Running...';
                    try {
                        const r = await fetch(`/ai/process/${sid}`, { method: 'POST' });
                        if (!r.ok) throw new Error('API error');
                        const result = await r.json();
                        const s2 = result.relevance_score;
                        const sc2 = s2>=70?'score-high':s2>=40?'score-mid':'score-low';
                        const pills2 = (result.relevance_topics||[]).map(t=>`<span class="subject-pill">${t}</span>`).join('');
                        aiPanelContent.innerHTML = `
                            <div class="ai-score-row">
                                <div class="ai-score-circle ${sc2}">${s2}</div>
                                <div class="ai-score-meta">
                                    <p class="ai-score-label">Relevance Score</p>
                                    <p class="ai-score-sublabel">${s2>=70?'High':s2>=40?'Moderate':'Low'} relevance</p>
                                </div>
                            </div>
                            ${pills2?`<div class="ai-topics-row"><h4>Matched Topics</h4><div class="pill-container">${pills2}</div></div>`:''}
                            ${result.relevance_rationale?`<div class="ai-section"><h4>Rationale</h4><p class="ai-text">${result.relevance_rationale}</p></div>`:''}
                            ${result.ai_summary?`<div class="ai-section"><h4>Impact Summary</h4><p class="ai-text">${result.ai_summary}</p></div>`:''}
                            <p class="ai-generated-note">Generated just now &middot; Model: claude-sonnet-4.5</p>
                        `;
                    } catch { aiPanelContent.innerHTML = '<p class="ai-error">Failed to run AI analysis.</p>'; }
                });
            }

            modalJsonBlock.textContent = JSON.stringify(doc.api_raw || doc, null, 2);

            // Live action timeline
            modalActionTimeline.innerHTML = '<div class="timeline-item">Loading actions...</div>';
            fetch(`/documents/${doc.source_id}/actions`)
                .then(r => r.ok ? r.json() : Promise.reject())
                .then(data => {
                    const actions = data.actions || [];
                    modalActionTimeline.innerHTML = '';
                    if (actions.length) {
                        const latest = actions[0];
                        if (latest.actionDate) modalActionDate.textContent = new Date(latest.actionDate).toLocaleDateString('en-US',{year:'numeric',month:'long',day:'numeric'});
                        if (latest.text) modalActionDesc.textContent = latest.text;
                        actions.forEach(act => {
                            const item = document.createElement('div');
                            item.className = 'timeline-item';
                            item.innerHTML = `
                                <div class="timeline-date">${act.actionDate ? new Date(act.actionDate).toLocaleDateString('en-US',{year:'numeric',month:'long',day:'numeric'}) : ''}</div>
                                <div class="timeline-text">${act.text || ''}</div>
                            `;
                            modalActionTimeline.appendChild(item);
                        });
                    } else {
                        modalActionTimeline.innerHTML = '<div class="timeline-item">No actions recorded.</div>';
                    }
                })
                .catch(() => {
                    modalActionTimeline.innerHTML = `<div class="timeline-item"><div class="timeline-date">${doc.last_action_date || ''}</div><div class="timeline-text">${doc.last_action_text || 'No actions recorded.'}</div></div>`;
                });

        } catch (err) {
            console.error("Modal load error:", err);
            modalBillId.textContent = 'Error';
            modalBillTitle.textContent = 'Failed to load document details.';
        }
    }

    modalTabButtons.forEach(btn => {
        btn.addEventListener('click', () => {
            modalTabButtons.forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            const tabName = btn.getAttribute('data-modal-tab');
            modalContentPanels.forEach(p => { p.classList.remove('active'); if (p.id === `m-panel-${tabName}`) p.classList.add('active'); });
        });
    });

    modalClose.addEventListener('click', () => detailModal.classList.remove('active'));
    detailModal.addEventListener('click', (e) => { if (e.target === detailModal) detailModal.classList.remove('active'); });
});

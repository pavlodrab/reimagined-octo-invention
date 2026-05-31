/**
 * script.js  --  Chelsea Voting Mini App
 * 4 tabs + admin tab (visible only to admins)
 * Works both inside Telegram WebApp and in regular browser (demo mode)
 */

/* === HTML escaping helper === */
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/* ═══ Telegram WebApp (with fallback for local dev) ═══ */
const tg = window.Telegram?.WebApp;
if (tg) {
    tg.expand();
    tg.setHeaderColor('#034694');
    tg.setBackgroundColor('#0a1628');
}

/* ═══ Demo mode? ═══ */
const urlParams = new URLSearchParams(location.search);
const DEMO_MODE = !tg || urlParams.get('demo') === '1';
if (DEMO_MODE) {
    document.body.classList.add('demo-mode');
}

/* ═══ State ═══ */
const state = {
    userId: null,
    username: '',
    firstName: '',
    lastName: '',
    isAdmin: false,
    initData: '',
    demoUser: null,   // set in init() for demo mode

    // poll data
    currentPoll: null,
    players: [],         // [{id, name, number, position, photo_url}]
    ratings: {},         // player_id -> rating (number)
    usedRatings: new Set(),
    hasVoted: false,

    // config
    config: {
        max_rating: 10,
        voting_period_hours: 24,
        bot_name: 'Челси Голосование',
        default_background_url: '',
        auto_create_polls: '1',
        auto_close_polls: '1',
        auto_notify: '1',
        notify_chat_id: '',
    },

    // profiles
    myProfile: null,

    // polls list
    allPolls: [],

    // prediction
    myPrediction: null,

    // mini-games
    scoreGuess: null,
    lineupGuess: null,

    // server clock offset (server_time - client_time in seconds)
    serverTimeOffset: 0,

    // SSE connection
    sseConnection: null,
    liveVoterCount: 0,

    // match events and AI ratings
    matchEvents: {},    // player_id -> [{event_type, emoji, minute, detail}]
    aiRatings: [],      // [{player_id, sstats_rating, normalized_rating}]
    timelineVisible: false,

    // notification prefs
    notificationPrefs: null,

    // FPL data
    fplData: null,

    // admin
    allAdmins: [],
    allLogs: [],
    allBackgrounds: [],
};

/* ═══ Helpers ═══ */
function api(path, opts = {}) {
    const headers = { 'Content-Type': 'application/json' };
    if (state.initData) headers['X-Init-Data'] = state.initData;
    if (state.demoUser) headers['X-Demo-User'] = JSON.stringify(state.demoUser);
    return fetch(path, { ...opts, headers: { ...headers, ...(opts.headers || {}) } })
        .then(async r => {
            const text = await r.text();
            try { return JSON.parse(text); } catch { return { success: false, error: text }; }
        });
}

function toast(msg, duration = 3000) {
    const el = document.getElementById('toast');
    el.textContent = msg;
    // Force reflow before adding the visibility class so the slide+fade
    // animation always plays, even on rapid back-to-back toasts.
    el.style.display = 'block';
    el.classList.remove('toast-visible');
    // eslint-disable-next-line no-unused-expressions
    el.offsetHeight;
    el.classList.add('toast-visible');
    clearTimeout(window._toastTimer);
    window._toastTimer = setTimeout(() => {
        el.classList.remove('toast-visible');
        setTimeout(() => { el.style.display = 'none'; }, 350);
    }, duration);
}

function tsToDate(ts) {
    if (!ts) return '—';
    return new Date(ts * 1000).toLocaleString('ru-RU');
}

/* ═══ animateNumber: count-up tween for a single element ═══
 * Reads target from the element's text or an explicit `target` arg, animates
 * from 0 to target over `duration` ms with ease-out cubic. Respects
 * prefers-reduced-motion (snaps to final value immediately). */
function animateNumber(el, target, duration) {
    if (!el) return;
    if (target === undefined || target === null || target === '') {
        target = parseFloat(el.textContent.replace(/[^\d.-]/g, '')) || 0;
    }
    target = Number(target);
    if (!isFinite(target)) { el.textContent = '0'; return; }
    duration = duration || 800;
    var reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduced) { el.textContent = formatCounterValue(target); return; }
    var startTime = performance.now();
    var isInt = Number.isInteger(target);
    function tick(now) {
        var p = Math.min((now - startTime) / duration, 1);
        var ease = 1 - Math.pow(1 - p, 3);
        var v = target * ease;
        el.textContent = isInt ? Math.floor(v).toString() : v.toFixed(1);
        if (p < 1) requestAnimationFrame(tick);
        else el.textContent = formatCounterValue(target);
    }
    requestAnimationFrame(tick);
}
function formatCounterValue(n) {
    return Number.isInteger(n) ? String(n) : n.toFixed(1);
}
function animateAllCounters(root) {
    root = root || document;
    var nodes = root.querySelectorAll('[data-counter]');
    for (var i = 0; i < nodes.length; i++) {
        var el = nodes[i];
        if (el.dataset.counterDone === '1') continue;
        var target = parseFloat(el.dataset.counter);
        el.textContent = '0';
        animateNumber(el, target);
        el.dataset.counterDone = '1';
    }
}

/* ═══ Inline SVG icons (kept inline so we don't ship an extra file) ═══ */
const ICON_COPY = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>';

/* ═══ Chelsea-themed Avatars ═══ */
const AVATARS = [
    { emoji: '', bg: 'var(--blue)', label: 'Default' },
    { emoji: '\uD83E\uDD81', bg: 'var(--blue)', label: 'Lion' },
    { emoji: '\u26BD', bg: 'var(--gold)', label: 'Football' },
    { emoji: '\uD83C\uDFC6', bg: 'var(--gold)', label: 'Trophy' },
    { emoji: '\uD83D\uDEE1\uFE0F', bg: 'var(--blue)', label: 'Shield' },
    { emoji: '\u2B50', bg: '#1a1a2e', label: 'Star' },
    { emoji: '\uD83D\uDC51', bg: 'var(--gold)', label: 'Crown' },
    { emoji: '\u26A1', bg: 'var(--blue)', label: 'Lightning' },
    { emoji: '\uD83D\uDD25', bg: '#e65100', label: 'Fire' },
    { emoji: '\uD83D\uDC8E', bg: 'var(--blue-light)', label: 'Diamond' },
];

function getAvatarHtml(avatarIndex, size, photoUrl) {
    var s = size || 48;
    // Tier 1: real Telegram profile photo if we have a URL.
    if (photoUrl && typeof photoUrl === 'string' && photoUrl.length > 0) {
        // Quote-escape the URL to be safe inside an HTML attribute.
        var safe = String(photoUrl).replace(/"/g, '&quot;');
        return '<img class="tg-avatar" src="' + safe + '" ' +
               'style="width:' + s + 'px;height:' + s + 'px;border-radius:50%;object-fit:cover;display:block;" ' +
               'onerror="this.outerHTML=\'\\u003Cdiv style=&quot;width:' + s + 'px;height:' + s + 'px;border-radius:50%;background:var(--blue);color:#fff;display:flex;align-items:center;justify-content:center;font-size:' + Math.round(s * 0.4) + 'px;font-weight:700;&quot;\\u003E?\\u003C/div\\u003E\'">';
    }
    // Tier 2: chosen emoji avatar
    var idx = parseInt(avatarIndex) || 0;
    if (idx < 0 || idx >= AVATARS.length) idx = 0;
    var avatar = AVATARS[idx];
    var fontSize = Math.round(s * 0.55);
    if (idx === 0) {
        // Tier 3: initials placeholder (no Telegram photo, no chosen emoji)
        var initial = ((state.firstName || '?')[0] + ((state.lastName || '')[0] || '')).toUpperCase();
        return '<div style="width:' + s + 'px;height:' + s + 'px;border-radius:50%;background:' + avatar.bg + ';color:#fff;display:flex;align-items:center;justify-content:center;font-size:' + Math.round(s * 0.4) + 'px;font-weight:700;">' + initial + '</div>';
    }
    return '<div style="width:' + s + 'px;height:' + s + 'px;border-radius:50%;background:' + avatar.bg + ';display:flex;align-items:center;justify-content:center;font-size:' + fontSize + 'px;">' + avatar.emoji + '</div>';
}

/* ═══ Confetti Animation 2.0 ═══
 * Brand-weighted colors (more blue+gold than white), 4 shape variants,
 * randomized rotation, fall duration and lateral drift. CSS handles the
 * physics via custom properties (--drift, --spin, --fall-dur).            */
function launchConfetti() {
    var existing = document.getElementById('confetti-container');
    if (existing) existing.remove();
    var container = document.createElement('div');
    container.id = 'confetti-container';
    document.body.appendChild(container);

    // Brand-weighted palette: blue and gold appear ~3x as often as accents
    var palette = [
        '#034694','#034694','#034694',     // Chelsea blue
        '#DBA111','#DBA111','#DBA111',     // gold
        '#0563c1','#0563c1',               // light blue
        '#f0c040',                          // light gold
        '#ffffff'                           // white sparkles
    ];
    var shapes = ['shape-circle','shape-rect','shape-strip','shape-square','shape-circle'];
    var n = 70 + Math.floor(Math.random() * 25);

    for (var i = 0; i < n; i++) {
        var p = document.createElement('div');
        var shape = shapes[Math.floor(Math.random() * shapes.length)];
        p.className = 'confetti-particle ' + shape;
        var color = palette[Math.floor(Math.random() * palette.length)];
        var left = Math.random() * 100;
        var delay = Math.random() * 0.45;
        var drift = (Math.random() - 0.5) * 360 + 'px';
        var spin = (480 + Math.random() * 720) * (Math.random() > 0.5 ? 1 : -1) + 'deg';
        var dur = (2.4 + Math.random() * 1.6).toFixed(2) + 's';
        p.style.cssText =
            'left:' + left + '%;' +
            'background:' + color + ';' +
            'animation-delay:' + delay + 's;' +
            '--drift:' + drift + ';' +
            '--spin:' + spin + ';' +
            '--fall-dur:' + dur + ';';
        container.appendChild(p);
    }

    setTimeout(function() {
        var el = document.getElementById('confetti-container');
        if (el) el.remove();
    }, 4500);
}

/* ═══ Sound Effects (Web Audio API) ═══ */
var _audioCtx = null;
function getAudioCtx() {
    if (!_audioCtx) {
        try { _audioCtx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return null; }
    }
    return _audioCtx;
}

function playSound(type) {
    try {
        var soundsEnabled = localStorage.getItem('chelsea_sounds');
        if (soundsEnabled === '0' || soundsEnabled === 'false') return;
    } catch (e) { return; }

    var ctx = getAudioCtx();
    if (!ctx) return;

    if (ctx.state === 'suspended') {
        ctx.resume();
    }

    if (type === 'success') {
        var notes = [523.25, 659.25, 783.99]; // C5, E5, G5
        for (var i = 0; i < notes.length; i++) {
            (function(freq, idx) {
                var osc = ctx.createOscillator();
                var gain = ctx.createGain();
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.type = 'sine';
                osc.frequency.value = freq;
                gain.gain.value = 0.15;
                var start = ctx.currentTime + idx * 0.1;
                osc.start(start);
                gain.gain.exponentialRampToValueAtTime(0.001, start + 0.15);
                osc.stop(start + 0.15);
            })(notes[i], i);
        }
    } else if (type === 'click') {
        var bufferSize = ctx.sampleRate * 0.03;
        var buffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
        var data = buffer.getChannelData(0);
        for (var j = 0; j < bufferSize; j++) {
            data[j] = (Math.random() * 2 - 1) * 0.1;
        }
        var source = ctx.createBufferSource();
        source.buffer = buffer;
        var gainNode = ctx.createGain();
        source.connect(gainNode);
        gainNode.connect(ctx.destination);
        gainNode.gain.value = 0.1;
        source.start();
    } else if (type === 'error') {
        var errNotes = [392.0, 261.63]; // G4, C4
        for (var k = 0; k < errNotes.length; k++) {
            (function(freq, idx) {
                var osc = ctx.createOscillator();
                var gain = ctx.createGain();
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.type = 'sine';
                osc.frequency.value = freq;
                gain.gain.value = 0.15;
                var start = ctx.currentTime + idx * 0.12;
                osc.start(start);
                gain.gain.exponentialRampToValueAtTime(0.001, start + 0.15);
                osc.stop(start + 0.15);
            })(errNotes[k], k);
        }
    }
}

/* ═══ Demo data (fallback only - real data comes from the API) ═══ */
const DEMO_PLAYERS = [
    { id: 'p1',  name: 'Cole Palmer',      number: '20', position: 'MF', photo_url: 'https://resources.premierleague.com/premierleague/photos/players/250x250/p244851.png' },
    { id: 'p2',  name: 'Nicolas Jackson',  number: '15', position: 'FW', photo_url: 'https://resources.premierleague.com/premierleague/photos/players/250x250/p243557.png' },
    { id: 'p3',  name: 'Moisés Caicedo',   number: '25', position: 'MF', photo_url: 'https://resources.premierleague.com/premierleague/photos/players/250x250/p247632.png' },
    { id: 'p4',  name: 'Enzo Fernández',   number: '8',  position: 'MF', photo_url: 'https://resources.premierleague.com/premierleague/photos/players/250x250/p247632.png' },
    { id: 'p5',  name: 'Levi Colwill',     number: '26', position: 'DF', photo_url: 'https://resources.premierleague.com/premierleague/photos/players/250x250/p244851.png' },
    { id: 'p6',  name: 'Marc Cucurella',   number: '3',  position: 'DF', photo_url: '' },
    { id: 'p7',  name: 'Pedro Neto',      number: '7',  position: 'FW', photo_url: '' },
    { id: 'p8',  name: 'Robert Sánchez',   number: '1',  position: 'GK', photo_url: '' },
    { id: 'p9',  name: 'Wesley Fofana',    number: '33', position: 'DF', photo_url: '' },
    { id: 'p10', name: 'Noni Madueke',     number: '11', position: 'FW', photo_url: '' },
    { id: 'p11', name: 'Reece James',      number: '24', position: 'DF', photo_url: '' },
];

/* ═══ Init ═══ */
async function init() {
    if (DEMO_MODE) {
        // ── Demo / local browser mode ──
        console.log('🎮 Running in DEMO mode (no Telegram WebApp)');
        state.demoUser = {
            id: parseInt(urlParams.get('user_id') || '100001'),
            username: urlParams.get('username') || 'demo_user',
            first_name: urlParams.get('first_name') || 'Demo',
            last_name: urlParams.get('last_name') || 'User',
        };
        state.userId  = state.demoUser.id;
        state.username = state.demoUser.username;
        state.firstName = state.demoUser.first_name;
        state.lastName  = state.demoUser.last_name;
        state.initData = '';

        // Show demo banner
        const banner = document.createElement('div');
        banner.id = 'demo-banner';
        banner.innerHTML = `
            <span>\uD83C\uDFAE ${t('demo.banner')}</span>
            <span style="flex:1"></span>
            <span>User ID: <input type="number" id="demo-uid" value="${state.userId}" style="width:90px;padding:2px 6px;border-radius:4px;border:1px solid #fff;background:rgba(255,255,255,0.2);color:#fff;font-size:0.8rem;" onchange="demoChangeUser(this.value)"></span>
        `;
        document.body.prepend(banner);

        // Load demo config
        try {
            const d = await api('/api/config');
            if (d.success) state.config = { ...state.config, ...d.config };
        } catch (_) {}

        // Check if there's a real poll; if not, auto-create one with real Chelsea players
        try {
            let dp = await api('/api/poll/current');
            if (dp.success && dp.poll && dp.players && dp.players.length > 0) {
                state.currentPoll = dp.poll;
                state.players = dp.players;
                state.hasVoted = dp.my_vote ? true : false;
                state.myRatings = dp.my_vote || {};
                state.config.max_rating = dp.poll.max_rating || state.config.max_rating;
                if (dp.server_time) {
                    state.serverTimeOffset = dp.server_time - (Date.now() / 1000);
                }
                if (dp.events) state.matchEvents = dp.events;
                if (dp.ai_ratings) state.aiRatings = dp.ai_ratings;
            } else {
                // Use real Chelsea game (Sunderland vs Chelsea 2026-05-24)
                const gameId = '1379346';  // Real match ID
                const gameTitle = 'Sunderland vs Chelsea (2026-05-24)';

                // Create poll with real lineup from the game
                // Pass user_id as query param for auth
                const newPoll = await api(`/api/admin/poll/create?user_id=${state.userId}`, {
                    method: 'POST',
                    body: JSON.stringify({
                        poll_id: `chelsea_${gameId}`,
                        match_id: gameId,
                        title: gameTitle,
                        game_id: gameId,  // server will fetch real lineup
                    }),
                });
                if (newPoll.success) {
                    // Fetch players (starters + subs with photos)
                    const pRes = await api('/api/players');
                    state.currentPoll = newPoll.poll;
                    state.players = pRes.players || [];
                    state.config.max_rating = pRes.max_rating || (state.players.length - 1);

                    // Create profile
                    await api('/api/profile/update', {
                        method: 'POST',
                        body: JSON.stringify({ username: state.username, first_name: state.firstName, last_name: state.lastName }),
                    });

                    // Auto-grant admin to demo user
                    state.isAdmin = true;
                    const adminTabBtn = document.getElementById('admin-tab-btn');
                    if (adminTabBtn) adminTabBtn.style.display = 'flex';
                    const demoStarters = state.players.filter(p => p.is_starter).length;
                    const demoSubs = state.players.filter(p => !p.is_starter).length;
                    toast(`${t('vote.poll_created_toast')} ${demoStarters} ${t('vote.starters')} + ${demoSubs} ${t('vote.subs')}, 0-${state.config.max_rating}`);
                }
            }
        } catch (e) {
            console.error('Demo poll creation failed:', e);
            toast(t('toast.error_creating_poll'));
        }

        // Ensure profile
        try {
            await api('/api/profile/update', {
                method: 'POST',
                body: JSON.stringify({
                    username: state.username,
                    first_name: state.firstName,
                    last_name: state.lastName,
                    // Sync the Telegram profile photo URL into our DB. This
                    // lets leaderboards / admin lists render real avatars
                    // for everyone who has opened the mini-app at least
                    // once.
                    telegram_photo_url: state.telegramPhotoUrl || '',
                }),
            });
        } catch (_) {}

        // Load prediction for current poll
        await loadMyPrediction();

        state.myProfile = {
            user_id: state.userId, username: state.username,
            first_name: state.firstName, last_name: state.lastName,
            auto_id: `chelsea-${String(state.userId).slice(-3).padStart(3, '0')}`,
            custom_id: null, total_votes: 0, avg_rating_given: 0,
            language: 'ru', theme: 'dark', notifications: 1, background_url: '',
        };

    } else {
        // ── Real Telegram mode ──
        if (tg.initDataUnsafe && tg.initDataUnsafe.user) {
            const u = tg.initDataUnsafe.user;
            state.userId   = u.id;
            state.username = u.username || '';
            state.firstName = u.first_name || '';
            state.lastName  = u.last_name || '';
            // Bot API 7.2+ exposes the user's profile photo URL when the
            // mini-app was opened via a menu/keyboard/inline button. We
            // store it in state and ship it to the backend so leaderboards
            // and admin views can render it for everyone too.
            state.telegramPhotoUrl = u.photo_url || '';
        }
        state.initData = tg.initData || '';

        await loadConfig();
        await loadMyProfile();
        await loadCurrentPoll();
        await loadMyPrediction();
    }

    // Setup tabs
    setupTabs();

    // Check admin
    if (parseInt(urlParams.get('admin') || '0') === state.userId || urlParams.get('admin') === '1') {
        state.isAdmin = true;
    }
    const adminTabBtn = document.getElementById('admin-tab-btn');
    if (adminTabBtn && state.isAdmin) adminTabBtn.style.display = 'flex';

    // Render initial tab
    const initialTab = location.hash.replace('#', '') || 'vote';
    switchTab(initialTab);
}

function demoChangeUser(newId) {
    state.userId = parseInt(newId) || 100001;
    state.demoUser.id = state.userId;
    state.myProfile.auto_id = `chelsea-${String(state.userId).slice(-3).padStart(3, '0')}`;
    state.ratings = {};
    state.usedRatings = new Set();
    state.hasVoted = false;
    switchTab('vote');
    toast(`${t('demo.switch_user')} ${state.userId}`);
}

/* ═══ Config ═══ */
async function loadConfig() {
    try {
        const data = await api('/api/config');
        if (data.success) state.config = { ...state.config, ...data.config };
        document.getElementById('bot-name').textContent = state.config.bot_name || 'Челси Голосование';
        // Admin-selected font preset propagates to all clients via /api/config.
        // applyFontPreset sanitizes the value (defaults to 'system' if unknown)
        // so a malformed config row can't break rendering.
        applyFontPreset(state.config.font_preset);
    } catch (e) { console.warn('config load failed', e); }
}

/* ═══ Profile ═══ */
async function loadMyProfile() {
    if (!state.userId) return;
    try {
        const data = await api('/api/profile/me');
        if (data.success) {
            state.myProfile = data.profile;
            state.isAdmin = state.myProfile?.is_admin === 1 || parseInt(new URLSearchParams(location.search).get('admin_check') || '0') === state.userId;
        }
    } catch (e) { console.warn('profile load failed', e); }
}

async function loadCurrentPoll() {
    try {
        const data = await api('/api/poll/current');
        if (data.success && data.poll) {
            state.currentPoll = data.poll;
            state.players = data.players || [];
            state.config.max_rating = data.poll.max_rating || state.config.max_rating;
            // Store server_time for clock offset correction
            if (data.server_time) {
                state.serverTimeOffset = data.server_time - (Date.now() / 1000);
            }
            // Store match events and AI ratings
            if (data.events) state.matchEvents = data.events;
            if (data.ai_ratings) state.aiRatings = data.ai_ratings;
            // Check if already voted
            state.hasVoted = data.my_vote ? true : false;
            state.myRatings = data.my_vote || {};
        }
    } catch (e) { console.warn('poll load failed', e); }
}

async function loadMyPrediction() {
    if (!state.currentPoll) return;
    try {
        var data = await api('/api/prediction/' + state.currentPoll.poll_id);
        if (data.success && data.prediction) {
            state.myPrediction = data.prediction;
        } else {
            state.myPrediction = null;
        }
    } catch (e) { state.myPrediction = null; }
}

/* ═══ Tab Switching ═══ */
function setupTabs() {
    document.querySelectorAll('.tab-btn').forEach(btn => {
        btn.addEventListener('click', () => switchTab(btn.dataset.tab));
    });
    updateTabLabels();
}

function switchTab(tab) {
    // Disconnect SSE when leaving vote tab
    if (tab !== 'vote') {
        disconnectSSE();
    }

    // Update buttons
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === tab));
    // Update content
    document.querySelectorAll('.tab-content').forEach(s => s.classList.toggle('active', s.id === `${tab}-tab`));
    location.hash = tab;

    // Update static headings with i18n
    var otherH2 = document.querySelector('#other-tab > h2');
    if (otherH2) otherH2.textContent = t('history.heading');
    var profileH2 = document.querySelector('#profile-tab > h2');
    if (profileH2) profileH2.textContent = t('profile.heading');
    var settingsH2 = document.querySelector('#settings-tab > h2');
    if (settingsH2) settingsH2.textContent = t('settings.heading');
    var adminH2 = document.querySelector('#admin-tab > h2');
    if (adminH2) adminH2.textContent = '\uD83D\uDEE1\uFE0F ' + t('admin.heading');

    // Lazy-load tab content
    if (tab === 'vote') renderVoteTab();
    else if (tab === 'other') renderOtherTab();
    else if (tab === 'profile') renderProfileTab();
    else if (tab === 'settings') renderSettingsTab();
    else if (tab === 'stats') renderStatsTab();
    else if (tab === 'admin') renderAdminTab();

    // After tab content has had a tick to mount, animate any [data-counter]
    // numeric values inside the new tab.
    setTimeout(function () {
        var pane = document.getElementById(tab + '-tab');
        if (pane) animateAllCounters(pane);
    }, 200);
}

/* ═══════════════════════════════════════════════════
   TAB 1 — VOTE
   ═══════════════════════════════════════════════════ */

function renderVoteTab() {
    const loading = document.getElementById('vote-loading');
    const content = document.getElementById('vote-content');
    const header = document.getElementById('match-header');
    const list = document.getElementById('players-list');

    if (!state.currentPoll) {
        loading.style.display = 'none';
        content.style.display = 'block';
        header.innerHTML = '<div class="empty-state">' +
            '<div class="empty-state-icon">\u26BD</div>' +
            '<div class="empty-state-title">' + t('vote.no_active_polls') + '</div>' +
            '<div class="empty-state-text">' + t('history.no_polls') + '</div>' +
            '</div>';
        list.innerHTML = '';
        document.getElementById('submit-btn').style.display = 'none';
        return;
    }

    loading.style.display = 'none';
    content.style.display = 'block';
    document.getElementById('submit-btn').style.display = 'block';
    document.getElementById('vote-success').innerHTML = '\u2705 ' + t('vote.vote_accepted') + '!';

    const maxR = state.currentPoll.max_rating || state.config.max_rating;
    const totalPlayers = state.players.length;
    const ratedCount = Object.keys(state.ratings).length;

    // Separate starters and subs
    const starters = state.players.filter(p => p.is_starter);
    const subs = state.players.filter(p => !p.is_starter);

    // Header
    header.innerHTML = `
        <div class="card">
            <div class="card-title">${state.currentPoll.title || t('vote.current_match')}</div>
            <div class="player-meta">${t('vote.scale_info')} — ${maxR} · ${totalPlayers} ${t('vote.players_count')} (11 ${t('vote.starters')} + ${subs.length} ${t('vote.subs')})</div>
            ${state.hasVoted ? '<span class="badge badge-gold mt-8">\u2705 ' + t('vote.already_voted') + '</span>' : ''}
        </div>
    `;

    // Countdown timer
    if (window._countdownInterval) clearInterval(window._countdownInterval);
    let countdownHtml = '';
    if (state.config.auto_close_polls == '1' && state.currentPoll.created_at) {
        const deadline = state.currentPoll.created_at + (parseInt(state.config.voting_period_hours) || 24) * 3600;
        const now = Math.floor(Date.now() / 1000) + state.serverTimeOffset;
        const remaining = Math.floor(deadline - now);
        if (remaining > 0) {
            const h = Math.floor(remaining / 3600);
            const m = Math.floor((remaining % 3600) / 60);
            const s = remaining % 60;
            countdownHtml = `<div class="countdown-timer" id="countdown-timer">
                <div class="countdown-label">${t('countdown.time_remaining')}</div>
                <div class="countdown-value">${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}</div>
            </div>`;
        } else {
            countdownHtml = `<div class="countdown-timer expired" id="countdown-timer">
                <div class="countdown-label">${t('countdown.time_expired')}</div>
                <div class="countdown-value">${t('countdown.voting_finished')}</div>
            </div>`;
        }
    }
    header.innerHTML += countdownHtml;

    // Start countdown interval
    if (state.config.auto_close_polls == '1' && state.currentPoll.created_at) {
        const deadline = state.currentPoll.created_at + (parseInt(state.config.voting_period_hours) || 24) * 3600;
        window._countdownInterval = setInterval(() => {
            const el = document.getElementById('countdown-timer');
            if (!el) { clearInterval(window._countdownInterval); return; }
            const now = Math.floor(Date.now() / 1000) + state.serverTimeOffset;
            const remaining = Math.floor(deadline - now);
            if (remaining <= 0) {
                el.classList.add('expired');
                el.querySelector('.countdown-label').textContent = t('countdown.time_expired');
                el.querySelector('.countdown-value').textContent = t('countdown.voting_finished');
                clearInterval(window._countdownInterval);
            } else {
                const h = Math.floor(remaining / 3600);
                const m = Math.floor((remaining % 3600) / 60);
                const s = remaining % 60;
                const newText = `${String(h).padStart(2,'0')}:${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
                const valueEl = el.querySelector('.countdown-value');
                if (valueEl.textContent !== newText) {
                    valueEl.textContent = newText;
                    // Brief tick animation on each second change
                    valueEl.classList.remove('ticking');
                    // eslint-disable-next-line no-unused-expressions
                    valueEl.offsetHeight;
                    valueEl.classList.add('ticking');
                }
            }
        }, 1000);
    }

    // Live voter counter (SSE)
    if (state.currentPoll && state.currentPoll.status === 'open') {
        var liveHtml = '<div class="live-container">' +
            '<span class="live-dot"></span>' +
            '<span class="live-count" id="live-voter-count">' + (state.liveVoterCount || 0) + '</span>' +
            '<span class="live-label"> ' + t('live.voters_now') + '</span></div>';
        header.innerHTML += liveHtml;

        // Connect SSE
        connectSSE(state.currentPoll.poll_id);
    }

    updateProgress(ratedCount, totalPlayers);

    // Pre-match Analytics section
    if (state.currentPoll && state.currentPoll.poll_id) {
        var analyticsContainer = document.createElement('div');
        analyticsContainer.id = 'analytics-section-container';
        list.appendChild(analyticsContainer);
        loadPreMatchAnalytics(state.currentPoll.poll_id, analyticsContainer);
    }

    // Prediction section - before players list
    var predictionHtml = '';
    var pollIsOpen = true;
    if (state.config.auto_close_polls == '1' && state.currentPoll.created_at) {
        var predDeadline = state.currentPoll.created_at + (parseInt(state.config.voting_period_hours) || 24) * 3600;
        var predNow = Math.floor(Date.now() / 1000) + state.serverTimeOffset;
        if (predNow >= predDeadline) pollIsOpen = false;
    }

    if (pollIsOpen && !state.myPrediction) {
        predictionHtml = '<div class="prediction-card">' +
            '<h4>' + t('predictions.predict_best') + '</h4>' +
            '<select class="prediction-select" id="prediction-player-select">' +
            '<option value="">' + t('predictions.select_player') + '</option>';
        for (var pi = 0; pi < state.players.length; pi++) {
            predictionHtml += '<option value="' + state.players[pi].id + '">' + state.players[pi].name + '</option>';
        }
        predictionHtml += '</select>' +
            '<button class="btn-primary" style="margin-top:0" onclick="submitPrediction()">' + t('predictions.submit') + '</button>' +
            '</div>';
    } else if (state.myPrediction) {
        var predictedPlayer = '';
        for (var pi2 = 0; pi2 < state.players.length; pi2++) {
            if (state.players[pi2].id === state.myPrediction.player_id) {
                predictedPlayer = state.players[pi2].name;
                break;
            }
        }
        if (!predictedPlayer) predictedPlayer = state.myPrediction.player_id;
        predictionHtml = '<div class="prediction-card">' +
            '<h4>' + t('predictions.your_prediction') + '</h4>' +
            '<span class="badge badge-gold">' + predictedPlayer + '</span>' +
            '</div>';
    }

    // Re-vote section
    var revoteHtml = '';
    if (state.hasVoted && pollIsOpen && state.config.allow_revote_hours > 0) {
        var revoteDeadline = state.currentPoll.created_at + (parseFloat(state.config.allow_revote_hours) * 3600);
        var revoteNow = Math.floor(Date.now() / 1000) + state.serverTimeOffset;
        var revoteRemaining = revoteDeadline - revoteNow;
        if (revoteRemaining > 0) {
            var revoteHours = Math.floor(revoteRemaining / 3600);
            var revoteMins = Math.floor((revoteRemaining % 3600) / 60);
            revoteHtml = '<button class="revote-btn" onclick="doRevote()">' + t('revote.change_vote') + '</button>' +
                '<div class="revote-info">' + t('revote.hours_remaining') + ': ' + revoteHours + 'h ' + revoteMins + 'm</div>';
        }
    }

    // Insert prediction + revote before players list
    list.innerHTML = '';
    if (predictionHtml) {
        var predDiv = document.createElement('div');
        predDiv.innerHTML = predictionHtml;
        list.appendChild(predDiv);
    }
    if (revoteHtml) {
        var revoteDiv = document.createElement('div');
        revoteDiv.innerHTML = revoteHtml;
        list.appendChild(revoteDiv);
    }

    // Mini Match Timeline
    var timelineEvents = [];
    for (var pid in state.matchEvents) {
        var pevts = state.matchEvents[pid];
        if (Array.isArray(pevts)) {
            for (var tei = 0; tei < pevts.length; tei++) {
                var tevt = pevts[tei];
                timelineEvents.push({event_type: tevt.event_type, emoji: tevt.emoji, minute: tevt.minute, detail: tevt.detail, player_id: pid});
            }
        }
    }
    timelineEvents.sort(function(a, b) { return (a.minute || 0) - (b.minute || 0); });

    if (timelineEvents.length > 0) {
        var timelineDiv = document.createElement('div');
        timelineDiv.className = 'timeline-section';
        var visClass = state.timelineVisible ? ' visible' : '';
        var btnText = state.timelineVisible ? t('timeline.hide') : t('timeline.show');

        var dotsHtml = '';
        for (var ti = 0; ti < timelineEvents.length; ti++) {
            var te = timelineEvents[ti];
            var leftPct = Math.min(100, Math.max(0, ((te.minute || 0) / 90) * 100));
            var dotClass = 'sub';
            if (te.event_type === 1) dotClass = 'goal';
            else if (te.event_type === 2) dotClass = te.detail && te.detail.includes('red') ? 'card-red' : 'card-yellow';
            var tPlayerName = '';
            for (var tpi = 0; tpi < state.players.length; tpi++) {
                if (String(state.players[tpi].id) === String(te.player_id) || String(state.players[tpi].player_id) === String(te.player_id)) {
                    tPlayerName = state.players[tpi].name; break;
                }
            }
            dotsHtml += '<div class="timeline-dot ' + dotClass + '" style="left:' + leftPct + '%;"><div class="timeline-tooltip">' + (te.emoji || '') + ' ' + tPlayerName + ' ' + (te.minute || '') + "'" + '</div></div>';
        }

        timelineDiv.innerHTML = '<div class="timeline-toggle" onclick="toggleTimeline()">' +
            '<h4>' + t('timeline.title') + '</h4>' +
            '<button class="timeline-toggle-btn" id="timeline-btn">' + btnText + '</button></div>' +
            '<div class="timeline-bar-container' + visClass + '" id="timeline-container">' +
            '<div class="timeline-bar">' + dotsHtml + '</div>' +
            '<div class="timeline-labels"><span>0\'</span><span>45\'</span><span>90\'</span></div></div>';
        list.appendChild(timelineDiv);
    }

    // Player list - starters first

    if (starters.length > 0) {
        const startersHeader = document.createElement('h3');
        startersHeader.style.cssText = 'color:var(--gold);margin:12px 0 8px;font-size:0.95rem;';
        startersHeader.textContent = `\u2B50 ${t('vote.starting_lineup')} (${starters.length})`;
        list.appendChild(startersHeader);

        starters.forEach((p, idx) => {
            const c = createPlayerCard(p, maxR);
            c.style.setProperty('--enter-delay', (idx * 45) + 'ms');
            list.appendChild(c);
        });
    }

    if (subs.length > 0) {
        const subsHeader = document.createElement('h3');
        subsHeader.style.cssText = 'color:var(--text-dim);margin:16px 0 8px;font-size:0.95rem;';
        subsHeader.textContent = `\uD83D\uDD04 ${t('vote.substitutes')} (${subs.length})`;
        list.appendChild(subsHeader);

        subs.forEach((p, idx) => {
            const c = createPlayerCard(p, maxR);
            // continue stagger from the starter range
            c.style.setProperty('--enter-delay', ((starters.length + idx) * 45) + 'ms');
            list.appendChild(c);
        });
    }

    // Restore ratings from my_vote if already voted
    if (state.hasVoted && state.myRatings) {
        for (const [pid, rating] of Object.entries(state.myRatings)) {
            state.ratings[pid] = rating;
            state.usedRatings.add(rating);
        }
    }

    // Submit button enable/disable logic
    const submitBtn = document.getElementById('submit-btn');
    const allRated = ratedCount === totalPlayers && totalPlayers > 0;
    submitBtn.disabled = !allRated || state.hasVoted;
    submitBtn.classList.toggle('ready', allRated && !state.hasVoted);
    submitBtn.textContent = state.hasVoted ? t('vote.already_voted') : t('vote.submit');
    submitBtn.onclick = submitVote;
}

function createPlayerCard(p, maxR) {
    const card = document.createElement('div');
    card.className = 'player-card';
    // If this player was the most recently rated, flash the gold pulse once.
    if (state.lastRatedPlayerId === p.id) {
        card.classList.add('just-rated');
    }

    const photoHtml = p.photo_url
        ? `<img class="player-photo" src="${p.photo_url}" alt="${p.name}" loading="lazy" onload="this.classList.add('loaded')" onerror="this.outerHTML='<div class=\\'player-photo-placeholder\\'>${(p.name||'?')[0]}</div>'">`
        : `<div class="player-photo-placeholder">${(p.name || '?')[0]}</div>`;

    const badge = p.is_starter
        ? `<span class="badge badge-blue" style="font-size:0.6rem">${t('vote.starter_badge')}</span>`
        : `<span class="badge" style="font-size:0.6rem;background:#555">${t('vote.sub_badge')}</span>`;

    // Event badges (goals, cards, subs)
    var eventBadges = '';
    var playerEvents = state.matchEvents[p.id] || state.matchEvents[p.player_id] || [];
    if (playerEvents && playerEvents.length > 0) {
        for (var ei = 0; ei < playerEvents.length; ei++) {
            var ev = playerEvents[ei];
            var evClass = 'sub';
            if (ev.event_type === 1) evClass = 'goal';
            else if (ev.event_type === 2) evClass = ev.detail && ev.detail.includes('red') ? 'card-red' : 'card';
            eventBadges += '<span class="event-badge ' + evClass + '">' + (ev.emoji || '') + ' ' + (ev.minute || '') + "'" + '</span>';
        }
    }

    // FPL badge
    var fplBadgeHtml = '';
    if (state.fplData && state.fplData.mapping) {
        var fplInfo = state.fplData.mapping[String(p.id)] || state.fplData.mapping[String(p.player_id)];
        if (fplInfo) {
            fplBadgeHtml = '<span class="fpl-badge-small">FPL: ' + fplInfo.event_points + '</span>';
        }
    }

    let chipsHtml = '<div class="rating-chips">';
    for (let i = 0; i <= maxR; i++) {
        const isUsed = state.usedRatings.has(i) && state.ratings[p.id] !== i;
        const isSelected = state.ratings[p.id] === i;
        chipsHtml += `<button class="rating-chip${isUsed ? ' used' : ''}${isSelected ? ' selected' : ''}"
            data-player="${p.id}" data-rating="${i}" ${isUsed ? 'disabled' : ''}>${i}</button>`;
    }
    chipsHtml += '</div>';

    card.innerHTML = `
        ${photoHtml}
        <div class="player-info">
            <div class="player-name">#${p.number || ''} ${p.name} ${badge} ${eventBadges} ${fplBadgeHtml}</div>
            <div class="player-meta">${p.position || ''}</div>
        </div>
    `;

    const chipsContainer = document.createElement('div');
    chipsContainer.style.flex = '0 0 100%';
    chipsContainer.innerHTML = chipsHtml;
    card.appendChild(chipsContainer);

    // Chip click
    card.querySelectorAll('.rating-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            if (chip.classList.contains('used')) return;
            const playerId = chip.dataset.player;
            const rating = parseInt(chip.dataset.rating);
            if (state.ratings[playerId] !== undefined) {
                state.usedRatings.delete(state.ratings[playerId]);
            }
            state.ratings[playerId] = rating;
            state.usedRatings.add(rating);
            // Mark the just-rated card so the next render flashes a gold pulse
            // around it (see createPlayerCard).
            state.lastRatedPlayerId = playerId;
            playSound('click');
            renderVoteTab();
            // Clear the marker so subsequent unrelated re-renders don't re-flash
            setTimeout(() => {
                if (state.lastRatedPlayerId === playerId) state.lastRatedPlayerId = null;
            }, 700);
        });
    });

    return card;
}

function toggleTimeline() {
    state.timelineVisible = !state.timelineVisible;
    var container = document.getElementById('timeline-container');
    var btn = document.getElementById('timeline-btn');
    if (container) container.classList.toggle('visible', state.timelineVisible);
    if (btn) btn.textContent = state.timelineVisible ? t('timeline.hide') : t('timeline.show');
}

function updateProgress(done, total) {
    const fill = document.getElementById('progress-fill');
    const text = document.getElementById('progress-text');
    const pct = total === 0 ? 0 : Math.round((done / total) * 100);
    fill.style.width = `${pct}%`;
    text.textContent = `${t('vote.rated_of')} ${done} ${t('vote.of')} ${total}`;
}

function loadPreMatchAnalytics(pollId, container) {
    api('/api/analytics/' + pollId).then(function(data) {
        if (!data || !data.success || !data.analytics) {
            container.innerHTML = '';
            return;
        }
        var a = data.analytics;
        var formHtml = '';
        if (a.opponent_form && a.opponent_form.length > 0) {
            for (var i = 0; i < a.opponent_form.length; i++) {
                var r = a.opponent_form[i];
                var cls = r === 'W' ? 'form-win' : (r === 'L' ? 'form-loss' : 'form-draw');
                formHtml += '<span class="analytics-form-indicator ' + cls + '">' + r + '</span>';
            }
        } else {
            formHtml = '<span class="analytics-no-data">' + t('analytics.no_data') + '</span>';
        }

        var h2hHtml = '';
        if (a.h2h_stats) {
            h2hHtml = '<div class="analytics-h2h-stat">' +
                '<span class="h2h-wins">' + t('analytics.wins') + ': ' + (a.h2h_stats.wins || 0) + '</span>' +
                '<span class="h2h-draws">' + t('analytics.draws') + ': ' + (a.h2h_stats.draws || 0) + '</span>' +
                '<span class="h2h-losses">' + t('analytics.losses') + ': ' + (a.h2h_stats.losses || 0) + '</span>' +
                '</div>';
            if (a.h2h_stats.last_meetings && a.h2h_stats.last_meetings.length > 0) {
                h2hHtml += '<div class="analytics-meetings"><div class="analytics-meetings-title">' + t('analytics.last_meetings') + ':</div>';
                for (var j = 0; j < a.h2h_stats.last_meetings.length; j++) {
                    var m = a.h2h_stats.last_meetings[j];
                    var mCls = m.result === 'W' ? 'form-win' : (m.result === 'L' ? 'form-loss' : 'form-draw');
                    h2hHtml += '<div class="analytics-meeting-row"><span class="analytics-form-indicator ' + mCls + '">' + m.result + '</span> ' +
                        m.home + ' ' + m.home_score + ' - ' + m.away_score + ' ' + m.away + '</div>';
                }
                h2hHtml += '</div>';
            }
        }

        var predHtml = a.predicted_result ? '<div class="analytics-prediction"><strong>' + t('analytics.prediction') + ':</strong> ' + a.predicted_result + '</div>' : '';

        container.innerHTML = '<div class="analytics-section" id="analytics-section">' +
            '<div class="analytics-toggle" onclick="toggleAnalytics()">' +
            '<h4>' + t('analytics.title') + '</h4>' +
            '<button class="analytics-toggle-btn" id="analytics-btn">' + t('timeline.show') + '</button></div>' +
            '<div class="analytics-content" id="analytics-content">' +
            '<div class="analytics-opponent"><strong>' + t('analytics.opponent_form') + ' (' + escapeHtml(a.opponent_name || '') + '):</strong><div class="analytics-form-row">' + formHtml + '</div></div>' +
            '<div class="analytics-h2h"><strong>' + t('analytics.h2h') + ':</strong>' + h2hHtml + '</div>' +
            predHtml +
            '</div></div>';
    }).catch(function() {
        container.innerHTML = '';
    });
}

function toggleAnalytics() {
    var content = document.getElementById('analytics-content');
    var btn = document.getElementById('analytics-btn');
    if (!content || !btn) return;
    if (content.classList.contains('visible')) {
        content.classList.remove('visible');
        btn.textContent = t('timeline.show');
    } else {
        content.classList.add('visible');
        btn.textContent = t('timeline.hide');
    }
}

async function submitVote() {
    const pollId = state.currentPoll?.poll_id;
    const maxR = state.currentPoll?.max_rating || state.config.max_rating;
    const verifyData = tg.initDataUnsafe || {};

    // Validate all rated
    const rated = Object.keys(state.ratings).length;
    const total = state.players.length;
    if (rated < total) {
        document.getElementById('vote-error').style.display = 'block';
        document.getElementById('vote-error').textContent = `${t('vote.rate_all_players')} ${total - rated}`;
        return;
    }

    // Validate unique
    const vals = Object.values(state.ratings);
    if (new Set(vals).size !== vals.length) {
        document.getElementById('vote-error').style.display = 'block';
        document.getElementById('vote-error').textContent = t('vote.all_ratings_unique');
        return;
    }

    const btn = document.getElementById('submit-btn');
    btn.disabled = true;
    btn.classList.add('submitting');
    btn.classList.remove('success');
    // Keep the label invisible (CSS color: transparent) but readable for SR
    btn.setAttribute('aria-label', t('vote.sending'));

    try {
        const data = await api('/api/vote_batch', {
            method: 'POST',
            body: JSON.stringify({
                poll_id: pollId,
                votes: state.ratings,
                batch_id: `batch_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
                // Telegram init data for verification (optional server-side)
                _initData: state.initData,
            }),
        });
        if (data.success) {
            state.hasVoted = true;
            // Visible feedback chain: spinner -> green check pulse -> confetti -> renderVoteTab
            btn.classList.remove('submitting');
            btn.classList.add('success');
            btn.textContent = '\u2705 ' + t('vote.vote_accepted');
            btn.removeAttribute('aria-label');
            launchConfetti();
            playSound('success');
            toast(t('vote.vote_success_toast'));
            // Let the success state breathe for a moment, then redraw the tab
            setTimeout(() => {
                document.getElementById('vote-success').style.display = 'block';
                renderVoteTab();
            }, 650);
        } else {
            btn.classList.remove('submitting', 'success');
            document.getElementById('vote-error').style.display = 'block';
            document.getElementById('vote-error').textContent = data.error || t('common.error');
            btn.disabled = false;
            btn.textContent = t('vote.submit');
        }
    } catch (e) {
        btn.classList.remove('submitting', 'success');
        document.getElementById('vote-error').style.display = 'block';
        document.getElementById('vote-error').textContent = t('vote.connection_error');
        btn.disabled = false;
        btn.textContent = t('vote.submit');
    }
}

async function submitPrediction() {
    var select = document.getElementById('prediction-player-select');
    if (!select || !select.value) { toast(t('predictions.select_player')); return; }
    try {
        var data = await api('/api/prediction', {
            method: 'POST',
            body: JSON.stringify({ poll_id: state.currentPoll.poll_id, player_id: select.value })
        });
        if (data.success) {
            state.myPrediction = { player_id: select.value, timestamp: Date.now() / 1000 };
            toast(t('predictions.submitted'));
            renderVoteTab();
        } else {
            toast(data.error || t('common.error'));
        }
    } catch (e) { toast(t('common.error')); }
}

async function doRevote() {
    if (!state.currentPoll) return;
    try {
        var data = await api('/api/revote', {
            method: 'POST',
            body: JSON.stringify({ poll_id: state.currentPoll.poll_id })
        });
        if (data.success) {
            state.hasVoted = false;
            state.ratings = {};
            state.usedRatings = new Set();
            state.myRatings = {};
            toast(t('revote.vote_reset'));
            renderVoteTab();
        } else {
            toast(data.error || t('common.error'));
        }
    } catch (e) { toast(t('common.error')); }
}

/* ═══════════════════════════════════════════════════
   TAB 2 — MATCH HISTORY
   ═══════════════════════════════════════════════════ */

async function renderOtherTab() {
    const loading = document.getElementById('other-loading');
    const content = document.getElementById('other-content');
    loading.style.display = 'block';
    content.style.display = 'none';

    var matchHistory = [];
    try {
        const data = await api('/api/match-history');
        if (data.success) matchHistory = data.polls || [];
    } catch (e) {
        matchHistory = [];
    }

    loading.style.display = 'none';
    content.style.display = 'block';

    if (matchHistory.length === 0) {
        content.innerHTML = '<div class="empty-state">' +
            '<div class="empty-state-icon">\uD83D\uDCDC</div>' +
            '<div class="empty-state-title">' + t('history.no_polls') + '</div>' +
            '</div>';
        return;
    }

    var html = '';
    for (var i = 0; i < matchHistory.length; i++) {
        var poll = matchHistory[i];
        var dateStr = tsToDate(poll.created_at);
        var closedStr = poll.closed_at ? tsToDate(poll.closed_at) : '';
        var topPlayers = poll.top_players || [];

        var medalsHtml = '';
        var medalClasses = ['medal-gold', 'medal-silver', 'medal-bronze'];
        var medalLabels = ['1', '2', '3'];
        for (var m = 0; m < Math.min(topPlayers.length, 3); m++) {
            medalsHtml += '<div style="display:flex;align-items:center;gap:6px;margin-top:4px;">' +
                '<span class="medal ' + medalClasses[m] + '">' + medalLabels[m] + '</span>' +
                '<span style="font-size:0.85rem;">' + topPlayers[m].name + '</span>' +
                '<span style="font-size:0.75rem;color:var(--gold);">' + (topPlayers[m].avg_rating != null ? topPlayers[m].avg_rating.toFixed(1) : '-') + '</span>' +
                '</div>';
        }

        html += '<div class="card history-card" data-poll-id="' + poll.poll_id + '" onclick="toggleHistoryCard(this, \'' + poll.poll_id + '\')">' +
            '<div class="card-title">' + (poll.title || t('tabs.vote')) + '</div>' +
            '<div class="player-meta">' +
                '<span class="badge badge-blue">' + t('history.status_closed') + '</span> ' +
                (closedStr ? closedStr : dateStr) +
                ' &middot; <span class="badge badge-success">' + t('history.total_voters') + ': ' + (poll.total_voters || 0) + '</span>' +
            '</div>' +
            '<div style="margin-top:8px;">' + medalsHtml + '</div>' +
            '<div class="results-detail" id="results-' + poll.poll_id + '"></div>' +
        '</div>';
    }

    content.innerHTML = html;
}

function toggleHistoryCard(cardEl, pollId) {
    var wasExpanded = cardEl.classList.contains('expanded');
    // Collapse all
    document.querySelectorAll('.history-card.expanded').forEach(function(c) {
        c.classList.remove('expanded');
    });
    if (!wasExpanded) {
        cardEl.classList.add('expanded');
        renderPollResults(pollId);
    }
}

async function renderPollResults(pollId) {
    var container = document.getElementById('results-' + pollId);
    if (!container) return;
    container.innerHTML = '<div class="loading" style="padding:12px;">' + t('common.loading') + '</div>';

    try {
        var data = await api('/api/results/' + pollId + '/visualization');
        if (!data.success) {
            container.innerHTML = '<div class="player-meta">' + t('common.error') + '</div>';
            return;
        }

        var results = data.results || [];
        var totalVoters = data.total_voters || 0;
        var medals = data.medals || {};
        var bestMatch = data.best_match;
        var worstMatch = data.worst_match;

        var html = '';

        // Best/Worst match stats
        if (bestMatch || worstMatch) {
            html += '<div class="grid-2 mb-8">';
            if (bestMatch) {
                html += '<div class="stat-card" style="background:var(--bg);padding:8px;border-radius:8px;text-align:center;">' +
                    '<div style="font-size:0.7rem;color:var(--success);">Best</div>' +
                    '<div style="font-size:0.8rem;font-weight:600;">' + (bestMatch.name || bestMatch.player_id || '-') + '</div>' +
                    '<div style="font-size:0.75rem;color:var(--gold);">' + (bestMatch.avg_rating != null ? bestMatch.avg_rating.toFixed(1) : '-') + '</div>' +
                '</div>';
            }
            if (worstMatch) {
                html += '<div class="stat-card" style="background:var(--bg);padding:8px;border-radius:8px;text-align:center;">' +
                    '<div style="font-size:0.7rem;color:var(--danger);">Worst</div>' +
                    '<div style="font-size:0.8rem;font-weight:600;">' + (worstMatch.name || worstMatch.player_id || '-') + '</div>' +
                    '<div style="font-size:0.75rem;color:var(--gold);">' + (worstMatch.avg_rating != null ? worstMatch.avg_rating.toFixed(1) : '-') + '</div>' +
                '</div>';
            }
            html += '</div>';
        }

        // Podium for top 3
        if (medals.gold || medals.silver || medals.bronze) {
            html += '<div class="podium">';
            if (medals.silver) {
                html += '<div class="podium-item"><span class="medal medal-silver">2</span><div class="podium-name">' + medals.silver.name + '</div><div class="podium-rating">' + (medals.silver.avg_rating != null ? medals.silver.avg_rating.toFixed(1) : '-') + '</div></div>';
            }
            if (medals.gold) {
                html += '<div class="podium-item"><span class="medal medal-gold">1</span><div class="podium-name">' + medals.gold.name + '</div><div class="podium-rating">' + (medals.gold.avg_rating != null ? medals.gold.avg_rating.toFixed(1) : '-') + '</div></div>';
            }
            if (medals.bronze) {
                html += '<div class="podium-item"><span class="medal medal-bronze">3</span><div class="podium-name">' + medals.bronze.name + '</div><div class="podium-rating">' + (medals.bronze.avg_rating != null ? medals.bronze.avg_rating.toFixed(1) : '-') + '</div></div>';
            }
            html += '</div>';
        }

        // Total voters
        html += '<div class="player-meta mb-8" style="text-align:center;">' + t('history.total_voters') + ': <span data-counter="' + totalVoters + '">0</span></div>';

        // Fetch FPL data for this poll
        var fplMapping = {};
        var fplCorrelation = null;
        try {
            var fplGwData = await api('/api/fpl/gameweek');
            if (fplGwData.success && fplGwData.mapping) {
                fplMapping = fplGwData.mapping;
                state.fplData = fplGwData;
            }
        } catch (fplErr) { /* FPL data not available */ }

        // Bar chart
        if (results.length > 0) {
            var maxRating = 0;
            for (var i = 0; i < results.length; i++) {
                if (results[i].avg_rating > maxRating) maxRating = results[i].avg_rating;
            }
            if (maxRating === 0) maxRating = 1;

            html += '<div class="bar-chart-container">';
            for (var i = 0; i < results.length; i++) {
                var r = results[i];
                var widthPct = (r.avg_rating / maxRating * 100).toFixed(1);
                var barColor = i === 0 ? 'var(--gold)' : (i === 1 ? '#c0c0c0' : (i === 2 ? '#cd7f32' : 'var(--blue)'));
                var fplBadge = '';
                var pid = String(r.player_id || '');
                if (fplMapping[pid]) {
                    fplBadge = ' <span class="fpl-badge">FPL: ' + fplMapping[pid].event_points + ' ' + t('fpl.points') + '</span>';
                }
                var podiumClass = i === 0 ? ' podium-1' : (i === 1 ? ' podium-2' : (i === 2 ? ' podium-3' : ''));
                var barDelay = (i * 60) + 'ms';
                html += '<div class="bar-chart-row' + podiumClass + '">' +
                    '<div class="bar-chart-label">' + r.name + fplBadge + '</div>' +
                    '<div class="bar-chart-bar" style="--bar-target:' + widthPct + '%;--bar-delay:' + barDelay + ';background:' + barColor + ';"></div>' +
                    '<div class="bar-chart-value" data-counter="' + (r.avg_rating != null ? r.avg_rating.toFixed(1) : '0') + '">0</div>' +
                '</div>';
            }
            html += '</div>';
        }

        // AI Rating comparison (Bot's Opinion)
        try {
            var compData = await api('/api/results/' + pollId + '/comparison');
            if (compData.success && compData.bot_ratings && Object.keys(compData.bot_ratings).length > 0) {
                html += '<div class="comparison-section">';
                html += '<h4>' + t('ai_rating.title') + '</h4>';
                html += '<table class="comparison-table"><thead><tr><th>Player</th><th>' + t('ai_rating.you') + '</th><th>' + t('ai_rating.bot') + '</th><th>' + t('ai_rating.community') + '</th></tr></thead><tbody>';

                for (var ci = 0; ci < Math.min(results.length, 10); ci++) {
                    var cr = results[ci];
                    var playerName = cr.name || cr.player_name || cr.player_id;
                    var userR = compData.user_ratings ? compData.user_ratings[cr.player_id] : null;
                    var botR = compData.bot_ratings[cr.player_id];
                    var commR = compData.community_avg ? compData.community_avg[cr.player_id] : cr.avg_rating;

                    var userStr = userR != null ? userR.toFixed(1) : '-';
                    var botStr = botR != null ? botR.toFixed(1) : '-';
                    var commStr = commR != null ? Number(commR).toFixed(1) : '-';

                    var diffClass = '';
                    if (botR != null && commR != null && Math.abs(botR - commR) > 2) {
                        diffClass = botR > commR ? ' comparison-diff-high' : ' comparison-diff-low';
                    }

                    html += '<tr><td>' + playerName + '</td><td>' + userStr + '</td><td class="' + diffClass + '">' + botStr + '</td><td>' + commStr + '</td></tr>';
                }
                html += '</tbody></table></div>';
            }
        } catch (compErr) { /* comparison not available */ }

        // Most Controversial Player
        try {
            var contData = await api('/api/controversial/' + pollId);
            if (contData.success && contData.players && contData.players.length > 0) {
                var contPlayers = contData.players;

                html += '<div class="controversial-section">';
                html += '<h4>' + t('controversial.title') + ' <span class="controversial-badge">' + t('controversial.badge_text') + '</span></h4>';

                // Show top 3 most controversial
                for (var ci = 0; ci < Math.min(contPlayers.length, 3); ci++) {
                    var cp = contPlayers[ci];
                    html += '<div class="controversial-player">' +
                        '<span class="controversial-rank">' + (ci + 1) + '</span>' +
                        '<span class="controversial-name">' + cp.name + (ci === 0 ? ' \uD83D\uDD25' : '') + '</span>' +
                        '<span class="controversial-stats">' + t('controversial.std_dev') + ': ' + (cp.std_dev != null ? cp.std_dev.toFixed(2) : '-') + '<br>avg: ' + (cp.avg_rating != null ? cp.avg_rating.toFixed(1) : '-') + '</span>' +
                    '</div>';
                }
                html += '</div>';
            }
        } catch (e) { /* controversial data not available */ }

        // Overrated / Underrated Analysis
        try {
            var overData = await api('/api/results/' + pollId + '/overrated');
            if (overData.success && !overData.no_data && overData.players && overData.players.length > 0) {
                html += '<div class="overrated-section">';
                html += '<h4>' + t('overrated.title') + '</h4>';

                for (var oi = 0; oi < overData.players.length; oi++) {
                    var op = overData.players[oi];
                    var arrowClass = '';
                    var arrowIcon = '';
                    var diffLabel = '';
                    if (op.classification === 'overrated') {
                        arrowClass = 'overrated-arrow-up';
                        arrowIcon = '\u2191';
                        diffLabel = t('overrated.overrated_by_fans');
                    } else if (op.classification === 'underrated') {
                        arrowClass = 'overrated-arrow-down';
                        arrowIcon = '\u2193';
                        diffLabel = t('overrated.underrated_by_fans');
                    } else {
                        arrowClass = '';
                        arrowIcon = '\u2194';
                        diffLabel = t('overrated.fair');
                    }
                    var diffSign = op.difference > 0 ? '+' : '';
                    html += '<div class="overrated-item">' +
                        '<span class="' + arrowClass + '">' + arrowIcon + '</span>' +
                        '<span class="overrated-name">' + op.name + '</span>' +
                        '<span class="overrated-diff' + (op.classification === 'overrated' ? ' overrated-diff-up' : (op.classification === 'underrated' ? ' overrated-diff-down' : '')) + '">' + diffSign + op.difference.toFixed(1) + '</span>' +
                        '<span class="overrated-label">' + diffLabel + '</span>' +
                    '</div>';
                }
                html += '</div>';
            } else if (overData.success && overData.no_data) {
                html += '<div class="overrated-section"><h4>' + t('overrated.title') + '</h4><p class="player-meta">' + t('overrated.no_data') + '</p></div>';
            }
        } catch (e) { /* overrated data not available */ }

        // FPL Correlation
        try {
            var corrData = await api('/api/fpl/correlation/' + pollId);
            if (corrData.success && corrData.correlation != null && !corrData.no_data) {
                var corrVal = corrData.correlation;
                var corrDesc = Math.abs(corrVal) > 0.5 ? t('fpl.high_correlation') : t('fpl.low_correlation');
                html += '<div class="fpl-correlation">' +
                    '<div class="fpl-correlation-value">' + corrVal.toFixed(2) + '</div>' +
                    '<div><div class="fpl-correlation-label">' + t('fpl.correlation') + '</div>' +
                    '<div class="fpl-correlation-desc">' + corrDesc + '</div></div>' +
                '</div>';
            }
        } catch (e) { /* FPL correlation not available */ }

        // Match Report section
        try {
            var reportData = await api('/api/report/' + pollId);
            if (reportData.success && reportData.report_data) {
                var rd = reportData.report_data;
                html += '<div class="report-section">';
                html += '<h4>\uD83D\uDCCB ' + t('report.title') + '</h4>';
                if (rd.fan_mvp) {
                    html += '<div class="report-mvp">' +
                        '<span class="report-mvp-medal">\uD83C\uDFC6</span>' +
                        '<span class="report-mvp-name">' + t('report.fan_mvp') + ': ' + rd.fan_mvp.name + '</span>' +
                        '<span class="report-mvp-rating">' + (rd.fan_mvp.rating != null ? Number(rd.fan_mvp.rating).toFixed(1) : '-') + '</span>' +
                    '</div>';
                }
                if (rd.top3 && rd.top3.length > 0) {
                    html += '<div class="report-top3-label">' + t('report.top_3') + ':</div>';
                    var topMedals = ['\uD83E\uDD47', '\uD83E\uDD48', '\uD83E\uDD49'];
                    for (var ti = 0; ti < rd.top3.length; ti++) {
                        html += '<div class="report-stat-row">' +
                            '<span><span class="medal-emoji">' + topMedals[ti] + '</span> ' + (rd.top3[ti].name || '-') + '</span>' +
                            '<span>' + topMedals[ti] + ' ' + rd.top3[ti].name + '</span>' +
                            '<span>' + (rd.top3[ti].avg_rating != null ? Number(rd.top3[ti].avg_rating).toFixed(1) : '-') + '</span>' +
                        '</div>';
                    }
                }
                if (rd.controversial) {
                    html += '<div class="report-stat-row report-controversial">' +
                        '<span>\uD83D\uDD25 ' + t('report.controversial') + ': ' + rd.controversial.name + '</span>' +
                        '<span>std: ' + (rd.controversial.std_dev != null ? Number(rd.controversial.std_dev).toFixed(2) : '-') + '</span>' +
                    '</div>';
                }
                html += '<div class="report-stat-row">' +
                    '<span>\uD83D\uDC65 ' + t('report.voters') + '</span>' +
                    '<span>' + (rd.total_voters || 0) + '</span>' +
                '</div>';
                if (rd.ai_comparison && rd.ai_comparison.length > 0) {
                    html += '<div class="report-comparison">';
                    html += '<div class="report-comparison-title">\uD83E\uDD16 ' + t('report.ai_comparison') + ':</div>';
                    for (var ai = 0; ai < rd.ai_comparison.length; ai++) {
                        var ac = rd.ai_comparison[ai];
                        var arrow = ac.difference > 0 ? '\u2191' : '\u2193';
                        html += '<div class="report-stat-row">' +
                            '<span>' + arrow + ' ' + ac.name + '</span>' +
                            '<span>fans ' + Number(ac.fan_rating).toFixed(1) + ' / AI ' + Number(ac.ai_rating).toFixed(1) + '</span>' +
                        '</div>';
                    }
                    html += '</div>';
                }
                if (rd.generated_at) {
                    var genDate = new Date(rd.generated_at * 1000);
                    html += '<div class="report-timestamp">' + genDate.toLocaleDateString() + ' ' + genDate.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) + '</div>';
                }
                html += '</div>';
            }
        } catch (e) { /* report not available */ }

        // Share button
        html += '<div style="text-align:center;margin-top:12px;">';
        html += '<button class="share-btn" onclick="shareResults(\'' + pollId + '\')">' + t('social.share_results') + '</button>';
        html += '<button class="share-card-btn" onclick="shareResultCard(\'' + pollId + '\')">&#x1f5bc;&#xfe0f; ' + t('share.generate_card') + '</button>';
        html += '</div>';

        container.innerHTML = html;
    } catch (e) {
        container.innerHTML = '<div class="player-meta">' + t('common.error') + '</div>';
    }
}

async function shareResults(pollId) {
    try {
        var data = await api('/api/results/' + pollId + '/visualization');
        if (!data.success || !data.results) { toast(t('common.error')); return; }
        var results = data.results;
        var poll = state.allPolls.find(function(p) { return p.poll_id === pollId; }) || state.currentPoll || {};
        var title = poll.title || pollId;
        var text = title + '\n' + t('social.top_5') + ':\n';
        for (var i = 0; i < Math.min(results.length, 5); i++) {
            text += (i + 1) + '. ' + results[i].name + ' - ' + (results[i].avg_rating != null ? results[i].avg_rating.toFixed(1) : '-') + '\n';
        }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(function() {
                toast(t('social.copied'));
            }).catch(function() {
                toast(t('common.error'));
            });
        }
        if (tg && tg.shareMessage) {
            try { tg.shareMessage(text); } catch (e) { /* fallback to clipboard */ }
        }
    } catch (e) { toast(t('common.error')); }
}

/* ═══ Result Card Generation (Canvas API) ═══ */

async function generateResultCard(pollId) {
    // Fetch results data
    var data = await api('/api/results/' + pollId + '/visualization');
    if (!data.success || !data.results) { toast(t('common.error')); return null; }

    var results = data.results;
    var poll = data.poll || state.currentPoll || {};
    var totalVoters = data.total_voters || 0;

    // Create canvas
    var canvas = document.createElement('canvas');
    canvas.width = 600;
    canvas.height = 800;
    var ctx = canvas.getContext('2d');

    // Background gradient (Chelsea blue)
    var grad = ctx.createLinearGradient(0, 0, 0, 800);
    grad.addColorStop(0, '#022d5c');
    grad.addColorStop(0.5, '#034694');
    grad.addColorStop(1, '#0a1628');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, 600, 800);

    // Decorative lines
    ctx.strokeStyle = 'rgba(219, 161, 17, 0.3)';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(30, 80);
    ctx.lineTo(570, 80);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(30, 720);
    ctx.lineTo(570, 720);
    ctx.stroke();

    // Title
    ctx.fillStyle = '#DBA111';
    ctx.font = 'bold 28px -apple-system, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(poll.title || 'Match Results', 300, 50);

    // Subtitle
    ctx.fillStyle = '#8899b0';
    ctx.font = '16px -apple-system, sans-serif';
    ctx.fillText('Chelsea Voting Bot - Player Ratings', 300, 110);

    // Total voters
    ctx.fillStyle = '#ffffff';
    ctx.font = '14px -apple-system, sans-serif';
    ctx.fillText(totalVoters + ' voters', 300, 135);

    // Top 5 players
    var top5 = results.slice(0, 5);
    var startY = 180;
    var rowHeight = 100;

    for (var i = 0; i < top5.length; i++) {
        var r = top5[i];
        var y = startY + i * rowHeight;
        var playerName = r.player_name || r.name || r.player_id;

        // Medal/rank circle
        var circleColors = ['#DBA111', '#c0c0c0', '#cd7f32', '#034694', '#034694'];
        ctx.beginPath();
        ctx.arc(60, y + 30, 22, 0, Math.PI * 2);
        ctx.fillStyle = circleColors[i];
        ctx.fill();
        ctx.fillStyle = i < 3 ? '#000' : '#fff';
        ctx.font = 'bold 18px sans-serif';
        ctx.textAlign = 'center';
        ctx.fillText(String(i + 1), 60, y + 36);

        // Player name
        ctx.textAlign = 'left';
        ctx.fillStyle = '#ffffff';
        ctx.font = 'bold 20px -apple-system, sans-serif';
        ctx.fillText(playerName, 100, y + 25);

        // Rating bar
        var maxWidth = 350;
        var barWidth = (r.avg_rating / (poll.max_rating || 15)) * maxWidth;
        barWidth = Math.min(maxWidth, Math.max(20, barWidth));

        var barGrad = ctx.createLinearGradient(100, y + 40, 100 + barWidth, y + 40);
        barGrad.addColorStop(0, '#034694');
        barGrad.addColorStop(1, '#DBA111');
        ctx.fillStyle = barGrad;
        if (ctx.roundRect) {
            ctx.beginPath();
            ctx.roundRect(100, y + 38, barWidth, 16, 8);
            ctx.fill();
        } else {
            ctx.fillRect(100, y + 38, barWidth, 16);
        }

        // Rating value
        ctx.fillStyle = '#DBA111';
        ctx.font = 'bold 22px sans-serif';
        ctx.textAlign = 'right';
        ctx.fillText(r.avg_rating != null ? r.avg_rating.toFixed(1) : '-', 560, y + 36);

        ctx.textAlign = 'left';
    }

    // Footer
    ctx.fillStyle = '#8899b0';
    ctx.font = '12px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('Generated by Chelsea Voting Bot', 300, 760);
    ctx.fillText(new Date().toLocaleDateString(), 300, 780);

    return canvas;
}

async function shareResultCard(pollId) {
    // New flow: open the variant picker, let the user pick A/B/C, then
    // generate + share. Old single-variant generation is preserved as
    // generateCardCommunityTop5 for callers that may still reference it.
    return openShareCardPicker(pollId);
}

function downloadBlob(blob) {
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a');
    a.href = url;
    a.download = 'chelsea-results.png';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    toast(t('share.card_ready'));
}

/* ═══ SSE Live Updates ═══ */

function connectSSE(pollId) {
    // Disconnect previous
    disconnectSSE();

    try {
        var es = new EventSource('/api/stream/poll/' + pollId);
        state.sseConnection = es;
        state._sseRetryCount = 0;

        es.addEventListener('connected', function(e) {
            var data = JSON.parse(e.data);
            console.log('SSE connected to poll:', data.poll_id);
            state._sseRetryCount = 0;
        });

        es.addEventListener('vote_count', function(e) {
            var data = JSON.parse(e.data);
            state.liveVoterCount = data.count || 0;
            updateLiveCounter();
            // Show toast if it's a new vote (not initial load)
            if (data.user) {
                showSSEToast(data.user + ' ' + t('live.just_voted'));
            }
        });

        es.onerror = function() {
            var retryCount = state._sseRetryCount || 0;
            // Exponential backoff: 2s, 4s, 8s, 16s, 32s (capped at 60s)
            var delay = Math.min(2000 * Math.pow(2, retryCount), 60000);
            state._sseRetryCount = retryCount + 1;
            setTimeout(function() {
                if (state.sseConnection === es) {
                    disconnectSSE();
                    // Only reconnect if still on vote tab and under max retries
                    if ((location.hash === '#vote' || location.hash === '') && state._sseRetryCount <= 10) {
                        connectSSE(pollId);
                    }
                }
            }, delay);
        };
    } catch (e) {
        console.warn('SSE not available:', e);
    }
}

function disconnectSSE() {
    if (state.sseConnection) {
        state.sseConnection.close();
        state.sseConnection = null;
    }
    state._sseRetryCount = 0;
}

function updateLiveCounter() {
    var el = document.getElementById('live-voter-count');
    if (!el) return;
    var prev = parseInt(el.textContent, 10);
    var next = state.liveVoterCount;
    el.textContent = next;
    // Only pulse when the number actually changed (avoid pulsing on first paint
    // or when SSE re-sends the same value).
    if (!isNaN(prev) && next !== prev) {
        el.classList.remove('bumping');
        // Force reflow so re-adding the class re-triggers the animation.
        // eslint-disable-next-line no-unused-expressions
        el.offsetHeight;
        el.classList.add('bumping');
        setTimeout(function() { el.classList.remove('bumping'); }, 500);
    }
}

function showSSEToast(message) {
    // Create a small slide-in notification
    var existing = document.querySelector('.sse-toast');
    if (existing) existing.remove();

    var toast_el = document.createElement('div');
    toast_el.className = 'sse-toast';
    toast_el.textContent = message;
    document.body.appendChild(toast_el);

    setTimeout(function() {
        if (toast_el.parentNode) toast_el.remove();
    }, 3000);
}

/* ═══════════════════════════════════════════════════
   TAB — STATS (Season Stats + Voter Leaderboard)
   ═══════════════════════════════════════════════════ */

async function renderStatsTab() {
    var loading = document.getElementById('stats-loading');
    var content = document.getElementById('stats-content');
    loading.style.display = 'block';
    content.style.display = 'none';

    var seasonData = null;
    var leaderboardData = null;

    try {
        var results = await Promise.all([
            api('/api/season-stats'),
            api('/api/leaderboard')
        ]);
        if (results[0].success) seasonData = results[0];
        if (results[1].success) leaderboardData = results[1];
    } catch (e) {
        /* ignore */
    }

    loading.style.display = 'none';
    content.style.display = 'block';

    var html = '';

    // Challenges section
    var challengesHtml = '';
    try {
        var challengesResp = await api('/api/challenges');
        if (challengesResp.success && challengesResp.challenges && challengesResp.challenges.length > 0) {
            challengesHtml += '<div class="admin-section"><h3>' + t('challenges.title') + '</h3>';
            for (var ci = 0; ci < challengesResp.challenges.length; ci++) {
                var ch = challengesResp.challenges[ci];
                var progress = ch.user_progress || 0;
                var target = ch.target || 1;
                var pct = Math.min(100, Math.round(progress / target * 100));
                var isCompleted = ch.user_completed === 1;
                var typeLabel = ch.type === 'daily' ? t('challenges.daily') : (ch.type === 'weekly' ? t('challenges.weekly') : ch.type);
                var timeLeft = '';
                if (ch.end_time) {
                    var remaining = ch.end_time - Date.now() / 1000;
                    if (remaining > 0) {
                        var hours = Math.floor(remaining / 3600);
                        var days = Math.floor(hours / 24);
                        timeLeft = days > 0 ? days + 'd ' + (hours % 24) + 'h' : hours + 'h';
                    }
                }
                var borderColor = ch.type === 'daily' ? 'var(--gold)' : (ch.type === 'weekly' ? 'var(--blue)' : 'var(--success)');
                challengesHtml += '<div class="challenge-card" style="border-left-color:' + borderColor + ';">';
                challengesHtml += '<div class="challenge-header">';
                challengesHtml += '<span class="challenge-type-badge">' + typeLabel + '</span>';
                if (isCompleted) {
                    challengesHtml += '<span class="challenge-badge-complete">&#10003; ' + t('challenges.completed') + '</span>';
                } else if (timeLeft) {
                    challengesHtml += '<span class="challenge-time">' + t('challenges.time_remaining') + ': ' + timeLeft + '</span>';
                }
                challengesHtml += '</div>';
                challengesHtml += '<div class="challenge-title">' + escapeHtml(ch.title) + '</div>';
                if (ch.description) {
                    challengesHtml += '<div class="challenge-desc">' + escapeHtml(ch.description) + '</div>';
                }
                challengesHtml += '<div class="challenge-progress-bar"><div class="challenge-progress-fill' + (isCompleted ? ' complete' : '') + '" style="width:' + pct + '%;"></div></div>';
                challengesHtml += '<div class="challenge-footer">';
                challengesHtml += '<span class="challenge-progress-text">' + progress + '/' + target + '</span>';
                challengesHtml += '<span class="challenge-reward">' + t('challenges.reward') + ': +' + ch.reward_xp + ' XP</span>';
                challengesHtml += '</div>';
                challengesHtml += '</div>';
            }
            challengesHtml += '</div>';
        } else {
            challengesHtml += '<div class="admin-section"><h3>' + t('challenges.title') + '</h3>';
            challengesHtml += '<div class="player-meta">' + t('challenges.no_active') + '</div></div>';
        }
    } catch (e) {
        /* challenges load failed - skip section */
    }
    html += challengesHtml;

    // Season Stats section - Team of the Season
    html += '<div class="admin-section"><h3>' + t('stats.team_of_season') + '</h3>';
    if (seasonData && seasonData.team_of_season && seasonData.team_of_season.length > 0) {
        var teamOfSeason = seasonData.team_of_season;
        var maxAvg = 0;
        for (var i = 0; i < teamOfSeason.length; i++) {
            if (teamOfSeason[i].avg_rating > maxAvg) maxAvg = teamOfSeason[i].avg_rating;
        }
        if (maxAvg === 0) maxAvg = 1;

        html += '<div class="bar-chart-container">';
        for (var i = 0; i < teamOfSeason.length; i++) {
            var player = teamOfSeason[i];
            var widthPct = (player.avg_rating / maxAvg * 100).toFixed(1);
            var podiumClass = i === 0 ? ' podium-1' : (i === 1 ? ' podium-2' : (i === 2 ? ' podium-3' : ''));
            var barDelay = (i * 60) + 'ms';
            html += '<div class="bar-chart-row' + podiumClass + '">' +
                '<div style="width:24px;text-align:center;font-weight:700;font-size:0.8rem;color:var(--gold);flex-shrink:0;">' + (i + 1) + '</div>' +
                '<div class="bar-chart-label">' + player.name + '</div>' +
                '<div class="bar-chart-bar" style="--bar-target:' + widthPct + '%;--bar-delay:' + barDelay + ';background:' + (i < 3 ? 'var(--gold)' : 'var(--blue)') + ';"></div>' +
                '<div class="bar-chart-value" data-counter="' + (player.avg_rating != null ? player.avg_rating.toFixed(1) : '0') + '">0</div>' +
            '</div>';
        }
        html += '</div>';
    } else {
        html += '<div class="player-meta">' + t('history.no_polls') + '</div>';
    }
    html += '</div>';

    // Player Form section
    if (seasonData && seasonData.players && seasonData.players.length > 0) {
        html += '<div class="admin-section"><h3>' + t('stats.player_form') + '</h3>';
        var players = seasonData.players;
        for (var i = 0; i < Math.min(players.length, 15); i++) {
            var p = players[i];
            var formDots = '';
            var form5 = p.form_last_5 || [];
            if (form5.length > 0) {
                formDots = '<div class="form-dots">';
                var avgAll = p.avg_rating || 0;
                for (var f = 0; f < form5.length; f++) {
                    var dotClass = 'neutral';
                    if (form5[f] > avgAll) dotClass = 'good';
                    else if (form5[f] < avgAll) dotClass = 'bad';
                    formDots += '<div class="form-dot ' + dotClass + '" title="' + form5[f].toFixed(1) + '"></div>';
                }
                formDots += '</div>';
            }
            html += '<div class="leaderboard-row">' +
                '<div class="leaderboard-rank">' + (i < 3 ? '<span class="medal-emoji">' + ['\uD83E\uDD47','\uD83E\uDD48','\uD83E\uDD49'][i] + '</span>' : (i + 1)) + '</div>' +
                '<div class="leaderboard-info">' +
                    '<div class="leaderboard-name">' + p.name + '</div>' +
                    '<div class="leaderboard-stats">' + (p.avg_rating != null ? p.avg_rating.toFixed(1) : '-') + ' avg &middot; ' + (p.matches_played || 0) + ' matches</div>' +
                '</div>' +
                formDots +
            '</div>';
        }
        html += '</div>';
    }

    // Voter Leaderboard section
    html += '<div class="admin-section"><h3>' + t('stats.leaderboard') + '</h3>';
    if (leaderboardData && leaderboardData.leaderboard && leaderboardData.leaderboard.length > 0) {
        var lb = leaderboardData.leaderboard;
        for (var i = 0; i < lb.length; i++) {
            var voter = lb[i];
            var initial = (voter.first_name || voter.username || '?')[0].toUpperCase();
            var displayName = voter.first_name || voter.username || ('User ' + voter.user_id);
            var totalVotes = voter.total_votes || 0;
            var consistency = voter.consistency_score != null ? voter.consistency_score : 0;
            var consistencyPct = Math.round(consistency * 100);

            // Build badge pills
            var badges = '';
            if (totalVotes >= 50) badges += '<span class="badge badge-gold" style="font-size:0.65rem;padding:2px 6px;">' + t('profile.badges.veteran') + '</span>';
            if (totalVotes >= 20 && totalVotes < 50) badges += '<span class="badge badge-blue" style="font-size:0.65rem;padding:2px 6px;">' + t('profile.badges.active') + '</span>';
            if (consistency >= 0.7) badges += '<span class="badge badge-success" style="font-size:0.65rem;padding:2px 6px;">' + t('profile.badges.seer') + '</span>';
            if (consistency <= 0.3 && totalVotes > 0) badges += '<span class="badge badge-danger" style="font-size:0.65rem;padding:2px 6px;">' + t('profile.badges.rebel') + '</span>';

            var avatarMarkup = getAvatarHtml(voter.avatar || 0, 32, voter.telegram_photo_url);
            html += '<div class="leaderboard-row">' +
                '<div class="leaderboard-rank">' + (i < 3 ? '<span class="medal-emoji">' + ['\uD83E\uDD47','\uD83E\uDD48','\uD83E\uDD49'][i] + '</span>' : (i + 1)) + '</div>' +
                '<div style="flex-shrink:0;">' + avatarMarkup + '</div>' +
                '<div class="leaderboard-info">' +
                    '<div class="leaderboard-name">' + displayName + ' ' + badges + '</div>' +
                    '<div class="leaderboard-stats">' + totalVotes + ' ' + t('profile.votes_count').toLowerCase() + '</div>' +
                '</div>' +
                '<div style="text-align:right;">' +
                    '<div class="consistency-bar"><div class="consistency-fill" style="width:' + consistencyPct + '%;"></div></div>' +
                    '<div style="font-size:0.7rem;color:var(--text-dim);margin-top:2px;">' + consistencyPct + '%</div>' +
                '</div>' +
            '</div>';
        }
    } else {
        html += '<div class="player-meta">' + t('history.no_polls') + '</div>';
    }
    html += '</div>';

    // Mini Games section
    html += renderMiniGamesSection();

    content.innerHTML = html;
}

function renderMiniGamesSection() {
    var html = '<div class="admin-section"><h3>' + t('games.heading') + '</h3>';

    if (!state.currentPoll) {
        html += '<div class="player-meta">' + t('vote.no_active_polls') + '</div></div>';
        return html;
    }

    var matchTitle = state.currentPoll.title || t('vote.current_match');
    var matchId = state.currentPoll.match_id || state.currentPoll.poll_id;

    // Guess the Score
    html += '<div class="mini-game-card">';
    html += '<h4>' + t('games.guess_score') + '</h4>';
    html += '<div class="player-meta mb-8">' + matchTitle + '</div>';
    if (state.scoreGuess) {
        html += '<div class="player-meta">' + t('games.your_guess') + ': ' + state.scoreGuess.home + ' - ' + state.scoreGuess.away + '</div>';
        html += '<span class="badge badge-success">' + t('games.already_submitted') + '</span>';
    } else {
        html += '<div class="score-inputs">' +
            '<input type="number" class="score-input" id="score-home" min="0" max="20" value="0" placeholder="0">' +
            '<span class="score-vs">-</span>' +
            '<input type="number" class="score-input" id="score-away" min="0" max="20" value="0" placeholder="0">' +
            '</div>';
        html += '<button class="btn-primary" style="margin-top:8px" onclick="submitScoreGuess()">' + t('games.submit_score') + '</button>';
    }
    html += '</div>';

    // Guess the Lineup
    html += '<div class="mini-game-card">';
    html += '<h4>' + t('games.guess_lineup') + '</h4>';
    html += '<div class="player-meta mb-8">' + matchTitle + '</div>';
    if (state.lineupGuess) {
        html += '<div class="player-meta">' + t('games.your_guess') + ':</div>';
        var guessNames = [];
        for (var lg = 0; lg < state.lineupGuess.length; lg++) {
            for (var lp = 0; lp < state.players.length; lp++) {
                if (state.players[lp].id === state.lineupGuess[lg]) {
                    guessNames.push(state.players[lp].name);
                    break;
                }
            }
        }
        html += '<div class="player-meta">' + guessNames.join(', ') + '</div>';
        html += '<span class="badge badge-success">' + t('games.already_submitted') + '</span>';
    } else {
        html += '<div class="lineup-counter" id="lineup-counter">' + t('games.selected_count') + ': 0 ' + t('games.of_eleven') + '</div>';
        html += '<div class="lineup-grid" id="lineup-grid">';
        for (var li = 0; li < state.players.length; li++) {
            var lpl = state.players[li];
            html += '<label class="lineup-option" data-player-id="' + lpl.id + '">' +
                '<input type="checkbox" value="' + lpl.id + '" onchange="updateLineupCount()">' +
                '<span>' + lpl.name + '</span></label>';
        }
        html += '</div>';
        html += '<button class="btn-primary" style="margin-top:8px" onclick="submitLineupGuess()">' + t('games.submit_lineup') + '</button>';
    }
    html += '</div>';

    // Mini-game Results
    html += '<div class="mini-game-card">';
    html += '<h4>' + t('games.results') + '</h4>';
    html += '<div id="mini-game-results"><div class="player-meta">' + t('common.loading') + '</div></div>';
    html += '</div>';

    html += '</div>';

    // Load mini-game results asynchronously
    setTimeout(function() { loadMiniGameResults(matchId); }, 100);

    return html;
}

function updateLineupCount() {
    var checkboxes = document.querySelectorAll('#lineup-grid input[type="checkbox"]');
    var count = 0;
    checkboxes.forEach(function(cb) {
        if (cb.checked) count++;
        cb.closest('.lineup-option').classList.toggle('selected', cb.checked);
    });
    var counter = document.getElementById('lineup-counter');
    if (counter) counter.textContent = t('games.selected_count') + ': ' + count + ' ' + t('games.of_eleven');
}

async function submitScoreGuess() {
    var homeEl = document.getElementById('score-home');
    var awayEl = document.getElementById('score-away');
    if (!homeEl || !awayEl) return;
    var home = parseInt(homeEl.value) || 0;
    var away = parseInt(awayEl.value) || 0;
    var matchId = state.currentPoll.match_id || state.currentPoll.poll_id;
    try {
        var data = await api('/api/mini-game/guess', {
            method: 'POST',
            body: JSON.stringify({ match_id: matchId, game_type: 'score', guess: JSON.stringify({ home: home, away: away }) })
        });
        if (data.success) {
            state.scoreGuess = { home: home, away: away };
            toast(t('games.score_submitted'));
            renderStatsTab();
        } else {
            toast(data.error || t('common.error'));
        }
    } catch (e) { toast(t('common.error')); }
}

async function submitLineupGuess() {
    var checkboxes = document.querySelectorAll('#lineup-grid input[type="checkbox"]:checked');
    var selectedIds = [];
    checkboxes.forEach(function(cb) { selectedIds.push(cb.value); });
    if (selectedIds.length !== 11) {
        toast(t('games.select_exactly_11'));
        return;
    }
    var matchId = state.currentPoll.match_id || state.currentPoll.poll_id;
    try {
        var data = await api('/api/mini-game/guess', {
            method: 'POST',
            body: JSON.stringify({ match_id: matchId, game_type: 'lineup', guess: JSON.stringify({ players: selectedIds }) })
        });
        if (data.success) {
            state.lineupGuess = selectedIds;
            toast(t('games.lineup_submitted'));
            renderStatsTab();
        } else {
            toast(data.error || t('common.error'));
        }
    } catch (e) { toast(t('common.error')); }
}

async function loadMiniGameResults(matchId) {
    var container = document.getElementById('mini-game-results');
    if (!container) return;
    try {
        var data = await api('/api/mini-game/results/' + matchId);
        if (data.success && data.results && data.results.length > 0) {
            var rhtml = '';
            for (var i = 0; i < data.results.length; i++) {
                var r = data.results[i];
                rhtml += '<div class="leaderboard-row">' +
                    '<div class="leaderboard-info">' +
                        '<div class="leaderboard-name">' + (r.username || r.user_id) + '</div>' +
                        '<div class="leaderboard-stats">' + r.game_type + ' - ' + (r.result || '-') + '</div>' +
                    '</div>' +
                    '<div style="text-align:right;color:var(--gold);font-weight:700;">' + (r.points || 0) + ' ' + t('predictions.points') + '</div>' +
                '</div>';
            }
            container.innerHTML = rhtml;
        } else {
            container.innerHTML = '<div class="player-meta">' + t('history.no_polls') + '</div>';
        }
    } catch (e) {
        container.innerHTML = '<div class="player-meta">' + t('common.error') + '</div>';
    }
}

/* ═══════════════════════════════════════════════════
   TAB 3 — PROFILE
   ═══════════════════════════════════════════════════ */

async function renderProfileTab() {
    const loading = document.getElementById('profile-loading');
    const content = document.getElementById('profile-content');
    loading.style.display = 'block';
    content.style.display = 'none';

    try {
        const data = await api('/api/profile/me');
        if (data.success) state.myProfile = data.profile;
    } catch (e) { /* ignore */ }

    var xpData = null;
    try {
        var xpRes = await api('/api/xp/me');
        if (xpRes.success) xpData = xpRes;
    } catch (e) { /* ignore */ }

    loading.style.display = 'none';
    content.style.display = 'block';

    const p = state.myProfile || {};
    const customId = p.custom_id || p.auto_id || '—';
    const votesCount = p.total_votes || 0;
    const canCustomize = votesCount >= 10;

    // Build badges
    let badges = '';
    if (state.isAdmin) badges += `<span class="badge badge-gold">${t('profile.badges.admin')}</span>`;
    if (votesCount >= 50) badges += `<span class="badge badge-gold">${t('profile.badges.veteran')}</span>`;
    if (votesCount >= 20) badges += `<span class="badge badge-blue">${t('profile.badges.active')}</span>`;
    if (canCustomize) badges += `<span class="badge badge-success">${t('profile.custom_id_available')}</span>`;

    // XP section HTML
    var xpHtml = '';
    if (xpData) {
        var totalXp = (xpData.xp && xpData.xp.total_xp) || 0;
        var level = (xpData.xp && xpData.xp.level) || 1;
        var xpToNext = (xpData.xp && xpData.xp.xp_to_next_level) || 0;
        var progressPct = (xpData.xp && xpData.xp.progress_pct) || 0;
        var levelName = '';
        if (totalXp >= 1500) levelName = t('levels.legend');
        else if (totalXp >= 500) levelName = t('levels.ultras');
        else if (totalXp >= 100) levelName = t('levels.fan');
        else levelName = t('levels.novice');

        xpHtml = '<div class="xp-section">' +
            '<span class="xp-level-badge">' + t('xp.level') + ' ' + level + ' - ' + levelName + '</span>' +
            '<div class="xp-progress-container">' +
                '<div class="xp-progress-fill" style="width:' + progressPct + '%"></div>' +
                '<div class="xp-progress-text">' + totalXp + ' / ' + (totalXp + xpToNext) + ' XP</div>' +
            '</div>' +
            '<div class="xp-stats">' +
                '<span>' + t('xp.total_xp') + ': ' + totalXp + '</span>' +
                '<span>' + t('xp.next_level') + ': ' + xpToNext + ' XP</span>' +
            '</div>' +
            '</div>';
    }

    // Streak section HTML
    var streakHtml = '';
    if (xpData) {
        var currentStreak = (xpData.streak && xpData.streak.current_streak) || 0;
        var maxStreak = (xpData.streak && xpData.streak.max_streak) || 0;
        var fireClass = currentStreak >= 5 ? ' streak-fire' : '';
        var fireEmoji = currentStreak >= 5 ? '\uD83D\uDD25' : '\uD83D\uDD25';
        // When streak >= 5, render the fire with rising ember particles around it.
        var fireBlock;
        if (currentStreak >= 5) {
            fireBlock = '<div class="streak-fire-wrap" style="font-size:2rem;">' +
                            '<span class="streak-fire" style="position:relative;z-index:2;">' + fireEmoji + '</span>' +
                            '<span class="ember"></span>' +
                            '<span class="ember"></span>' +
                            '<span class="ember"></span>' +
                            '<span class="ember"></span>' +
                            '<span class="ember"></span>' +
                        '</div>';
        } else {
            fireBlock = '<div style="font-size:2rem;opacity:0.6;">' + fireEmoji + '</div>';
        }
        streakHtml = '<div class="streak-section">' +
            fireBlock +
            '<div class="streak-info">' +
                '<div class="streak-current">' + t('xp.streak_current') + ': ' + currentStreak + (currentStreak >= 5 ? ' ' + t('xp.fire_streak') : '') + '</div>' +
                '<div class="streak-record">' + t('xp.streak_record') + ': ' + maxStreak + '</div>' +
            '</div>' +
            '</div>';
    }

    // Awards section HTML
    var awardsHtml = '';
    var userAwards = (state.myProfile && state.myProfile.awards) || [];
    if (userAwards.length > 0) {
        var awardTypeEmojis = {
            'most_accurate': '\uD83C\uDFAF',
            'most_active': '\uD83D\uDD25',
            'best_predictor': '\uD83D\uDD2E',
            'streak_record': '\uD83D\uDCAA'
        };
        var awardTypeKeys = {
            'most_accurate': 'awards.most_accurate',
            'most_active': 'awards.most_active',
            'best_predictor': 'awards.best_predictor',
            'streak_record': 'awards.streak_record'
        };
        awardsHtml = '<div class="awards-section"><h3>\uD83C\uDFC6 ' + t('awards.title') + '</h3>';
        for (var i = 0; i < userAwards.length; i++) {
            var aw = userAwards[i];
            var emoji = awardTypeEmojis[aw.award_type] || '\uD83C\uDFC6';
            var label = t(awardTypeKeys[aw.award_type] || 'awards.title');
            var monthLabel = aw.month || '';
            awardsHtml += '<div class="award-item">' +
                '<span class="award-badge">' + emoji + '</span>' +
                '<span class="award-text">' + label + '</span>' +
                '<span class="award-month">' + monthLabel + '</span>' +
                '</div>';
        }
        awardsHtml += '</div>';
    } else {
        awardsHtml = '<div class="awards-section"><h3>\uD83C\uDFC6 ' + t('awards.title') + '</h3>' +
            '<div class="player-meta">' + t('awards.no_awards') + '</div></div>';
    }

    // Bonds section: love/hate progression with players. Computed on
    // the backend (db.get_player_bonds) from the user's full vote
    // history; we only render here.
    var bondsHtml = renderBondsSection(state.myProfile && state.myProfile.bonds);

    // Avatar source: ONLY Telegram profile photo. The chelsea-themed emoji
    // grid was removed — TG photo is the single source of truth, with a
    // graceful initials fallback for users who didn't grant Telegram photo
    // access (or who connected via demo mode without a real account).
    const heroPhotoUrl = p.telegram_photo_url || state.telegramPhotoUrl || '';
    const heroAvatarHtml = getAvatarHtml(0, 96, heroPhotoUrl);

    content.innerHTML = `
        <!-- XP Progress -->
        ${xpHtml}

        <!-- Streak Display -->
        ${streakHtml}

        <!-- Awards Display -->
        ${awardsHtml}

        <!-- Player bonds (love/hate progression) -->
        ${bondsHtml}

        <!-- Profile hero (avatar + name + ID badge) -->
        <div class="profile-hero">
            <div class="profile-hero-bg"></div>
            <div class="profile-hero-content">
                <div class="profile-hero-avatar">${heroAvatarHtml}</div>
                <h2 class="profile-hero-name">${escapeHtml((state.firstName || '') + ' ' + (state.lastName || '')).trim() || '—'}</h2>
                ${state.username ? `<a class="profile-username-pill" href="https://t.me/${encodeURIComponent(state.username)}" target="_blank" rel="noopener">@${escapeHtml(state.username)}</a>` : ''}
                <div class="profile-id-row">
                    <span class="profile-id-label">ID</span>
                    <button class="profile-id-badge${p.custom_id ? ' is-custom' : ''}" onclick="copyMyId()" title="${t('social.copy_link')}">
                        <span class="profile-id-value">${escapeHtml(customId)}</span>
                        <span class="profile-id-copy">${ICON_COPY}</span>
                    </button>
                </div>
                ${badges ? `<div class="profile-hero-badges">${badges}</div>` : ''}
            </div>
        </div>

        <div class="stats-grid">
            <div class="stat-card">
                <strong data-counter="${votesCount}">0</strong>
                <span class="player-meta">${t('profile.votes_count')}</span>
            </div>
            <div class="stat-card">
                <strong data-counter="${p.avg_rating_given || 0}">0</strong>
                <span class="player-meta">${t('profile.avg_rating')}</span>
            </div>
        </div>
        ${canCustomize ? `
        <div class="admin-section mt-16">
            <h3>${t('profile.custom_id')}</h3>
            <div class="player-meta mb-8">${t('profile.custom_id_hint')}</div>
            <div class="form-group">
                <label>${t('profile.custom_id_label')}</label>
                <input type="text" id="custom-id-input" placeholder="chelsea-${p.auto_id ? p.auto_id.split('-')[1] : '001'}" value="${p.custom_id || ''}">
            </div>
            <button class="btn-primary" onclick="saveCustomId()">${t('profile.save')}</button>
        </div>` : ''}

        <!-- Compare with Friend -->
        <div class="compare-section">
            <h3>${t('social.compare_heading')}</h3>
            <div class="form-group">
                <label>${t('social.friend_id')}</label>
                <input type="number" id="compare-friend-id" placeholder="123456">
            </div>
            <button class="btn-secondary" onclick="compareFriend()">${t('social.compare_btn')}</button>
            <div id="compare-result"></div>
        </div>
    `;

    // Load and render heatmap
    loadHeatmap();
}

/* ═══════════════════════════════════════════════════
   Bonds — render the love/hate progression in profile
   ═══════════════════════════════════════════════════
   Backend (db.get_player_bonds) returns:
     { love: [{ player_id, player_name, photo_url, count, tier }, …],
       hate: [...same shape...] }
   Each `tier` is 1..4 mapped to thresholds 5/10/25/50.
   We render two stacked rows of badges, gold for love and red-ish for
   hate, with a "next tier" tip when the user is between tiers.        */
var BOND_THRESHOLDS = [5, 10, 25, 50];

function _bondTierLabel(kind, tier) {
    return t('bonds.' + kind + '_tier_' + tier) || '';
}

/* Pluralise the "N times" counter using simple ru/en rules. ru has
   three forms (1 раз / 2-4 раза / 5+ раз); en collapses to one/many.   */
function _bondCounter(n) {
    var lang = (typeof getLang === 'function' ? getLang() : 'ru');
    if (lang === 'ru') {
        var n100 = n % 100;
        var n10 = n % 10;
        if (n100 >= 11 && n100 <= 14) return t('bonds.counter_many');
        if (n10 === 1) return t('bonds.counter_one');
        if (n10 >= 2 && n10 <= 4) return t('bonds.counter_few');
        return t('bonds.counter_many');
    }
    return n === 1 ? t('bonds.counter_one') : t('bonds.counter_many');
}

/* Find the next un-reached threshold so we can show "5 more to next
   tier" hints. Returns null when the user is already at the cap.       */
function _nextThreshold(count) {
    for (var i = 0; i < BOND_THRESHOLDS.length; i++) {
        if (count < BOND_THRESHOLDS[i]) return BOND_THRESHOLDS[i];
    }
    return null;
}

function _renderBondCard(kind, item) {
    var photoUrl = item.photo_url || '';
    var initial = (item.player_name || '?')[0].toUpperCase();
    var photoHtml = photoUrl
        ? '<img class="bond-photo" src="' + escapeHtml(photoUrl) + '" alt="" loading="lazy" onerror="this.replaceWith(Object.assign(document.createElement(\'div\'),{className:\'bond-photo bond-photo-fallback\',textContent:\'' + escapeHtml(initial) + '\'}))">'
        : '<div class="bond-photo bond-photo-fallback">' + escapeHtml(initial) + '</div>';
    var tierLabel = _bondTierLabel(kind, item.tier);
    var nextThr = _nextThreshold(item.count);
    var progressLine = '';
    if (nextThr) {
        var pct = Math.min(100, Math.round(item.count * 100 / nextThr));
        progressLine = '<div class="bond-progress" title="' + (nextThr - item.count) + '">' +
            '<div class="bond-progress-fill" style="width:' + pct + '%"></div></div>' +
            '<div class="bond-progress-meta">' + item.count + ' / ' + nextThr + '</div>';
    } else {
        progressLine = '<div class="bond-progress-meta bond-maxed">' + item.count + ' \u2605</div>';
    }
    return '<div class="bond-card bond-' + kind + ' bond-tier-' + item.tier + '">' +
        photoHtml +
        '<div class="bond-info">' +
            '<div class="bond-name">' + escapeHtml(item.player_name || '') + '</div>' +
            '<div class="bond-tier">' + escapeHtml(tierLabel) + '</div>' +
            '<div class="bond-count">' + item.count + ' ' + _bondCounter(item.count) + '</div>' +
            progressLine +
        '</div>' +
    '</div>';
}

function renderBondsSection(bonds) {
    var love = (bonds && bonds.love) || [];
    var hate = (bonds && bonds.hate) || [];
    if (!love.length && !hate.length) {
        return '<div class="bonds-section">' +
            '<h3>\uD83D\uDC95 ' + t('bonds.title') + '</h3>' +
            '<div class="player-meta">' + t('bonds.no_bonds') + '</div>' +
        '</div>';
    }
    var html = '<div class="bonds-section">' +
        '<h3>\uD83D\uDC95 ' + t('bonds.title') + '</h3>';
    if (love.length) {
        html += '<div class="bonds-group">' +
            '<div class="bonds-group-heading"><span class="bond-glyph love">\u2665</span>' +
            ' ' + t('bonds.love_heading') + '</div>' +
            '<div class="bonds-grid">';
        for (var i = 0; i < love.length; i++) html += _renderBondCard('love', love[i]);
        html += '</div></div>';
    }
    if (hate.length) {
        html += '<div class="bonds-group">' +
            '<div class="bonds-group-heading"><span class="bond-glyph hate">\u2620</span>' +
            ' ' + t('bonds.hate_heading') + '</div>' +
            '<div class="bonds-grid">';
        for (var i = 0; i < hate.length; i++) html += _renderBondCard('hate', hate[i]);
        html += '</div></div>';
    }
    html += '</div>';
    return html;
}

async function loadHeatmap() {
    try {
        var data = await api('/api/heatmap/me');
        if (!data.success || !data.players || data.players.length === 0) return;

        var container = document.getElementById('profile-content');
        if (!container) return;

        var html = '<div class="heatmap-section">';
        html += '<h3>' + t('heatmap.title') + '</h3>';

        // Heatmap grid
        html += '<div class="heatmap-grid">';
        for (var i = 0; i < data.players.length; i++) {
            var p = data.players[i];
            var cellClass = 'heatmap-neutral';
            if (p.bias === 'high') cellClass = 'heatmap-high';
            else if (p.bias === 'low') cellClass = 'heatmap-low';
            html += '<div class="heatmap-cell ' + cellClass + '">' +
                '<div class="heatmap-cell-name">' + (p.name || '').split(' ').pop() + '</div>' +
                '<div class="heatmap-cell-value">' + (p.user_avg != null ? p.user_avg.toFixed(1) : '-') + '</div></div>';
        }
        html += '</div>';

        // Insights
        if (data.insights && data.insights.length > 0) {
            html += '<h4 style="color:var(--text-dim);font-size:0.85rem;margin:12px 0 8px;">' + t('heatmap.your_patterns') + '</h4>';
            for (var ii = 0; ii < data.insights.length; ii++) {
                html += '<div class="insight-card"><span class="insight-icon">\uD83D\uDCA1</span><span>' + data.insights[ii] + '</span></div>';
            }
        }
        html += '</div>';

        container.insertAdjacentHTML('beforeend', html);
    } catch (e) { /* ignore */ }
}

// `selectAvatar()` and `isAvatarUnlocked()` were removed alongside the
// chelsea-themed emoji avatar grid. Telegram profile photo (or initials
// fallback) is now the single source of truth for the user avatar.
// `getAvatarHtml()` is preserved because it's still used to render
// avatars inside leaderboards and admin user lists, with the same
// photo-url-first contract.

async function saveCustomId() {
    const input = document.getElementById('custom-id-input');
    const newId = input.value.trim();
    if (!newId) { toast(t('profile.enter_id')); return; }
    try {
        const data = await api('/api/profile/update', {
            method: 'POST',
            body: JSON.stringify({ custom_id: newId }),
        });
        if (data.success) {
            toast(t('profile.id_saved'));
            state.myProfile.custom_id = newId;
        } else {
            toast(data.error || t('common.error'));
        }
    } catch (e) { toast(t('toast.error_saving')); }
}

async function compareFriend() {
    var friendIdEl = document.getElementById('compare-friend-id');
    if (!friendIdEl || !friendIdEl.value) { toast(t('social.friend_id')); return; }
    var friendId = friendIdEl.value.trim();
    var myId = state.userId;
    var container = document.getElementById('compare-result');
    if (!container) return;
    container.innerHTML = '<div class="player-meta">' + t('common.loading') + '</div>';
    try {
        var data = await api('/api/compare/' + myId + '/' + friendId);
        if (data.success) {
            container.innerHTML = '<div class="compare-result">' +
                '<div class="similarity-score">' + Math.round(data.similarity_score || 0) + '%</div>' +
                '<div class="similarity-label">' + t('social.similarity') + '</div>' +
                '<div class="player-meta mt-8">' + t('social.common_polls') + ': ' + (data.common_polls || 0) + '</div>' +
                '</div>';
        } else {
            container.innerHTML = '<div class="player-meta">' + (data.error || t('common.error')) + '</div>';
        }
    } catch (e) {
        container.innerHTML = '<div class="player-meta">' + t('common.error') + '</div>';
    }
}

function copyMyId() {
    // Copy the bare ID (no referral text) — the badge shows just the ID,
    // so what users paste should match what they tapped on. Falls back to
    // the numeric Telegram user_id if neither custom nor auto IDs exist.
    var p = state.myProfile || {};
    var code = p.custom_id || p.auto_id || String(state.userId || '');
    if (!code) return;
    var done = function () {
        toast(t('profile.id_copied') || t('social.copied'));
        try { if (tg && tg.HapticFeedback) tg.HapticFeedback.impactOccurred('light'); } catch (_) {}
        var btn = document.querySelector('.profile-id-badge');
        if (btn) {
            btn.classList.add('copied');
            setTimeout(function () { btn.classList.remove('copied'); }, 600);
        }
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(code).then(done).catch(function () { toast(t('common.error')); });
    } else {
        try {
            var ta = document.createElement('textarea');
            ta.value = code;
            ta.style.position = 'fixed';
            ta.style.opacity = '0';
            document.body.appendChild(ta);
            ta.select();
            document.execCommand('copy');
            document.body.removeChild(ta);
            done();
        } catch (_) {
            toast(t('common.error'));
        }
    }
}

/* ═══════════════════════════════════════════════════
   TAB 4 — SETTINGS
   ═══════════════════════════════════════════════════ */

function renderSettingsTab() {
    const content = document.getElementById('settings-content');
    const backgrounds = state.config.default_background_url;
    const myBg = state.myProfile?.background_url || '';

    var soundsEnabled = true;
    try { var sv = localStorage.getItem('chelsea_sounds'); soundsEnabled = (sv !== '0' && sv !== 'false'); } catch (e) {}

    // Local user-uploaded background (base64 in localStorage). Read it
    // here so the markup can render a preview tile if one is set, and
    // a Reset button to nuke it.
    var userBg = '';
    try { userBg = localStorage.getItem('chelsea_user_bg') || ''; } catch (e) {}
    var bgPreviewHtml = userBg
        ? `<div class="bg-uploader-preview" style="background-image:url(${JSON.stringify(userBg)})"></div>`
        : `<div class="bg-uploader-preview bg-uploader-empty">${t('settings.background_empty')}</div>`;

    content.innerHTML = `
        <!-- Language -->
        <div class="admin-section">
            <h3>\uD83C\uDF10 ${t('settings.language')}</h3>
            <div class="form-group">
                <select id="setting-lang" onchange="onLangChange(this.value)">
                    <option value="ru" ${getLang() === 'ru' ? 'selected' : ''}>Русский</option>
                    <option value="en" ${getLang() === 'en' ? 'selected' : ''}>English</option>
                </select>
            </div>
        </div>

        <!-- Theme -->
        <div class="admin-section">
            <h3>\uD83C\uDFA8 ${t('settings.theme')}</h3>
            <div class="theme-grid">
                <button class="theme-card" data-theme-pick="dark" onclick="setTheme('dark')">
                    <span class="theme-card-swatch theme-swatch-dark"></span>
                    <span class="theme-card-label">\uD83C\uDF19 ${t('settings.theme_dark')}</span>
                </button>
                <button class="theme-card" data-theme-pick="light" onclick="setTheme('light')">
                    <span class="theme-card-swatch theme-swatch-light"></span>
                    <span class="theme-card-label">\u2600\uFE0F ${t('settings.theme_light')}</span>
                </button>
                <button class="theme-card" data-theme-pick="stamford-bridge" onclick="setTheme('stamford-bridge')">
                    <span class="theme-card-swatch theme-swatch-stamford"></span>
                    <span class="theme-card-label">\uD83E\uDD81 ${t('settings.theme_stamford')}</span>
                </button>
                <button class="theme-card" data-theme-pick="vintage" onclick="setTheme('vintage')">
                    <span class="theme-card-swatch theme-swatch-vintage"></span>
                    <span class="theme-card-label">\uD83C\uDFFA ${t('settings.theme_vintage')}</span>
                </button>
                <button class="theme-card" data-theme-pick="stadium" onclick="setTheme('stadium')">
                    <span class="theme-card-swatch theme-swatch-stadium"></span>
                    <span class="theme-card-label">\uD83C\uDFDF\uFE0F ${t('settings.theme_stadium')}</span>
                </button>
                <button class="theme-card" data-theme-pick="auto" onclick="setTheme('auto')">
                    <span class="theme-card-swatch theme-swatch-auto"></span>
                    <span class="theme-card-label">\uD83D\uDCF1 ${t('settings.theme_auto')}</span>
                </button>
            </div>
        </div>

        <!-- Sound Effects -->
        <div class="admin-section">
            <h3>\uD83D\uDD0A ${t('customization.sound_effects')}</h3>
            <div class="toggle-row">
                <span class="toggle-label">${t('customization.sound_effects')}</span>
                <label class="switch">
                    <input type="checkbox" id="setting-sound" ${soundsEnabled ? 'checked' : ''}
                        onchange="toggleSound(this.checked)">
                    <span class="switch-track"><span class="switch-thumb"></span></span>
                </label>
            </div>
        </div>

        <!-- Notification Preferences -->
        <div class="admin-section">
            <h3>\uD83D\uDD14 ${t('notifications.prefs_title')}</h3>
            <div class="toggle-row">
                <span class="toggle-label">${t('notifications.remind_before_close')}</span>
                <label class="switch">
                    <input type="checkbox" id="notif-remind" onchange="saveNotifPrefs()">
                    <span class="switch-track"><span class="switch-thumb"></span></span>
                </label>
            </div>
            <div class="toggle-row">
                <span class="toggle-label">${t('notifications.new_poll')}</span>
                <label class="switch">
                    <input type="checkbox" id="notif-new-poll" onchange="saveNotifPrefs()">
                    <span class="switch-track"><span class="switch-thumb"></span></span>
                </label>
            </div>
            <div class="toggle-row">
                <span class="toggle-label">${t('notifications.results_ready')}</span>
                <label class="switch">
                    <input type="checkbox" id="notif-results" onchange="saveNotifPrefs()">
                    <span class="switch-track"><span class="switch-thumb"></span></span>
                </label>
            </div>
        </div>

        <!-- Background -->
        <div class="admin-section">
            <h3>\uD83D\uDDBC\uFE0F ${t('settings.background')}</h3>
            ${bgPreviewHtml}
            <div class="bg-uploader">
                <label class="bg-uploader-pick">
                    \uD83D\uDCF7 ${t('settings.background_pick')}
                    <input type="file" accept="image/*" onchange="onBgFileChosen(this)">
                </label>
                ${userBg ? `<button class="bg-uploader-clear" onclick="clearLocalBg()">\u2716 ${t('settings.background_clear')}</button>` : ''}
            </div>
            <div class="bg-uploader-hint">${t('settings.background_local_hint')}</div>
        </div>

        <!-- Config info (public) -->
        <div class="admin-section">
            <h3>\uD83D\uDCCB ${t('settings.info')}</h3>
            <div class="player-meta">
                ${t('settings.voting_period')}: ${state.config.voting_period_hours} ${t('settings.hours')}<br>
                ${t('settings.max_rating')}: ${state.config.max_rating}
            </div>
        </div>
    `;

    // Load notification preferences
    loadNotifPrefs();

    // Highlight currently-selected theme card (read from <html data-theme>
    // which boot.js seeded from localStorage on initial load).
    var currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
    document.querySelectorAll('.theme-card').forEach(function (b) {
        b.classList.toggle('selected', b.getAttribute('data-theme-pick') === currentTheme);
    });
}

function toggleSound(enabled) {
    try { localStorage.setItem('chelsea_sounds', enabled ? '1' : '0'); } catch (e) {}
    if (enabled) playSound('click');
}

async function loadNotifPrefs() {
    try {
        var data = await api('/api/notifications/prefs');
        if (data.success && data.prefs) {
            state.notificationPrefs = data.prefs;
            var remindEl = document.getElementById('notif-remind');
            var newPollEl = document.getElementById('notif-new-poll');
            var resultsEl = document.getElementById('notif-results');
            if (remindEl) remindEl.checked = !!data.prefs.remind_before_close;
            if (newPollEl) newPollEl.checked = !!data.prefs.new_poll_notify;
            if (resultsEl) resultsEl.checked = !!data.prefs.results_notify;
        }
    } catch (e) { /* ignore */ }
}

async function saveNotifPrefs() {
    var remindEl = document.getElementById('notif-remind');
    var newPollEl = document.getElementById('notif-new-poll');
    var resultsEl = document.getElementById('notif-results');
    var prefs = {
        remind_before_close: remindEl && remindEl.checked ? 1 : 0,
        new_poll_notify: newPollEl && newPollEl.checked ? 1 : 0,
        results_notify: resultsEl && resultsEl.checked ? 1 : 0,
    };
    try {
        await api('/api/notifications/prefs', {
            method: 'POST',
            body: JSON.stringify(prefs),
        });
        state.notificationPrefs = prefs;
        toast(t('toast.saved'));
    } catch (e) { toast(t('toast.error_saving')); }
}

async function saveSetting(key, value) {
    try {
        await api('/api/profile/update', {
            method: 'POST',
            body: JSON.stringify({ [key]: value }),
        });
        toast(t('toast.saved'));
    } catch (e) { toast(t('toast.error_saving')); }
}

function onLangChange(lang) {
    saveSetting('language', lang);
    setLang(lang);
}

function setTheme(theme) {
    // Auto mode follows the OS via prefers-color-scheme; we still tag
    // the root element so other code (setTheme highlight, theme-card
    // selection) can reflect the user's pick.
    document.documentElement.setAttribute('data-theme', theme);
    try { localStorage.setItem('chelsea_theme', theme); } catch (e) {}
    // Reflect selection on the theme-card buttons (visible-only when
    // the settings tab is rendered; querySelectorAll silently no-ops
    // otherwise).
    document.querySelectorAll('.theme-card').forEach(function (b) {
        b.classList.toggle('selected', b.getAttribute('data-theme-pick') === theme);
    });
    try { if (tg && tg.HapticFeedback) tg.HapticFeedback.selectionChanged(); } catch (_) {}
}

async function saveBackground() {
    const url = document.getElementById('setting-bg-url').value.trim();
    await saveSetting('background_url', url);
}

/* ── Local-only background uploader ──────────────────────────────
   Storage strategy: we read the file via FileReader, downscale + crop
   in-memory via a hidden canvas (max 1080×1920, JPEG q=0.82), then
   stash the resulting base64 data URL in localStorage["chelsea_user_bg"].
   That keeps the payload around 200-500KB which is well under the
   ~5MB localStorage budget on every browser we care about. The image
   is applied immediately as a CSS variable on <html>, so users see
   it without a reload.
   ──────────────────────────────────────────────────────────────── */

const BG_MAX_W = 1080;          // capped long-edge after downscale
const BG_MAX_H = 1920;
const BG_JPEG_QUALITY = 0.82;
const BG_MAX_BYTES = 600 * 1024; // hard ceiling — refuse if can't compress under

function onBgFileChosen(input) {
    var file = input && input.files && input.files[0];
    if (!file) return;
    if (!/^image\//.test(file.type)) {
        toast(t('settings.background_invalid'));
        input.value = '';
        return;
    }
    var reader = new FileReader();
    reader.onerror = function () {
        toast(t('common.error'));
        input.value = '';
    };
    reader.onload = function (e) {
        var img = new Image();
        img.onload = function () {
            try {
                var dataUrl = _resizeImageToDataUrl(img, BG_MAX_W, BG_MAX_H, BG_JPEG_QUALITY);
                if (dataUrl.length > BG_MAX_BYTES * 1.4 /* base64 overhead */) {
                    // Try one more pass at lower quality before giving up.
                    dataUrl = _resizeImageToDataUrl(img, Math.round(BG_MAX_W * 0.8), Math.round(BG_MAX_H * 0.8), 0.7);
                }
                localStorage.setItem('chelsea_user_bg', dataUrl);
                applyLocalBg();
                toast(t('toast.saved'));
                renderSettingsTab();
            } catch (err) {
                console.warn('bg upload failed', err);
                toast(t('settings.background_too_large') || t('common.error'));
            } finally {
                input.value = '';
            }
        };
        img.onerror = function () {
            toast(t('common.error'));
            input.value = '';
        };
        img.src = e.target.result;
    };
    reader.readAsDataURL(file);
}

function _resizeImageToDataUrl(img, maxW, maxH, quality) {
    // Preserve aspect ratio: shrink so neither dimension exceeds the cap,
    // but never upscale a small image. iPhone Live Photos / DSLR shots
    // routinely arrive at 4032×3024 — without this they'd blow past the
    // localStorage budget.
    var w = img.naturalWidth || img.width;
    var h = img.naturalHeight || img.height;
    var scale = Math.min(1, maxW / w, maxH / h);
    var dstW = Math.round(w * scale);
    var dstH = Math.round(h * scale);
    var canvas = document.createElement('canvas');
    canvas.width = dstW;
    canvas.height = dstH;
    var ctx = canvas.getContext('2d');
    ctx.drawImage(img, 0, 0, dstW, dstH);
    return canvas.toDataURL('image/jpeg', quality);
}

function applyLocalBg() {
    var bg = '';
    try { bg = localStorage.getItem('chelsea_user_bg') || ''; } catch (e) {}
    var html = document.documentElement;
    if (bg) {
        // Quote the URL so any commas/parens inside the data URL don't
        // break the CSS parser; data URLs *can* technically contain them.
        html.style.setProperty('--user-bg', 'url("' + bg.replace(/"/g, '\\"') + '")');
        html.setAttribute('data-user-bg', '1');
    } else {
        html.style.removeProperty('--user-bg');
        html.removeAttribute('data-user-bg');
    }
}

function clearLocalBg() {
    try { localStorage.removeItem('chelsea_user_bg'); } catch (e) {}
    applyLocalBg();
    renderSettingsTab();
    toast(t('toast.saved'));
}

/* ── Font preset (admin-controlled, applied to <html>) ──────────── */
function applyFontPreset(preset) {
    var allowed = { system: 1, sport: 1, classic: 1, modern: 1 };
    var p = allowed[preset] ? preset : 'system';
    document.documentElement.setAttribute('data-font', p);
}

/* ═══════════════════════════════════════════════════
   TAB 5 — ADMIN  (visible only to admins)
   ═══════════════════════════════════════════════════ */

async function renderAdminTab() {
    if (!state.isAdmin) {
        document.getElementById('admin-content').innerHTML = '<div class="msg error">' + t('admin.access_denied') + '</div>';
        return;
    }

    const content = document.getElementById('admin-content');
    content.innerHTML = '<div class="loading">' + t('admin.loading') + '</div>';

    try {
        const [cfgRes, pollsRes, adminsRes, logsRes, bgRes, schedulerRes, monitoringRes] = await Promise.all([
            api('/api/config'),
            api('/api/admin/polls?limit=20'),
            api('/api/admin/admins'),
            api('/api/admin/logs?limit=50'),
            api('/api/backgrounds'),
            api('/api/admin/scheduler/status'),
            api('/api/admin/monitoring'),
        ]);
        if (cfgRes.success) state.config = { ...state.config, ...cfgRes.config };
        if (schedulerRes.success && schedulerRes.scheduler) {
            state.config.notify_chat_id = schedulerRes.scheduler.notify_chat_id || '';
        }
        if (monitoringRes.success) state.monitoring = monitoringRes;
        state.allPolls = pollsRes.polls || [];
        state.allAdmins = adminsRes.admins || [];
        state.allLogs   = logsRes.logs   || [];
        state.allBackgrounds = bgRes.backgrounds || [];
    } catch (e) { /* use stale data */ }

    content.innerHTML = `
        ${renderAdminMonitoring()}
        ${renderAdminConfig()}
        ${renderAdminAutomation()}
        ${renderAdminChannel()}
        ${renderAdminPolls()}
        ${renderAdminAdmins()}
        ${renderAdminCustomId()}
        ${renderAdminVotesView()}
        ${renderAdminVoteAdjust()}
        ${renderAdminResetVote()}
        ${renderAdminRemoveVotes()}
        ${renderAdminChallenges()}
        ${renderAdminBackgrounds()}
        ${renderAdminLogs()}
    `;

    // Add event listeners for dynamic elements
    document.getElementById('btn-create-poll')?.addEventListener('click', createPoll);
    document.getElementById('btn-add-admin')?.addEventListener('click', addAdmin);
    document.getElementById('btn-load-votes')?.addEventListener('click', adminLoadVotes);
    document.getElementById('btn-reset-vote')?.addEventListener('click', adminResetVote);
    document.getElementById('btn-remove-votes')?.addEventListener('click', adminRemoveUserVotes);
    document.getElementById('btn-create-challenge')?.addEventListener('click', adminCreateChallenge);
    document.getElementById('btn-toggle-challenge-on')?.addEventListener('click', () => adminToggleChallenge(true));
    document.getElementById('btn-toggle-challenge-off')?.addEventListener('click', () => adminToggleChallenge(false));
}

function renderAdminMonitoring() {
    var m = state.monitoring || {};
    var lastRun = m.last_scheduler_run ? new Date(parseFloat(m.last_scheduler_run) * 1000).toLocaleString() : '---';
    var elapsed = m.last_scheduler_run ? (Date.now() / 1000 - parseFloat(m.last_scheduler_run)) : null;
    var statusOk = elapsed !== null && elapsed < 3600;
    var statusColor = statusOk ? '#4caf50' : '#f44336';
    var statusText = statusOk ? t('monitoring.status_ok') : t('monitoring.status_warning');
    var errors = m.api_error_count || 0;

    return '<div class="admin-section">' +
        '<h3>\uD83D\uDCCA ' + t('monitoring.title') + '</h3>' +
        '<div class="grid-2">' +
            '<div class="form-group">' +
                '<label>' + t('monitoring.last_run') + '</label>' +
                '<div>' + lastRun + '</div>' +
            '</div>' +
            '<div class="form-group">' +
                '<label>' + t('monitoring.status') + '</label>' +
                '<div style="color:' + statusColor + ';font-weight:bold;">' + statusText + '</div>' +
            '</div>' +
        '</div>' +
        '<div class="grid-2">' +
            '<div class="form-group">' +
                '<label>' + t('monitoring.errors') + '</label>' +
                '<div>' + errors + '</div>' +
            '</div>' +
            '<div class="form-group">' +
                '<label>' + t('monitoring.users') + '</label>' +
                '<div>' + (m.total_users || 0) + '</div>' +
            '</div>' +
        '</div>' +
        '<div class="grid-2">' +
            '<div class="form-group">' +
                '<label>' + t('monitoring.votes') + '</label>' +
                '<div>' + (m.total_votes || 0) + '</div>' +
            '</div>' +
            '<div class="form-group">' +
                '<label>' + t('monitoring.polls') + '</label>' +
                '<div>' + (m.total_polls || 0) + '</div>' +
            '</div>' +
        '</div>' +
        '<button class="btn-primary" onclick="resetApiErrors()">' + t('monitoring.reset_errors') + '</button>' +
    '</div>';
}

async function resetApiErrors() {
    var res = await api('/api/admin/monitoring/reset', { method: 'POST' });
    if (res.success) {
        state.monitoring = state.monitoring || {};
        state.monitoring.api_error_count = 0;
        renderAdminTab();
    }
}

function renderAdminConfig() {
    return `
        <div class="admin-section">
            <h3>\u2699\uFE0F ${t('admin.config.heading')}</h3>
            <div class="grid-2">
                <div class="form-group">
                    <label>${t('admin.config.max_scale')}</label>
                    <input type="number" id="cfg-maxrating" value="${state.config.max_rating}">
                </div>
                <div class="form-group">
                    <label>${t('admin.config.bot_name')}</label>
                    <input type="text" id="cfg-botname" value="${state.config.bot_name || ''}">
                </div>
            </div>
            <div class="form-group">
                <label>${t('admin.config.global_bg')}</label>
                <input type="text" id="cfg-bg" value="${state.config.default_background_url || ''}">
            </div>
            <!--
              Font preset is global: admin picks here, every user gets it on
              their next /api/config load. The four presets cover system
              default + three Cyrillic-friendly Google Font pairings.
            -->
            <div class="form-group">
                <label>${t('admin.config.font')}</label>
                <select id="cfg-font">
                    <option value="system" ${ (state.config.font_preset || 'system') === 'system' ? 'selected' : '' }>${t('admin.config.font_system')}</option>
                    <option value="sport"  ${ state.config.font_preset === 'sport'   ? 'selected' : '' }>${t('admin.config.font_sport')}</option>
                    <option value="classic" ${ state.config.font_preset === 'classic' ? 'selected' : '' }>${t('admin.config.font_classic')}</option>
                    <option value="modern" ${ state.config.font_preset === 'modern'  ? 'selected' : '' }>${t('admin.config.font_modern')}</option>
                </select>
                <div class="player-meta mt-8">${t('admin.config.font_hint')}</div>
            </div>
            <button class="btn-primary" onclick="adminSaveConfig()">\uD83D\uDCBE ${t('admin.config.save')}</button>
        </div>`;
}

function renderAdminAutomation() {
    return `
        <div class="admin-section">
            <h3>\uD83E\uDD16 ${t('admin.automation.heading')}</h3>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="cfg-auto-create" ${state.config.auto_create_polls == '1' ? 'checked' : ''}>
                    ${t('admin.automation.auto_create')}
                </label>
            </div>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="cfg-auto-close" ${state.config.auto_close_polls == '1' ? 'checked' : ''}>
                    ${t('admin.automation.auto_close')}
                </label>
            </div>
            <div class="form-group">
                <label>${t('admin.automation.voting_period')}</label>
                <input type="number" id="cfg-period" value="${state.config.voting_period_hours}" min="1" max="168">
            </div>
            <div class="form-group">
                <label>
                    <input type="checkbox" id="cfg-auto-notify" ${state.config.auto_notify == '1' ? 'checked' : ''}>
                    ${t('admin.automation.notifications')}
                </label>
            </div>
            <div class="form-group">
                <label>${t('admin.automation.chat_id')}</label>
                <input type="text" id="cfg-notify-chat" value="${state.config.notify_chat_id || ''}" placeholder="-1001234567890">
            </div>
        </div>`;
}

function renderAdminChannel() {
    var chatId = state.config.results_chat_id || '';
    var template = state.config.results_template || 'top5';
    var announce = state.config.announce_matches || '1';

    return '<div class="admin-section">' +
        '<h3>\uD83D\uDCE2 ' + t('admin.channel.heading') + '</h3>' +
        '<div class="form-group">' +
            '<label>' + t('admin.channel.chat_id') + '</label>' +
            '<input type="text" id="channel-chat-id" value="' + chatId + '" placeholder="-100123456789">' +
        '</div>' +
        '<div class="form-group">' +
            '<label>' + t('admin.channel.template') + '</label>' +
            '<select id="channel-template">' +
                '<option value="top3"' + (template === 'top3' ? ' selected' : '') + '>' + t('admin.channel.top3') + '</option>' +
                '<option value="top5"' + (template === 'top5' ? ' selected' : '') + '>' + t('admin.channel.top5') + '</option>' +
                '<option value="full"' + (template === 'full' ? ' selected' : '') + '>' + t('admin.channel.full') + '</option>' +
            '</select>' +
        '</div>' +
        '<div class="toggle-row">' +
            '<span class="toggle-label">' + t('admin.channel.announce') + '</span>' +
            '<input type="checkbox" id="channel-announce"' + (announce === '1' ? ' checked' : '') + '>' +
        '</div>' +
        '<button class="btn-primary" onclick="saveChannelConfig()">' + t('admin.channel.save') + '</button>' +
    '</div>';
}

function renderAdminPolls() {
    let pollsHtml = state.allPolls.map(p =>
        `<div class="card" style="padding:10px 14px;display:flex;align-items:center;gap:10px;">
            <span style="flex:1"><strong>${p.title || '—'}</strong> <span class="player-meta">(${p.status})</span></span>
            ${p.status === 'open'
                ? `<button class="btn-danger" style="padding:6px 12px;font-size:0.75rem" onclick="adminClosePoll('${p.poll_id}')">${t('admin.polls.close')}</button>`
                : `<span class="badge badge-blue">${t('admin.polls.closed')}</span>`}
        </div>`
    ).join('');

    return `
        <div class="admin-section">
            <h3>\uD83D\uDDF3\uFE0F ${t('admin.polls.heading')}</h3>
            <div class="form-group">
                <label>${t('admin.polls.match_id')}</label>
                <input type="text" id="newpoll-matchid" placeholder="chelsea_001">
            </div>
            <div class="form-group">
                <label>${t('admin.polls.title')}</label>
                <input type="text" id="newpoll-title" placeholder="Chelsea vs Liverpool">
            </div>
            <button class="btn-primary" id="btn-create-poll">\u2795 ${t('admin.polls.create')}</button>
            <div class="mt-16"><strong>${t('admin.polls.all_polls')}</strong></div>
            ${pollsHtml || '<div class="player-meta mt-8">' + t('admin.polls.no_polls') + '</div>'}
        </div>`;
}

function renderAdminAdmins() {
    let adminsHtml = state.allAdmins.map(a =>
        `<div class="card" style="padding:8px 14px;display:flex;align-items:center;gap:10px;">
            <div style="flex-shrink:0;">${getAvatarHtml(0, 32, a.telegram_photo_url)}</div>
            <span style="flex:1">${a.username || a.first_name || a.user_id} <span class="player-meta">(ID: ${a.user_id})</span></span>
            <button class="btn-danger" style="padding:4px 10px;font-size:0.75rem"
                onclick="adminRemoveAdmin(${a.user_id})">${t('admin.admins.remove')}</button>
        </div>`
    ).join('');

    return `
        <div class="admin-section">
            <h3>\uD83D\uDC65 ${t('admin.admins.heading')}</h3>
            <div class="grid-2">
                <div class="form-group">
                    <label>${t('admin.admins.new_user_id')}</label>
                    <input type="number" id="newadmin-id" placeholder="123456789">
                </div>
                <div class="form-group">
                    <label>${t('admin.admins.username')}</label>
                    <input type="text" id="newadmin-username" placeholder="username">
                </div>
            </div>
            <button class="btn-secondary mt-8" id="btn-add-admin">${t('admin.admins.add')}</button>
            <div class="mt-16"><strong>${t('admin.admins.current')}</strong></div>
            ${adminsHtml || '<div class="player-meta mt-8">' + t('admin.admins.none') + '</div>'}
        </div>`;
}

function renderAdminCustomId() {
    return `
        <div class="admin-section">
            <h3>\uD83D\uDD11 ${t('admin.custom_id.heading')}</h3>
            <p class="player-meta mb-8">${t('admin.custom_id.hint')}</p>
            <div class="grid-2">
                <div class="form-group">
                    <label>${t('admin.custom_id.user_id')}</label>
                    <input type="number" id="cid-user-id" placeholder="123456789">
                </div>
                <div class="form-group">
                    <label>${t('admin.custom_id.custom_id')}</label>
                    <input type="text" id="cid-custom-id" placeholder="drakelovc" maxlength="32">
                </div>
            </div>
            <button class="btn-primary mt-8" onclick="adminSetCustomId()">${t('admin.custom_id.apply')}</button>
        </div>`;
}

function renderAdminVoteAdjust() {
    return `
        <div class="admin-section">
            <h3>\uD83D\uDCDD ${t('admin.vote_adjust.heading')}</h3>
            <div class="form-group">
                <label>${t('admin.vote_adjust.poll_id')}</label>
                <input type="text" id="adj-poll-id" placeholder="abc123">
            </div>
            <div class="grid-2">
                <div class="form-group">
                    <label>${t('admin.vote_adjust.user_id')}</label>
                    <input type="number" id="adj-user-id" placeholder="123456">
                </div>
                <div class="form-group">
                    <label>${t('admin.vote_adjust.player_id')}</label>
                    <input type="text" id="adj-player-id" placeholder="player_1">
                </div>
            </div>
            <div class="form-group">
                <label>${t('admin.vote_adjust.new_rating')} (0—${state.config.max_rating})</label>
                <input type="number" id="adj-rating" min="0" max="${state.config.max_rating}" placeholder="7">
            </div>
            <button class="btn-primary" onclick="adminAdjustVote()">${t('admin.vote_adjust.apply')}</button>
            <p class="player-meta mt-8">${t('admin.vote_adjust.note')}</p>
        </div>`;
}

function renderAdminBackgrounds() {
    let bgHtml = state.allBackgrounds.map(b =>
        `<div class="card" style="padding:8px 14px;">
            <div style="display:flex;align-items:center;gap:10px;">
                <img src="${b.url}" style="width:60px;height:40px;object-fit:cover;border-radius:4px;" alt="">
                <span style="flex:1">${b.label} ${b.is_default ? '\u2B50' : ''}</span>
            </div>
        </div>`
    ).join('');

    return `
        <div class="admin-section">
            <h3>\uD83D\uDDBC\uFE0F ${t('admin.backgrounds.heading')}</h3>
            <div class="form-group">
                <label>${t('admin.backgrounds.label')}</label>
                <input type="text" id="newbg-label" placeholder="${t('admin.backgrounds.label')}">
            </div>
            <div class="form-group">
                <label>${t('admin.backgrounds.url')}</label>
                <input type="text" id="newbg-url" placeholder="https://...">
            </div>
            <label style="display:flex;align-items:center;gap:8px;margin:8px 0">
                <input type="checkbox" id="newbg-default"> ${t('admin.backgrounds.make_default')}
            </label>
            <button class="btn-secondary mt-8" onclick="adminAddBackground()">${t('admin.backgrounds.add')}</button>
            <div class="mt-16"><strong>${t('admin.backgrounds.available')}</strong></div>
            ${bgHtml || '<div class="player-meta mt-8">' + t('admin.backgrounds.none') + '</div>'}
        </div>`;
}

function renderAdminLogs() {
    let logsHtml = state.allLogs.map(l =>
        `<div class="log-entry">
            <span class="log-action">${l.action}</span>
            <span class="log-time">${tsToDate(l.timestamp)}</span>
            <div>${t('admin.logs.admin_label')}: ${l.admin_user_id}${l.target_user_id ? ' \u2192 ' + t('admin.logs.target_label') + ': ' + l.target_user_id : ''}</div>
            ${l.details ? `<div class="player-meta">${l.details.substring(0, 120)}</div>` : ''}
        </div>`
    ).join('');

    return `
        <div class="admin-section">
            <h3>\uD83D\uDCDC ${t('admin.logs.heading')}</h3>
            <div style="max-height:400px;overflow-y:auto;">
                ${logsHtml || '<div class="player-meta">' + t('admin.logs.empty') + '</div>'}
            </div>
        </div>`;
}

// ──── Admin action handlers ────

async function adminSaveConfig() {
    const body = {
        voting_period_hours: document.getElementById('cfg-period').value,
        max_rating: document.getElementById('cfg-maxrating').value,
        bot_name: document.getElementById('cfg-botname').value,
        default_background_url: document.getElementById('cfg-bg').value,
        font_preset: document.getElementById('cfg-font').value,
        auto_create_polls: document.getElementById('cfg-auto-create').checked ? '1' : '0',
        auto_close_polls: document.getElementById('cfg-auto-close').checked ? '1' : '0',
        auto_notify: document.getElementById('cfg-auto-notify').checked ? '1' : '0',
        notify_chat_id: document.getElementById('cfg-notify-chat').value.trim(),
    };
    try {
        await api('/api/admin/config', { method: 'POST', body: JSON.stringify(body) });
        toast(t('admin.config_saved_toast'));
        await loadConfig(); await renderAdminTab();
    } catch (e) { toast(t('common.error')); }
}

async function createPoll() {
    const body = {
        match_id: document.getElementById('newpoll-matchid').value.trim(),
        title: document.getElementById('newpoll-title').value.trim(),
        max_rating: parseInt(document.getElementById('cfg-maxrating').value) || state.config.max_rating,
    };
    if (!body.match_id) { toast(t('admin.polls.match_id')); return; }
    if (!body.title) body.title = `Match ${body.match_id}`;
    try {
        const data = await api('/api/admin/poll/create', { method: 'POST', body: JSON.stringify(body) });
        if (data.success) {
            toast(t('admin.polls.poll_created_toast'));
            document.getElementById('newpoll-matchid').value = '';
            document.getElementById('newpoll-title').value = '';
            await renderAdminTab();
        } else { toast(data.error || t('common.error')); }
    } catch (e) { toast(t('common.error')); }
}

async function adminClosePoll(pollId) {
    if (!confirm(t('admin.polls.close_confirm'))) return;
    try {
        await api(`/api/admin/poll/close/${pollId}`, { method: 'POST' });
        toast(t('admin.polls.poll_closed_toast'));
        await renderAdminTab();
    } catch (e) { toast(t('common.error')); }
}

async function addAdmin() {
    const uid = parseInt(document.getElementById('newadmin-id').value);
    const uname = document.getElementById('newadmin-username').value.trim();
    if (!uid) { toast(t('admin.admins.enter_id')); return; }
    try {
        const data = await api('/api/admin/admins/add', { method: 'POST', body: JSON.stringify({ user_id: uid, username: uname }) });
        if (data.success) {
            toast(t('admin.admins.added_toast'));
            document.getElementById('newadmin-id').value = '';
            await renderAdminTab();
        } else { toast(data.error || t('common.error')); }
    } catch (e) { toast(t('common.error')); }
}

async function adminRemoveAdmin(uid) {
    if (!confirm(t('admin.admins.remove_confirm'))) return;
    try {
        await api('/api/admin/admins/remove', { method: 'POST', body: JSON.stringify({ user_id: uid }) });
        toast(t('admin.admins.removed_toast'));
        await renderAdminTab();
    } catch (e) { toast(t('common.error')); }
}

async function adminSetCustomId() {
    // Owner / admin tool: assign or clear custom_id for any user. Empty
    // input clears the field. Validation happens server-side too — we
    // pre-validate here only to surface a friendlier toast immediately.
    const uid = parseInt((document.getElementById('cid-user-id') || {}).value);
    const customId = ((document.getElementById('cid-custom-id') || {}).value || '').trim();
    if (!uid || isNaN(uid)) { toast(t('admin.custom_id.fill_user_id')); return; }
    if (customId && !/^[A-Za-z0-9._\-]{2,32}$/.test(customId)) {
        toast(t('admin.custom_id.invalid_format'));
        return;
    }
    try {
        const data = await api('/api/admin/profile/custom-id', {
            method: 'POST',
            body: JSON.stringify({ user_id: uid, custom_id: customId }),
        });
        if (data.success) {
            toast(t(customId ? 'admin.custom_id.applied_toast' : 'admin.custom_id.cleared_toast'));
            const idEl = document.getElementById('cid-user-id');
            const valEl = document.getElementById('cid-custom-id');
            if (idEl) idEl.value = '';
            if (valEl) valEl.value = '';
        } else {
            // Map known errors to localized toasts; everything else falls
            // through to the generic message so the user at least knows
            // something failed.
            if (data.error === 'custom_id already taken') toast(t('admin.custom_id.taken_toast'));
            else if (data.error === 'profile not found') toast(t('admin.custom_id.profile_not_found'));
            else if (String(data.error || '').indexOf('custom_id must be') === 0) toast(t('admin.custom_id.invalid_format'));
            else toast(data.error || t('common.error'));
        }
    } catch (e) { toast(t('common.error')); }
}

async function adminAdjustVote() {
    const body = {
        poll_id: document.getElementById('adj-poll-id').value.trim(),
        user_id: parseInt(document.getElementById('adj-user-id').value),
        player_id: document.getElementById('adj-player-id').value.trim(),
        new_rating: parseInt(document.getElementById('adj-rating').value),
    };
    if (!body.poll_id || !body.user_id || !body.player_id || isNaN(body.new_rating)) {
        toast(t('admin.vote_adjust.fill_all')); return;
    }
    try {
        const data = await api('/api/admin/vote/adjust', { method: 'POST', body: JSON.stringify(body) });
        if (data.success) {
            toast(t('admin.vote_adjust.applied_toast'));
            document.getElementById('adj-poll-id').value = '';
            document.getElementById('adj-user-id').value = '';
            document.getElementById('adj-player-id').value = '';
            document.getElementById('adj-rating').value = '';
            await renderAdminTab();
        } else { toast(data.error || t('common.error')); }
    } catch (e) { toast(t('common.error')); }
}

// ──── New admin sections (votes view, reset/remove vote, challenges) ────

function renderAdminVotesView() {
    return `
        <div class="admin-section">
            <h3>\uD83D\uDCCB ${t('admin.votes_view.heading')}</h3>
            <div class="form-group">
                <label>${t('admin.votes_view.poll_id')}</label>
                <input type="text" id="votes-view-poll-id" placeholder="poll_1735862400">
            </div>
            <button class="btn-primary" id="btn-load-votes">${t('admin.votes_view.load')}</button>
            <div id="votes-view-summary" class="player-meta mt-8"></div>
            <div id="votes-view-list" class="mt-8"></div>
        </div>`;
}

async function adminLoadVotes() {
    const pollId = document.getElementById('votes-view-poll-id').value.trim();
    if (!pollId) { toast(t('admin.votes_view.enter_poll_id')); return; }
    const summary = document.getElementById('votes-view-summary');
    const list = document.getElementById('votes-view-list');
    summary.textContent = t('admin.loading');
    list.innerHTML = '';
    try {
        const data = await api(`/api/admin/votes/${encodeURIComponent(pollId)}`);
        if (!data.success) { toast(data.error || t('common.error')); summary.textContent = ''; return; }
        const byUser = data.by_user || [];
        const totalVotes = (data.votes || []).length;
        summary.textContent = `${t('admin.votes_view.total_voters')}: ${data.total_voters || 0} \u00B7 ${t('admin.votes_view.total_votes')}: ${totalVotes}`;
        if (byUser.length === 0) {
            list.innerHTML = '<div class="player-meta mt-8">' + t('admin.votes_view.empty') + '</div>';
            return;
        }
        list.innerHTML = byUser.map(u => {
            const ratingsHtml = Object.entries(u.votes || {})
                .sort((a, b) => b[1] - a[1])
                .map(([pid, rate]) => `<span class="badge badge-blue" style="margin:2px 4px 2px 0;font-size:0.7rem;">${escapeHtml(pid)}: ${rate}</span>`)
                .join('');
            const idLabel = u.custom_id || u.auto_id || u.user_id;
            return `<div class="card" style="padding:8px 12px;margin-bottom:6px;">
                <div><strong>${escapeHtml(u.username || ('User ' + u.user_id))}</strong>
                <span class="player-meta">(${escapeHtml(String(idLabel))} \u00B7 ID: ${u.user_id})</span></div>
                <div style="margin-top:4px;">${ratingsHtml}</div>
            </div>`;
        }).join('');
    } catch (e) { toast(t('common.error')); summary.textContent = ''; }
}

function renderAdminResetVote() {
    return `
        <div class="admin-section">
            <h3>\uD83D\uDD04 ${t('admin.reset_vote.heading')}</h3>
            <p class="player-meta">${t('admin.reset_vote.note')}</p>
            <div class="form-group">
                <label>${t('admin.vote_adjust.poll_id')}</label>
                <input type="text" id="reset-vote-poll-id" placeholder="poll_1735862400">
            </div>
            <div class="form-group">
                <label>${t('admin.vote_adjust.user_id')}</label>
                <input type="number" id="reset-vote-user-id" placeholder="123456">
            </div>
            <button class="btn-danger" id="btn-reset-vote">${t('admin.reset_vote.apply')}</button>
        </div>`;
}

async function adminResetVote() {
    const body = {
        poll_id: document.getElementById('reset-vote-poll-id').value.trim(),
        user_id: parseInt(document.getElementById('reset-vote-user-id').value),
    };
    if (!body.poll_id || !body.user_id) { toast(t('admin.vote_adjust.fill_all')); return; }
    if (!confirm(t('admin.reset_vote.confirm') + ' ' + body.user_id + '?')) return;
    try {
        const data = await api('/api/admin/reset-vote', { method: 'POST', body: JSON.stringify(body) });
        if (data.success) {
            toast(t('admin.reset_vote.applied_toast'));
            document.getElementById('reset-vote-poll-id').value = '';
            document.getElementById('reset-vote-user-id').value = '';
            await renderAdminTab();
        } else { toast(data.error || t('common.error')); }
    } catch (e) { toast(t('common.error')); }
}

function renderAdminRemoveVotes() {
    return `
        <div class="admin-section">
            <h3>\uD83D\uDDD1\uFE0F ${t('admin.remove_votes.heading')}</h3>
            <p class="player-meta">${t('admin.remove_votes.note')}</p>
            <div class="form-group">
                <label>${t('admin.vote_adjust.poll_id')}</label>
                <input type="text" id="remove-votes-poll-id" placeholder="poll_1735862400">
            </div>
            <div class="form-group">
                <label>${t('admin.vote_adjust.user_id')}</label>
                <input type="number" id="remove-votes-user-id" placeholder="123456">
            </div>
            <button class="btn-danger" id="btn-remove-votes">${t('admin.remove_votes.apply')}</button>
        </div>`;
}

async function adminRemoveUserVotes() {
    const body = {
        poll_id: document.getElementById('remove-votes-poll-id').value.trim(),
        user_id: parseInt(document.getElementById('remove-votes-user-id').value),
    };
    if (!body.poll_id || !body.user_id) { toast(t('admin.vote_adjust.fill_all')); return; }
    if (!confirm(t('admin.remove_votes.confirm') + ' ' + body.user_id + '?')) return;
    try {
        const data = await api('/api/admin/vote/remove', { method: 'POST', body: JSON.stringify(body) });
        if (data.success) {
            toast(t('admin.remove_votes.applied_toast'));
            document.getElementById('remove-votes-poll-id').value = '';
            document.getElementById('remove-votes-user-id').value = '';
            await renderAdminTab();
        } else { toast(data.error || t('common.error')); }
    } catch (e) { toast(t('common.error')); }
}

function renderAdminChallenges() {
    return `
        <div class="admin-section">
            <h3>\uD83C\uDFC6 ${t('admin.challenges.heading')}</h3>
            <p class="player-meta">${t('admin.challenges.note')}</p>
            <div class="form-group">
                <label>${t('admin.challenges.title_field')}</label>
                <input type="text" id="ch-title" placeholder="${t('admin.challenges.title_placeholder')}">
            </div>
            <div class="form-group">
                <label>${t('admin.challenges.description')}</label>
                <input type="text" id="ch-desc" placeholder="${t('admin.challenges.description_placeholder')}">
            </div>
            <div class="grid-2">
                <div class="form-group">
                    <label>${t('admin.challenges.type')}</label>
                    <input type="text" id="ch-type" value="custom">
                </div>
                <div class="form-group">
                    <label>${t('admin.challenges.target')}</label>
                    <input type="number" id="ch-target" value="1" min="1">
                </div>
            </div>
            <div class="grid-2">
                <div class="form-group">
                    <label>${t('admin.challenges.reward_xp')}</label>
                    <input type="number" id="ch-xp" value="20" min="0">
                </div>
                <div class="form-group">
                    <label>${t('admin.challenges.end_time')}</label>
                    <input type="number" id="ch-end" placeholder="${t('admin.challenges.end_time_placeholder')}">
                </div>
            </div>
            <button class="btn-primary" id="btn-create-challenge">\u2795 ${t('admin.challenges.create')}</button>

            <div class="mt-16"><strong>${t('admin.challenges.toggle_heading')}</strong></div>
            <div class="form-group">
                <label>${t('admin.challenges.challenge_id')}</label>
                <input type="number" id="ch-toggle-id" placeholder="1">
            </div>
            <div style="display:flex;gap:8px;">
                <button class="btn-primary" id="btn-toggle-challenge-on">${t('admin.challenges.activate')}</button>
                <button class="btn-danger" id="btn-toggle-challenge-off">${t('admin.challenges.deactivate')}</button>
            </div>
        </div>`;
}

async function adminCreateChallenge() {
    const body = {
        title: document.getElementById('ch-title').value.trim(),
        description: document.getElementById('ch-desc').value.trim(),
        type: document.getElementById('ch-type').value.trim() || 'custom',
        target: parseInt(document.getElementById('ch-target').value) || 1,
        reward_xp: parseInt(document.getElementById('ch-xp').value) || 20,
    };
    const endVal = document.getElementById('ch-end').value.trim();
    if (endVal) body.end_time = parseFloat(endVal);
    if (!body.title) { toast(t('admin.challenges.title_required')); return; }
    try {
        const data = await api('/api/admin/challenges/create', { method: 'POST', body: JSON.stringify(body) });
        if (data.success) {
            toast(`${t('admin.challenges.created_toast')} #${data.challenge_id}`);
            document.getElementById('ch-title').value = '';
            document.getElementById('ch-desc').value = '';
            document.getElementById('ch-end').value = '';
        } else { toast(data.error || t('common.error')); }
    } catch (e) { toast(t('common.error')); }
}

async function adminToggleChallenge(active) {
    const challenge_id = parseInt(document.getElementById('ch-toggle-id').value);
    if (!challenge_id) { toast(t('admin.challenges.id_required')); return; }
    try {
        const data = await api('/api/admin/challenges/toggle', { method: 'POST', body: JSON.stringify({ challenge_id, active }) });
        if (data.success) {
            toast(active ? t('admin.challenges.activated_toast') : t('admin.challenges.deactivated_toast'));
        } else { toast(data.error || t('common.error')); }
    } catch (e) { toast(t('common.error')); }
}

// ──── End new admin sections ────

async function adminAddBackground() {
    const body = {
        label: document.getElementById('newbg-label').value.trim() || 'background',
        url: document.getElementById('newbg-url').value.trim(),
        is_default: document.getElementById('newbg-default').checked,
    };
    if (!body.url) { toast(t('admin.backgrounds.enter_url')); return; }
    try {
        await api('/api/admin/background/add', { method: 'POST', body: JSON.stringify(body) });
        toast(t('admin.backgrounds.added_toast'));
        document.getElementById('newbg-label').value = '';
        document.getElementById('newbg-url').value = '';
        await renderAdminTab();
    } catch (e) { toast(t('common.error')); }
}

async function saveChannelConfig() {
    var chatId = document.getElementById('channel-chat-id').value.trim();
    var template = document.getElementById('channel-template').value;
    var announce = document.getElementById('channel-announce').checked ? '1' : '0';

    try {
        var data = await api('/api/admin/channel-config', {
            method: 'POST',
            body: JSON.stringify({
                results_chat_id: chatId,
                results_template: template,
                announce_matches: announce
            })
        });
        if (data.success) {
            state.config.results_chat_id = chatId;
            state.config.results_template = template;
            state.config.announce_matches = announce;
            toast(t('admin.channel.saved'));
        } else {
            toast(data.error || t('common.error'));
        }
    } catch (e) { toast(t('common.error')); }
}

/* ═══════════════════════════════════════════════════
   Bootstrap
   ═══════════════════════════════════════════════════ */

// Apply saved theme
const savedTheme = localStorage.getItem('chelsea_theme') || 'dark';
document.documentElement.setAttribute('data-theme', savedTheme);
// Apply user's locally-uploaded background (if any) before first paint
// so they don't see a flash of the default gradient. applyLocalBg is a
// no-op when localStorage is empty/disabled.
try { applyLocalBg(); } catch (e) { /* localStorage may be blocked */ }

// Show admin tab if admin
if (state.isAdmin) {
    document.getElementById('admin-tab-btn').style.display = 'flex';
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
} else {
    init();
}

// ── First-paint entry sequence: header, tabs, content fade in once at boot.
// The CSS rules under `body.app-booting ...` provide the staggered animation;
// we strip the class after the cascade finishes so it doesn't replay later.
document.body.classList.add('app-booting');
window.addEventListener('load', function () {
    setTimeout(function () { document.body.classList.remove('app-booting'); }, 1000);
});

// ── Page micro-parallax: header lifts subtly when content is scrolled.
// Uses requestAnimationFrame to avoid scroll-listener jank on Android.
(function attachHeaderParallax() {
    var hdr = document.getElementById('header');
    if (!hdr) return;
    var ticking = false;
    function update() {
        if (window.scrollY > 8) hdr.classList.add('scrolled');
        else hdr.classList.remove('scrolled');
        ticking = false;
    }
    window.addEventListener('scroll', function () {
        if (!ticking) {
            window.requestAnimationFrame(update);
            ticking = true;
        }
    }, { passive: true });
})();



/* ═════════════════════════════════════════════════════════════════
   Share Card — three canvas-rendered variants
   ─────────────────────────────────────────────────────────────────
   The user opens a picker modal that thumbnails all three variants,
   picks one, then sees a full-size preview with Share / Download.

   Variants:
     A: Lineup formation         1080×1080  — pitch + all players + my ratings
     B: MVP Cover                1080×1080  — single hero player, magazine cover
     C: Stats Vertical (9:16)    1080×1920  — stories-format with top 3 + stats

   Data is fetched once via /api/share/<poll_id>, then all renders draw
   from the same payload. Player photos are loaded with CORS=anonymous;
   if a load fails (CORS rejection / 404) we fall back to a colored
   circle with the player's initials so the card never breaks.
   ═════════════════════════════════════════════════════════════════ */

var SHARE_BG = '#022d5c';
var SHARE_BG_DEEP = '#0a1628';
var SHARE_BLUE = '#034694';
var SHARE_BLUE_LIGHT = '#0563c1';
var SHARE_GOLD = '#DBA111';
var SHARE_GOLD_LIGHT = '#f0c040';

function _shareDisplayFont(weight) {
    // The mini-app body may be rendering with a Google-Fonts preset
    // (Russo One / Oswald / Manrope) but the share canvas is captured
    // as pixels — we want a stable, system-available font that's bold
    // and Cyrillic-friendly. Using 'Impact' as the lead with safe
    // fallbacks keeps the export consistent across devices.
    var w = weight || 800;
    return w + ' ${px}px Impact, "Arial Black", "Helvetica Neue", sans-serif';
}
function _shareBodyFont(weight, italic) {
    var w = weight || 600;
    var i = italic ? 'italic ' : '';
    return i + w + ' ${px}px -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif';
}

// Tiny string-template helper to avoid sprinkling .replace('${px}', ...)
// at every callsite. Pass a template returned by _shareDisplayFont/etc
// and the desired pixel size, get a font shorthand back.
function _font(template, px) { return template.replace('${px}', String(px)); }

function _initials(name) {
    if (!name) return '?';
    var parts = String(name).trim().split(/\s+/);
    var s = parts[0][0] || '?';
    if (parts.length > 1) s += parts[parts.length - 1][0] || '';
    return s.toUpperCase();
}

function _loadImage(url) {
    // Load with CORS so the resulting canvas isn't tainted (toBlob would
    // throw SecurityError otherwise). On failure (CORS missing / 404 /
    // network) the promise rejects and the caller draws a placeholder.
    return new Promise(function (resolve, reject) {
        if (!url) return reject(new Error('no url'));
        var img = new Image();
        img.crossOrigin = 'anonymous';
        img.onload = function () { resolve(img); };
        img.onerror = function () { reject(new Error('image failed')); };
        img.src = url;
    });
}

function _roundRect(ctx, x, y, w, h, r) {
    var rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y,     x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x,     y + h, rr);
    ctx.arcTo(x,     y + h, x,     y,     rr);
    ctx.arcTo(x,     y,     x + w, y,     rr);
    ctx.closePath();
}

function _drawPlayerPhoto(ctx, img, x, y, size, opts) {
    // Square photo with rounded corners. opts.desaturate=true draws as
    // grayscale (variant A's monochrome roster look). opts.fallbackName
    // picks the placeholder initials if we never got the image.
    opts = opts || {};
    var radius = opts.radius != null ? opts.radius : Math.round(size * 0.12);
    ctx.save();
    _roundRect(ctx, x, y, size, size, radius);
    ctx.clip();
    if (img) {
        if (opts.desaturate) {
            ctx.filter = 'grayscale(100%) contrast(1.1)';
        }
        // Cover-fit: scale up & crop center.
        var iw = img.naturalWidth, ih = img.naturalHeight;
        var scale = Math.max(size / iw, size / ih);
        var sw = size / scale, sh = size / scale;
        var sx = (iw - sw) / 2, sy = (ih - sh) / 2;
        ctx.drawImage(img, sx, sy, sw, sh, x, y, size, size);
        ctx.filter = 'none';
    } else {
        // Placeholder: gradient + initials.
        var grad = ctx.createLinearGradient(x, y, x + size, y + size);
        grad.addColorStop(0, SHARE_BLUE);
        grad.addColorStop(1, SHARE_BLUE_LIGHT);
        ctx.fillStyle = grad;
        ctx.fillRect(x, y, size, size);
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = _font(_shareDisplayFont(800), Math.round(size * 0.4));
        ctx.fillText(_initials(opts.fallbackName), x + size / 2, y + size / 2);
    }
    ctx.restore();
}

function _drawAvatarCircle(ctx, img, cx, cy, radius, opts) {
    opts = opts || {};
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.clip();
    if (img) {
        var iw = img.naturalWidth, ih = img.naturalHeight;
        var scale = Math.max((radius * 2) / iw, (radius * 2) / ih);
        var sw = (radius * 2) / scale, sh = (radius * 2) / scale;
        var sx = (iw - sw) / 2, sy = (ih - sh) / 2;
        ctx.drawImage(img, sx, sy, sw, sh, cx - radius, cy - radius, radius * 2, radius * 2);
    } else {
        var grad = ctx.createLinearGradient(cx - radius, cy - radius, cx + radius, cy + radius);
        grad.addColorStop(0, SHARE_BLUE);
        grad.addColorStop(1, SHARE_GOLD);
        ctx.fillStyle = grad;
        ctx.fillRect(cx - radius, cy - radius, radius * 2, radius * 2);
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = _font(_shareDisplayFont(800), Math.round(radius * 0.7));
        ctx.fillText(_initials(opts.fallbackName), cx, cy);
    }
    ctx.restore();
    // Gold ring
    ctx.strokeStyle = opts.ringColor || SHARE_GOLD;
    ctx.lineWidth = opts.ringWidth || Math.max(3, radius * 0.06);
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.stroke();
}

function _drawRatingBubble(ctx, cx, cy, radius, value) {
    // Gold-filled circle with the rating number (e.g. "9.5"). Used in
    // the lineup variant next to each player and in the MVP cover.
    var grad = ctx.createRadialGradient(cx - radius * 0.3, cy - radius * 0.3, 0, cx, cy, radius);
    grad.addColorStop(0, SHARE_GOLD_LIGHT);
    grad.addColorStop(1, SHARE_GOLD);
    ctx.fillStyle = grad;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#0a1628';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    var label = (value == null || isNaN(value)) ? '—' : (Number(value) % 1 === 0 ? String(value) : Number(value).toFixed(1));
    ctx.font = _font(_shareDisplayFont(800), Math.round(radius * 1.05));
    ctx.fillText(label, cx, cy + radius * 0.05);
}

/* ── Formation layout for variant A ────────────────────────────────
   Picks normalized positions (0..1 in x and y) for up to 11 starters.
   Falls back to 3-row distribution if formation can't be inferred.
   Returns an array of {x: 0..1, y: 0..1} the same length as `starters`.
*/
function _computeFormation(starters) {
    var n = starters.length;
    if (n === 0) return [];
    // Recognize common shapes by count buckets if positions are unknown:
    // n=11 → 4-3-3 default, n=10 fallback to 4-4-2-ish minus one, etc.
    // We tag each starter by position prefix when available.
    var rows = { GK: [], DEF: [], MID: [], FWD: [] };
    var unknown = [];
    starters.forEach(function (p) {
        var pos = (p.position || '').toUpperCase();
        if (pos.indexOf('GK') === 0 || pos === 'G' || pos === 'GOAL') rows.GK.push(p);
        else if (pos.indexOf('D') === 0 || pos.indexOf('CB') === 0 || pos.indexOf('LB') === 0 || pos.indexOf('RB') === 0 || pos.indexOf('FB') === 0 || pos === 'WB') rows.DEF.push(p);
        else if (pos.indexOf('M') === 0 || pos === 'CDM' || pos === 'CAM') rows.MID.push(p);
        else if (pos.indexOf('F') === 0 || pos.indexOf('W') === 0 || pos === 'ST' || pos === 'CF') rows.FWD.push(p);
        else unknown.push(p);
    });
    // If positions weren't tagged at all, use jersey numbers as a hint
    // (1 = GK, 2-5 def-ish, etc). Otherwise distribute unknowns into MID.
    if (rows.GK.length + rows.DEF.length + rows.MID.length + rows.FWD.length < 4) {
        return _formationFromCount(starters);
    }
    unknown.forEach(function (p) { rows.MID.push(p); });
    // Assemble row-by-row, top to bottom. Top of canvas = forwards
    // (attacking direction up, which mirrors the user's example).
    var pos = [];
    var rowDefs = [
        { players: rows.FWD, y: 0.18 },
        { players: rows.MID, y: 0.45 },
        { players: rows.DEF, y: 0.72 },
        { players: rows.GK,  y: 0.92 },
    ];
    rowDefs.forEach(function (r) {
        var k = r.players.length;
        if (k === 0) return;
        for (var i = 0; i < k; i++) {
            var x = (k === 1) ? 0.5 : (0.12 + (i / (k - 1)) * 0.76);
            pos.push({ player: r.players[i], x: x, y: r.y });
        }
    });
    return pos;
}

function _formationFromCount(starters) {
    // Fallback: just split into three rows by index. Not realistic but
    // looks fine if positional data is missing entirely.
    var pos = [];
    var n = starters.length;
    var rows = [Math.ceil(n / 3), Math.ceil(n / 3), n - 2 * Math.ceil(n / 3)];
    var ys = [0.22, 0.5, 0.78];
    var idx = 0;
    for (var r = 0; r < 3; r++) {
        var k = rows[r];
        for (var i = 0; i < k; i++) {
            var x = (k === 1) ? 0.5 : (0.12 + (i / (k - 1)) * 0.76);
            pos.push({ player: starters[idx++], x: x, y: ys[r] });
            if (idx >= n) break;
        }
        if (idx >= n) break;
    }
    return pos;
}

/* ── Variant A: Lineup ─────────────────────────────────────────── */
async function drawCardLineup(ctx, data, W, H) {
    var lineup = (data.lineup || []).slice();
    var starters = lineup.filter(function (p) { return p.is_starter; });
    var subs = lineup.filter(function (p) { return !p.is_starter; }).slice(0, 5);

    // Background — chelsea blue, slightly darker at the top
    var grad = ctx.createLinearGradient(0, 0, 0, H);
    grad.addColorStop(0, '#0a1f4d');
    grad.addColorStop(1, '#062052');
    ctx.fillStyle = grad;
    ctx.fillRect(0, 0, W, H);

    // Pitch lines (subtle, like the example image)
    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.lineWidth = 2;
    var px = 60, py = 200, pw = W - 120, ph = H - 380;
    ctx.strokeRect(px, py, pw, ph);
    // Center circle
    ctx.beginPath();
    ctx.arc(W / 2, py + ph / 2, 110, 0, Math.PI * 2);
    ctx.stroke();
    // Center line
    ctx.beginPath();
    ctx.moveTo(px, py + ph / 2);
    ctx.lineTo(px + pw, py + ph / 2);
    ctx.stroke();
    // Penalty boxes
    ctx.strokeRect(px + pw * 0.2, py, pw * 0.6, 100);
    ctx.strokeRect(px + pw * 0.2, py + ph - 100, pw * 0.6, 100);

    // Header strip
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.font = _font(_shareDisplayFont(800), 96);
    ctx.fillText('ЧЕЛСИ', 60, 40);
    // vs Opponent + tour + date (parsed from poll.title best-effort)
    var titleText = (data.poll && data.poll.title) || '';
    ctx.fillStyle = '#fff';
    ctx.font = _font(_shareBodyFont(700), 30);
    ctx.fillText(titleText.slice(0, 38), 60, 145);

    // Brand bug top right
    ctx.fillStyle = SHARE_GOLD;
    ctx.beginPath();
    ctx.arc(W - 90, 90, 50, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#0a1628';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.font = _font(_shareDisplayFont(800), 56);
    ctx.fillText('CFC', W - 90, 92);

    // Preload all photos in parallel; use null for any that fail.
    var allPlayers = starters.concat(subs);
    var imgs = await Promise.all(allPlayers.map(function (p) {
        return _loadImage(p.photo_url).catch(function () { return null; });
    }));
    var imgFor = {};
    allPlayers.forEach(function (p, i) { imgFor[p.player_id] = imgs[i]; });

    // Place starters on the pitch
    var positions = _computeFormation(starters);
    var photoSize = 130;
    positions.forEach(function (slot) {
        var p = slot.player;
        var cx = px + slot.x * pw;
        var cy = py + slot.y * ph;
        var x = cx - photoSize / 2;
        var y = cy - photoSize / 2;
        _drawPlayerPhoto(ctx, imgFor[p.player_id], x, y, photoSize, {
            desaturate: true, radius: 18, fallbackName: p.name,
        });
        // My rating bubble (top-right of photo) — only if voted
        if (p.my_rating != null) {
            _drawRatingBubble(ctx, x + photoSize - 14, y + 14, 32, p.my_rating);
        } else if (p.number != null) {
            // No rating → show jersey number instead
            ctx.fillStyle = '#fff';
            ctx.beginPath();
            ctx.arc(x + photoSize - 14, y + 14, 26, 0, Math.PI * 2);
            ctx.fill();
            ctx.fillStyle = SHARE_BLUE;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.font = _font(_shareDisplayFont(800), 28);
            ctx.fillText(String(p.number), x + photoSize - 14, y + 16);
        }
        // Name underneath
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.font = _font(_shareBodyFont(700), 24);
        var nm = p.name || '';
        if (nm.length > 14) nm = nm.slice(0, 13) + '…';
        ctx.fillText(nm, cx, y + photoSize + 8);
    });

    // Subs strip
    var subY = H - 150;
    ctx.fillStyle = 'rgba(255,255,255,0.85)';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.font = _font(_shareDisplayFont(800), 28);
    ctx.fillText('ЗАМЕНЫ', 60, subY - 60);
    var subSize = 90;
    var subSpacing = 110;
    var subStartX = 60;
    subs.forEach(function (p, i) {
        var x = subStartX + i * subSpacing;
        var y = subY - subSize / 2;
        _drawPlayerPhoto(ctx, imgFor[p.player_id], x, y, subSize, {
            desaturate: true, radius: 12, fallbackName: p.name,
        });
        if (p.my_rating != null) {
            _drawRatingBubble(ctx, x + subSize - 8, y + 8, 22, p.my_rating);
        }
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.font = _font(_shareBodyFont(700), 18);
        var nm = (p.name || '').split(' ').pop();
        if (nm.length > 10) nm = nm.slice(0, 9) + '…';
        ctx.fillText(nm, x + subSize / 2, y + subSize + 4);
    });

    // Brand mark bottom right
    ctx.fillStyle = SHARE_GOLD;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.font = _font(_shareBodyFont(700), 22);
    ctx.fillText('@ChelseaVotingBot', W - 60, H - 50);
}

/* ── Variant B: MVP Cover ──────────────────────────────────────── */
async function drawCardMvp(ctx, data, W, H) {
    var lineup = data.lineup || [];
    // MVP = the player I rated highest. Tie-break: community rank.
    var rated = lineup.filter(function (p) { return p.my_rating != null; });
    rated.sort(function (a, b) {
        if (b.my_rating !== a.my_rating) return b.my_rating - a.my_rating;
        return (a.community_rank || 999) - (b.community_rank || 999);
    });
    var mvp = rated[0] || lineup[0] || {};
    var maxRating = data.max_rating || 10;

    // Deep blue base + diagonal gold stripe
    ctx.fillStyle = '#020e2c';
    ctx.fillRect(0, 0, W, H);
    var stripGrad = ctx.createLinearGradient(0, 0, W, H);
    stripGrad.addColorStop(0, '#0a2c70');
    stripGrad.addColorStop(0.55, '#0a1f4d');
    stripGrad.addColorStop(1, '#020e2c');
    ctx.fillStyle = stripGrad;
    ctx.fillRect(0, 0, W, H);

    // Gold diagonal accent
    ctx.save();
    ctx.translate(W * 0.55, H * 0.5);
    ctx.rotate(-0.4);
    var stripeGrad = ctx.createLinearGradient(-W, 0, W, 0);
    stripeGrad.addColorStop(0, 'rgba(219,161,17,0)');
    stripeGrad.addColorStop(0.5, 'rgba(219,161,17,0.4)');
    stripeGrad.addColorStop(1, 'rgba(219,161,17,0)');
    ctx.fillStyle = stripeGrad;
    ctx.fillRect(-W, -60, 2 * W, 120);
    ctx.restore();

    // Player photo: large square on the right
    var photoSize = Math.round(H * 0.62);
    var photoX = W - photoSize - 60;
    var photoY = (H - photoSize) / 2 + 40;
    var img = null;
    try { img = await _loadImage(mvp.photo_url); } catch (e) { img = null; }
    _drawPlayerPhoto(ctx, img, photoX, photoY, photoSize, {
        desaturate: true, radius: 24, fallbackName: mvp.name,
    });
    // Outer gold border on photo
    ctx.strokeStyle = SHARE_GOLD;
    ctx.lineWidth = 6;
    _roundRect(ctx, photoX, photoY, photoSize, photoSize, 24);
    ctx.stroke();

    // Left-side typography stack
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    // "MVP" small label
    ctx.fillStyle = SHARE_GOLD;
    ctx.font = _font(_shareDisplayFont(800), 36);
    ctx.fillText('MVP МАТЧА', 60, 100);
    // Surname HUGE (split on whitespace, take last token)
    var surname = ((mvp.name || '').trim().split(/\s+/).pop() || '—').toUpperCase();
    var nameSize = 200;
    if (surname.length > 8) nameSize = 160;
    if (surname.length > 11) nameSize = 130;
    if (surname.length > 14) nameSize = 110;
    ctx.fillStyle = '#fff';
    ctx.font = _font(_shareDisplayFont(900), nameSize);
    ctx.fillText(surname, 60, 150);
    // Rating MASSIVE in gold
    ctx.fillStyle = SHARE_GOLD;
    ctx.font = _font(_shareDisplayFont(900), 320);
    var ratingLabel = (mvp.my_rating == null) ? '—' :
        (Number(mvp.my_rating) % 1 === 0 ? String(mvp.my_rating) : Number(mvp.my_rating).toFixed(1));
    ctx.fillText(ratingLabel, 60, 380);
    // /max-rating below the rating
    ctx.fillStyle = 'rgba(255,255,255,0.5)';
    ctx.font = _font(_shareDisplayFont(700), 60);
    var rWidth = ctx.measureText(ratingLabel).width;
    ctx.fillText(' / ' + maxRating, 60 + rWidth, 540);

    // Match strip
    ctx.fillStyle = 'rgba(255,255,255,0.7)';
    ctx.font = _font(_shareBodyFont(600), 30);
    var titleText = (data.poll && data.poll.title) || '';
    ctx.fillText('Челси ' + (titleText.slice(0, 36)), 60, 760);

    // Bottom-left: my mini avatar + handle
    var stats = data.my || {};
    var avatarImg = null;
    try { avatarImg = await _loadImage(stats.telegram_photo_url); } catch (e) { avatarImg = null; }
    _drawAvatarCircle(ctx, avatarImg, 110, H - 100, 50, {
        fallbackName: (stats.first_name || '') + ' ' + (stats.last_name || ''),
        ringColor: SHARE_GOLD, ringWidth: 4,
    });
    var handleParts = [];
    if (stats.username) handleParts.push('@' + stats.username);
    var idStr = stats.custom_id || stats.auto_id;
    if (idStr) handleParts.push(idStr);
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.font = _font(_shareBodyFont(700), 28);
    ctx.fillText(handleParts.join('  •  '), 180, H - 100);

    // Brand mark bottom right
    ctx.fillStyle = SHARE_GOLD;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.font = _font(_shareBodyFont(700), 24);
    ctx.fillText('@ChelseaVotingBot', W - 60, H - 60);
}

/* ── Variant C: Stats Vertical 9:16 ────────────────────────────── */
async function drawCardStats(ctx, data, W, H) {
    var bg = ctx.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, '#0a1f4d');
    bg.addColorStop(0.45, '#062052');
    bg.addColorStop(1, '#0a1628');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    // Subtle pitch grid
    ctx.strokeStyle = 'rgba(255,255,255,0.04)';
    ctx.lineWidth = 1;
    for (var gy = 0; gy < H; gy += 80) {
        ctx.beginPath();
        ctx.moveTo(0, gy);
        ctx.lineTo(W, gy);
        ctx.stroke();
    }

    var stats = data.my || {};
    var statsBlock = data.stats || {};

    // Header: avatar + name + handle
    var avatarImg = null;
    try { avatarImg = await _loadImage(stats.telegram_photo_url); } catch (e) { avatarImg = null; }
    _drawAvatarCircle(ctx, avatarImg, 140, 200, 90, {
        fallbackName: (stats.first_name || '') + ' ' + (stats.last_name || ''),
    });
    ctx.fillStyle = '#fff';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.font = _font(_shareDisplayFont(800), 64);
    var fullName = ((stats.first_name || '') + ' ' + (stats.last_name || '')).trim() || '—';
    if (fullName.length > 18) fullName = fullName.slice(0, 17) + '…';
    ctx.fillText(fullName, 260, 130);
    ctx.fillStyle = SHARE_GOLD_LIGHT;
    ctx.font = _font(_shareBodyFont(600), 36);
    ctx.fillText(stats.username ? '@' + stats.username : (stats.custom_id || stats.auto_id || ''), 260, 220);

    // Title: "Мои оценки vs ..."
    ctx.fillStyle = SHARE_GOLD;
    ctx.font = _font(_shareDisplayFont(800), 56);
    ctx.fillText('МОИ ОЦЕНКИ', 60, 360);
    ctx.fillStyle = '#fff';
    ctx.font = _font(_shareBodyFont(600), 34);
    var titleText = (data.poll && data.poll.title) || '';
    ctx.fillText(titleText.slice(0, 30), 60, 432);

    // Top 3 of my ratings
    var rated = (data.lineup || []).filter(function (p) { return p.my_rating != null; });
    rated.sort(function (a, b) { return b.my_rating - a.my_rating; });
    var top3 = rated.slice(0, 3);

    // Preload photos
    var photos = await Promise.all(top3.map(function (p) {
        return _loadImage(p.photo_url).catch(function () { return null; });
    }));

    var rankColors = [SHARE_GOLD, '#c0c0c0', '#cd7f32'];
    var startY = 540;
    var rowH = 200;
    top3.forEach(function (p, i) {
        var y = startY + i * rowH;
        // Rank circle
        ctx.fillStyle = rankColors[i];
        ctx.beginPath();
        ctx.arc(110, y + rowH / 2 - 20, 50, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = '#0a1628';
        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.font = _font(_shareDisplayFont(900), 64);
        ctx.fillText(String(i + 1), 110, y + rowH / 2 - 18);

        // Photo
        var photoSize = 140;
        _drawPlayerPhoto(ctx, photos[i], 200, y + (rowH - photoSize) / 2 - 20, photoSize, {
            desaturate: false, radius: 16, fallbackName: p.name,
        });

        // Name
        ctx.fillStyle = '#fff';
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.font = _font(_shareDisplayFont(800), 56);
        var nm = p.name || '';
        if (nm.length > 16) nm = nm.slice(0, 15) + '…';
        ctx.fillText(nm, 370, y + rowH / 2 - 30);

        // Rating
        ctx.fillStyle = SHARE_GOLD;
        ctx.font = _font(_shareDisplayFont(900), 80);
        ctx.textAlign = 'right';
        var lbl = Number(p.my_rating) % 1 === 0 ? String(p.my_rating) : Number(p.my_rating).toFixed(1);
        ctx.fillText(lbl, W - 60, y + rowH / 2 - 25);
    });

    // Stat strip near bottom
    var stripY = H - 360;
    ctx.fillStyle = 'rgba(0,0,0,0.35)';
    _roundRect(ctx, 60, stripY, W - 120, 200, 24);
    ctx.fill();
    ctx.strokeStyle = 'rgba(219,161,17,0.5)';
    ctx.lineWidth = 2;
    _roundRect(ctx, 60, stripY, W - 120, 200, 24);
    ctx.stroke();

    var cells = [
        { label: 'XP', value: String(statsBlock.total_xp || 0) },
        { label: 'СЕРИЯ', value: String(statsBlock.current_streak || 0) },
        { label: 'ВСЕГО ГОЛОСОВ', value: String(stats.total_votes || 0) },
    ];
    var cellW = (W - 120) / cells.length;
    cells.forEach(function (c, i) {
        var cx = 60 + i * cellW + cellW / 2;
        ctx.fillStyle = SHARE_GOLD;
        ctx.textAlign = 'center';
        ctx.textBaseline = 'top';
        ctx.font = _font(_shareDisplayFont(900), 80);
        ctx.fillText(c.value, cx, stripY + 30);
        ctx.fillStyle = 'rgba(255,255,255,0.7)';
        ctx.font = _font(_shareBodyFont(600), 26);
        ctx.fillText(c.label, cx, stripY + 130);
    });

    // Brand mark
    ctx.fillStyle = SHARE_GOLD;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'bottom';
    ctx.font = _font(_shareBodyFont(700), 30);
    ctx.fillText('@ChelseaVotingBot', W / 2, H - 60);
}

/* ── Render dispatch ─────────────────────────────────────────────── */
async function _renderShareCard(variant, data) {
    var dims = (variant === 'C') ? { w: 1080, h: 1920 } : { w: 1080, h: 1080 };
    var canvas = document.createElement('canvas');
    canvas.width = dims.w;
    canvas.height = dims.h;
    var ctx = canvas.getContext('2d');
    if (variant === 'A') await drawCardLineup(ctx, data, dims.w, dims.h);
    else if (variant === 'B') await drawCardMvp(ctx, data, dims.w, dims.h);
    else await drawCardStats(ctx, data, dims.w, dims.h);
    return canvas;
}

/* ── Picker modal ─────────────────────────────────────────────── */
async function openShareCardPicker(pollId) {
    toast(t('share.downloading'));
    var data;
    try {
        data = await api('/api/share/' + encodeURIComponent(pollId));
        if (!data.success) throw new Error('share data fetch failed');
    } catch (e) {
        toast(t('common.error'));
        return;
    }

    // Build the modal scaffold
    var overlay = document.createElement('div');
    overlay.className = 'share-modal-overlay';
    overlay.innerHTML =
        '<div class="share-modal">' +
        '  <div class="share-modal-header">' +
        '    <h3>' + (t('share.pick_variant') || 'Выбери дизайн') + '</h3>' +
        '    <button class="share-modal-close" aria-label="close">\u2716</button>' +
        '  </div>' +
        '  <div class="share-variants">' +
        '    <div class="share-variant" data-variant="A"><div class="share-variant-canvas"></div><div class="share-variant-label">' + (t('share.variant_a') || 'A — Состав') + '</div></div>' +
        '    <div class="share-variant" data-variant="B"><div class="share-variant-canvas"></div><div class="share-variant-label">' + (t('share.variant_b') || 'B — MVP') + '</div></div>' +
        '    <div class="share-variant" data-variant="C"><div class="share-variant-canvas"></div><div class="share-variant-label">' + (t('share.variant_c') || 'C — Stories') + '</div></div>' +
        '  </div>' +
        '</div>';
    document.body.appendChild(overlay);
    overlay.querySelector('.share-modal-close').addEventListener('click', function () {
        overlay.remove();
    });
    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) overlay.remove();
    });

    // Render thumbnails (smaller canvases). Use the same draw functions
    // — they're size-parameterized.
    var thumbDims = { w: 320, h: 320 };
    var thumbDimsTall = { w: 240, h: 426 };
    var slots = overlay.querySelectorAll('.share-variant');
    for (var i = 0; i < slots.length; i++) {
        (function (slot) {
            var v = slot.getAttribute('data-variant');
            var dims = (v === 'C') ? thumbDimsTall : thumbDims;
            var c = document.createElement('canvas');
            c.width = dims.w;
            c.height = dims.h;
            var cx = c.getContext('2d');
            var fn = (v === 'A') ? drawCardLineup : (v === 'B') ? drawCardMvp : drawCardStats;
            fn(cx, data, dims.w, dims.h).then(function () {
                slot.querySelector('.share-variant-canvas').appendChild(c);
            }).catch(function () {});
            slot.addEventListener('click', function () {
                _renderAndShare(v, data);
                overlay.remove();
            });
        })(slots[i]);
    }
}

async function _renderAndShare(variant, data) {
    toast(t('share.downloading'));
    var canvas;
    try {
        canvas = await _renderShareCard(variant, data);
    } catch (e) {
        toast(t('common.error'));
        return;
    }
    canvas.toBlob(function (blob) {
        if (!blob) { toast(t('common.error')); return; }
        var fileName = 'chelsea-' + variant.toLowerCase() + '.png';
        if (navigator.share && navigator.canShare) {
            var file = new File([blob], fileName, { type: 'image/png' });
            var sd = { files: [file], title: 'Chelsea Voting' };
            if (navigator.canShare(sd)) {
                navigator.share(sd).then(function () { toast(t('share.card_ready')); })
                                   .catch(function () { downloadBlob(blob); });
                return;
            }
        }
        downloadBlob(blob);
    }, 'image/png');
}

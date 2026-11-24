// PC-MQTT-Notifier — landing page
// One language at a time (English / Italian): every translated element carries
// data-en and data-it. The choice is remembered in this browser.
document.addEventListener('DOMContentLoaded', () => {
  const root = document.documentElement;
  const langBtn = document.getElementById('lang-toggle');
  const texts = document.querySelectorAll('[data-en]');
  const KEY = 'pc-mqtt-notifier-lang';
  root.classList.add('js-ready');

  function saved() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function remember(lang) {
    try { localStorage.setItem(KEY, lang); } catch (e) { /* private mode: no memory */ }
  }

  const GROUP_LABELS = {
    en: { Theme: 'Theme', Glow: 'Glow', Palette: 'Palette' },
    it: { Theme: 'Tema', Glow: 'Alone', Palette: 'Palette' },
  };

  function apply(lang) {
    texts.forEach((el) => {
      const value = el.dataset[lang];
      if (value !== undefined) el.innerHTML = value;
    });
    root.lang = lang;
    document.querySelectorAll('[data-group]').forEach((el) => {
      el.setAttribute('aria-label', GROUP_LABELS[lang][el.dataset.group]);
    });
    if (langBtn) {
      langBtn.textContent = lang === 'it' ? 'EN' : 'IT';
      langBtn.setAttribute('aria-label', lang === 'it' ? 'Switch to English' : "Passa all'italiano");
      langBtn.title = langBtn.getAttribute('aria-label');
    }
    setMenu(menuOpen);
  }

  // Phone menu (under 640px): the button exists only when this script runs; without it the links stay in the bar.
  const menuBtn = document.getElementById('menu-toggle');
  const menu = document.getElementById('primary-nav');
  let menuOpen = false;
  const MENU_LABELS = {
    en: { open: 'Open menu', close: 'Close menu' },
    it: { open: 'Apri il menu', close: 'Chiudi il menu' },
  };
  function setMenu(open) {
    menuOpen = open;
    if (!menuBtn || !menu) return;
    const labels = MENU_LABELS[root.lang === 'it' ? 'it' : 'en'];
    menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    menuBtn.setAttribute('aria-label', open ? labels.close : labels.open);
    root.classList.toggle('menu-open', open);
  }

  if (menuBtn && menu) {
    menuBtn.hidden = false;
    root.classList.add('menu-ready');
    menuBtn.addEventListener('click', () => setMenu(!menuOpen));
    menu.addEventListener('click', (e) => { if (e.target.closest('a')) setMenu(false); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && menuOpen) { setMenu(false); menuBtn.focus(); }
    });
    window.matchMedia('(min-width: 641px)').addEventListener('change', (e) => { if (e.matches) setMenu(false); });
  }

  // Styles gallery: a Dark / Light switch for the section and one option row per style.
  // Without this script each picture simply follows the page theme.
  const M = window.Motion;
  const reduceMotion = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const darkQuery = window.matchMedia('(prefers-color-scheme: dark)');
  const seg = document.getElementById('theme-seg');
  const panels = Array.prototype.slice.call(document.querySelectorAll('.style-panel'));
  const NAMES = {
    'glass-soft': 'Windows 11 Glass notification, Soft glow',
    'glass-full': 'Windows 11 Glass notification, Full glow',
    'aurora-night': 'Soft Aurora notification, Night palette',
    'aurora-sunset': 'Soft Aurora notification, Sunset palette',
    'aurora-forest': 'Soft Aurora notification, Forest palette',
    'classic': 'Classic notification',
    'static': 'Static notification',
    'ambient-washer': 'Ambient notification, washer icon',
    'ambient-door': 'Ambient notification, door icon',
    'ambient-warning': 'Ambient notification, warning icon',
    'poster-washer': 'Poster notification, washer icon',
    'poster-door': 'Poster notification, door icon',
    'poster-warning': 'Poster notification, warning icon',
    'vinyl': 'Vinyl notification',
  };
  let pickedTheme = null;
  const theme = () => pickedTheme || (darkQuery.matches ? 'dark' : 'light');

  function paint(panel, fade) {
    const img = panel.querySelector('.style-stage img');
    const stage = panel.querySelector('.style-stage');
    if (!img) return;
    const t = theme();
    const variant = panel.dataset.variant;
    img.src = './styles/style-' + variant + '-' + t + '.webp';
    img.alt = NAMES[variant] || img.alt;
    stage.classList.toggle('on-dark', pickedTheme === 'dark');
    stage.classList.toggle('on-light', pickedTheme === 'light');
    panel.querySelectorAll('.chips button').forEach((b) => {
      b.setAttribute('aria-pressed', b.dataset.variant === variant ? 'true' : 'false');
    });
    if (fade && M && M.animate && !reduceMotion) {
      M.animate(img, { opacity: [0.4, 1] }, { duration: 0.18, ease: [0.22, 1, 0.36, 1] });
    }
  }

  function paintSeg() {
    if (!seg) return;
    seg.querySelectorAll('button').forEach((b) => {
      b.setAttribute('aria-pressed', b.dataset.theme === theme() ? 'true' : 'false');
    });
  }

  panels.forEach((panel) => {
    const source = panel.querySelector('.style-stage source');
    if (source) source.remove();
    const chips = panel.querySelector('.chips');
    if (chips) {
      chips.hidden = false;
      chips.dataset.group = chips.getAttribute('aria-label');
      chips.addEventListener('click', (e) => {
        const b = e.target.closest('button');
        if (!b) return;
        panel.dataset.variant = b.dataset.variant;
        paint(panel, true);
      });
    }
    paint(panel, false);
  });

  if (seg) {
    seg.hidden = false;
    seg.dataset.group = 'Theme';
    paintSeg();
    seg.addEventListener('click', (e) => {
      const b = e.target.closest('button');
      if (!b) return;
      pickedTheme = b.dataset.theme;
      paintSeg();
      panels.forEach((p) => paint(p, true));
    });
  }
  darkQuery.addEventListener('change', () => {
    if (pickedTheme) return;
    paintSeg();
    panels.forEach((p) => paint(p, false));
  });

  // ?lang=it / ?lang=en wins, then the saved choice, then the browser language.
  const fromUrl = new URLSearchParams(location.search).get('lang');
  let lang = ['en', 'it'].includes(fromUrl) ? fromUrl
    : saved() || ((navigator.language || 'en').toLowerCase().startsWith('it') ? 'it' : 'en');
  apply(lang);

  if (langBtn) {
    langBtn.addEventListener('click', () => {
      lang = lang === 'it' ? 'en' : 'it';
      apply(lang);
      remember(lang);
    });
  }

  // Entrance on scroll with Motion (motion.dev), optional: a short fade and rise.
  // Content is visible by default; it is hidden only while Motion is expected (class
  // motion-ready, removed after 1.5 s at most) and never with reduced motion.
  clearTimeout(window.__pmnReveal);
  if (!M || reduceMotion || !M.animate || !M.inView || !root.classList.contains('motion-ready')) {
    root.classList.remove('motion-ready');
    return;
  }

  const ease = [0.22, 1, 0.36, 1];
  const reveals = Array.prototype.slice.call(document.querySelectorAll('.reveal'));
  // Hand the hidden start state from the class to inline styles, then fade and rise each element as it enters.
  reveals.forEach((el) => { el.style.opacity = '0'; });
  root.classList.remove('motion-ready');
  const showAll = () => reveals.forEach((el) => { el.style.opacity = ''; el.style.transform = ''; });

  // Elements entering together get a small stagger (50 ms, at most six steps).
  let batch = 0;
  let batchTimer = null;
  try {
    reveals.forEach((el) => {
      M.inView(el, () => {
        const delay = Math.min(batch, 5) * 0.05;
        batch += 1;
        clearTimeout(batchTimer);
        batchTimer = setTimeout(() => { batch = 0; }, 120);
        M.animate(el, { opacity: [0, 1], transform: ['translateY(8px)', 'translateY(0px)'] },
          { duration: 0.4, delay: delay, ease: ease });
      }, { amount: 0.2 });
    });
  } catch (e) {
    showAll();
  }
});

document.addEventListener('DOMContentLoaded', () => {
  // 1. Theme Toggle
  const themeToggle = document.getElementById('theme-toggle');
  const root = document.documentElement;

  if (themeToggle) {
    let isLight = false;
    themeToggle.addEventListener('click', () => {
      isLight = !isLight;
      if (isLight) {
        root.classList.add('light');
        themeToggle.textContent = '🌙 Dark';
      } else {
        root.classList.remove('light');
        themeToggle.textContent = '☀️ Light';
      }
    });
  }

  // 2. Language Toggle
  const langToggle = document.getElementById('lang-toggle');
  if (langToggle) {
    let isItalian = false;
    const elementsToTranslate = document.querySelectorAll('[data-en]');

    langToggle.addEventListener('click', () => {
      isItalian = !isItalian;
      langToggle.textContent = isItalian ? '🇬🇧 EN' : '🇮🇹 IT';

      elementsToTranslate.forEach(el => {
        if (isItalian) {
          if (el.dataset.it) el.innerHTML = el.dataset.it;
        } else {
          if (el.dataset.en) el.innerHTML = el.dataset.en;
        }
      });
    });
  }

  // 3. Scroll Reveal Animation (Arborae Standard)
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const reveals = document.querySelectorAll('.reveal');

  if (reduceMotion || !('IntersectionObserver' in window)) {
    reveals.forEach(el => el.classList.add('visible'));
  } else {
    const io = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting) {
          entry.target.classList.add('visible');
          io.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });

    reveals.forEach(el => io.observe(el));
  }
});

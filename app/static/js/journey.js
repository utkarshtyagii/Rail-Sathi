document.addEventListener('DOMContentLoaded', () => {
  const journey = document.querySelector('[data-rail-journey]');
  if (!journey) return;

  const chapters = [...journey.querySelectorAll('[data-journey-chapter]')];
  const marker = journey.querySelector('.journey-chapter-marker');
  const number = journey.querySelector('[data-journey-number]');
  const label = journey.querySelector('[data-journey-label]');
  const progressBar = journey.querySelector('[data-journey-progress]');
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  let frame = 0;

  if (!reducedMotion) document.body.classList.add('journey-motion-ready');

  const clamp = (value, min = 0, max = 1) => Math.max(min, Math.min(max, value));

  const updateStory = () => {
    frame = 0;
    const viewport = window.innerHeight || 1;
    const scrollable = Math.max(1, document.documentElement.scrollHeight - viewport);
    const pageProgress = clamp(window.scrollY / scrollable);
    if (progressBar) progressBar.style.width = `${pageProgress * 100}%`;

    const markerY = window.scrollY + viewport * 0.48;
    let activeIndex = 0;
    chapters.forEach((chapter, index) => {
      const top = chapter.offsetTop;
      const bottom = top + chapter.offsetHeight;
      if (markerY >= top && markerY < bottom) activeIndex = index;

      const rect = chapter.getBoundingClientRect();
      const travel = Math.max(1, chapter.offsetHeight - viewport);
      const sceneProgress = clamp(-rect.top / travel);
      const easedProgress = sceneProgress * sceneProgress * (3 - 2 * sceneProgress);
      chapter.style.setProperty('--journey-scene-progress', sceneProgress.toFixed(3));
      if (chapter.id === 'journey-arrival') {
        chapter.classList.toggle('is-arrival-visible', rect.top <= viewport * 0.08);
      }

      if (!reducedMotion) {
        chapter.querySelectorAll('[data-journey-copy]').forEach(copy => {
          if (chapter.id === 'journey-arrival') {
            copy.style.transform = 'none';
          } else {
            const travelDistance = 88;
            copy.style.transform = `translate3d(0, ${(travelDistance / 2) - easedProgress * travelDistance}px, 0)`;
          }
        });
        chapter.querySelectorAll('[data-journey-photo]').forEach(photo => {
          if (chapter.id === 'journey-help') {
            const porterProgress = 0.5 - Math.cos(Math.PI * sceneProgress) / 2;
            const photoWidth = photo.getBoundingClientRect().width;
            const endPosition = window.innerWidth - photoWidth * 0.3 - window.innerWidth * 0.035;
            const travelLimit = Math.min(window.innerWidth * (window.innerWidth <= 600 ? 0.38 : 0.46), Math.max(0, endPosition));
            const porterTravel = porterProgress * travelLimit;
            photo.style.transform = `translate3d(${porterTravel}px, ${8 - sceneProgress * 16}px, 0)`;
          } else if (chapter.id === 'journey-freedom') {
            photo.style.transform = `translate3d(${36 - easedProgress * 72}px, ${18 - easedProgress * 36}px, 0) scale(${1.08 - easedProgress * 0.05})`;
          } else if (chapter.id === 'journey-arrival') {
            photo.style.transform = 'none';
          } else {
            photo.style.transform = `translate3d(0, ${18 - easedProgress * 36}px, 0) scale(${1.07 - easedProgress * 0.04})`;
          }
        });
      }
    });

    chapters.forEach((chapter, index) => chapter.classList.toggle('is-current', index === activeIndex));
    chapters[activeIndex]?.classList.add('is-entered');

    if (number) number.textContent = String(activeIndex + 1).padStart(2, '0');
    if (label) label.textContent = chapters[activeIndex]?.dataset.label || 'The Rail Sathi journey';
    if (marker) marker.hidden = activeIndex === chapters.length - 1;
  };

  const scheduleUpdate = () => {
    if (!frame) frame = window.requestAnimationFrame(updateStory);
  };

  updateStory();
  window.addEventListener('scroll', scheduleUpdate, { passive: true });
  window.addEventListener('resize', scheduleUpdate);
});

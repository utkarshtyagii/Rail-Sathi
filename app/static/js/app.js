document.addEventListener('DOMContentLoaded', () => {
  const landingTopbar = document.querySelector('.redesigned-landing .topbar');
  const landingHero = document.querySelector('.redesigned-landing .hero');
  const landingHeroPhoto = landingHero?.querySelector('.hero-photo');
  const landingJourney = document.querySelector('.redesigned-landing .journey');
  const luggageStory = document.querySelector('[data-luggage-scroll]');
  const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (landingTopbar && !reduceMotion) {
    document.body.classList.add('landing-motion-ready');
    landingHero?.querySelectorAll('.hero-word').forEach((word, index) => {
      word.style.setProperty('--hero-word-delay', `${650 + index * 80}ms`);
    });

    if (landingJourney) {
      if ('IntersectionObserver' in window) {
        const journeyObserver = new IntersectionObserver(entries => {
          if (entries.some(entry => entry.isIntersecting)) {
            landingJourney.classList.add('is-visible');
            journeyObserver.disconnect();
          }
        }, { rootMargin: '0px 0px -30% 0px', threshold: 0 });
        journeyObserver.observe(landingJourney);
      } else {
        landingJourney.classList.add('is-visible');
      }
    }
  }
  if (landingTopbar || landingHeroPhoto) {
    let photoFrame = 0;
    let photoProgress = 0;
    let targetPhotoProgress = 0;
    let previousPhotoFrame = 0;
    const renderHeroPhoto = timestamp => {
      photoFrame = 0;
      if (!landingHero || !landingHeroPhoto || reduceMotion) return;
      const elapsed = previousPhotoFrame ? timestamp - previousPhotoFrame : 16;
      previousPhotoFrame = timestamp;
      // Match the prototype's 1.2s ScrollTrigger scrub so the photo glides
      // with the scroll instead of snapping to each wheel/touch update.
      const follow = 1 - Math.exp(-elapsed / 1200);
      photoProgress += (targetPhotoProgress - photoProgress) * follow;
      if (Math.abs(targetPhotoProgress - photoProgress) < 0.0005) {
        photoProgress = targetPhotoProgress;
        previousPhotoFrame = 0;
      }
      const verticalShift = photoProgress * 8;
      const scale = 1 + photoProgress * 0.04;
      landingHeroPhoto.style.transform = `translate3d(0, ${verticalShift}%, 0) scale(${scale})`;
      landingHeroPhoto.style.objectPosition = 'center 48%';
      if (photoProgress !== targetPhotoProgress) {
        photoFrame = window.requestAnimationFrame(renderHeroPhoto);
      }
    };
    const updateLandingEffects = () => {
      if (landingTopbar) {
        const whiteHeaderAt = landingHero
          ? landingHero.offsetTop + landingHero.offsetHeight
          : 32;
        landingTopbar.classList.toggle('is-scrolled', window.scrollY >= whiteHeaderAt);
      }
      if (!landingHero || !landingHeroPhoto || reduceMotion) return;
      const heroProgress = -landingHero.getBoundingClientRect().top / Math.max(1, landingHero.offsetHeight);
      targetPhotoProgress = Math.max(0, Math.min(1, heroProgress));
      if (!photoFrame) photoFrame = window.requestAnimationFrame(renderHeroPhoto);
    };
    updateLandingEffects();
    window.addEventListener('scroll', updateLandingEffects, { passive: true });
    window.addEventListener('resize', updateLandingEffects);
  }
  if (luggageStory) {
    const luggageScene = luggageStory.querySelector('.luggage-scene');
    const questions = [...luggageStory.querySelectorAll('[data-story-step]')];
    const counter = luggageStory.querySelector('[data-story-count]');
    const solution = luggageStory.querySelector('[data-story-solution]');
    const porter = luggageStory.querySelector('[data-story-porter]');
    const progressBar = luggageStory.querySelector('[data-story-progress]');
    let storyFrame = 0;
    const updateLuggageStory = () => {
      storyFrame = 0;
      const travel = Math.max(1, luggageStory.offsetHeight - window.innerHeight);
      const progress = Math.max(0, Math.min(1, -luggageStory.getBoundingClientRect().top / travel));
      const activeStep = Math.min(3, Math.floor(progress * 4));
      questions.forEach((question, index) => {
        const active = index === activeStep && activeStep < questions.length;
        question.classList.toggle('is-active', active);
        question.setAttribute('aria-hidden', String(!active));
      });
      const showSolution = activeStep === 3;
      luggageScene?.classList.toggle('is-final', showSolution);
      solution?.classList.toggle('is-active', showSolution);
      solution?.setAttribute('aria-hidden', String(!showSolution));
      if (counter) counter.textContent = String(activeStep + 1).padStart(2, '0');
      if (progressBar) progressBar.style.width = `${progress * 100}%`;
      if (porter) {
        const visibleTravel = Math.min(1, progress / .75);
        const rightMargin = window.innerWidth * .02;
        const travelDistance = Math.max(0, window.innerWidth - porter.offsetWidth * .92 - rightMargin);
        porter.style.transform = `translate3d(${travelDistance * visibleTravel}px, 0, 0)`;
      }
    };
    const scheduleLuggageStory = () => {
      if (!storyFrame) storyFrame = window.requestAnimationFrame(updateLuggageStory);
    };
    updateLuggageStory();
    window.addEventListener('scroll', scheduleLuggageStory, { passive: true });
    window.addEventListener('resize', scheduleLuggageStory, { passive: true });
  }

  document.querySelectorAll('.flash-stack .flash').forEach(message => {
    window.setTimeout(() => {
      message.classList.add('flash-dismissed');
      window.setTimeout(() => message.remove(), 350);
    }, 5000);
  });

  const station = document.querySelector('#station');
  const service = document.querySelector('#service');
  const fare = document.querySelector('#fare');
  const bags = document.querySelector('[name="bags"]');
  const accountRole = document.querySelector('#role');
  const porterFields = document.querySelector('#porter-application-fields');
  const passengerFields = document.querySelector('#passenger-fields');
  const menuButton = document.querySelector('#site-menu-toggle');
  const siteMenu = document.querySelector('#site-menu');
  if (menuButton && siteMenu) {
    const closeMenu = () => {
      siteMenu.hidden = true;
      menuButton.setAttribute('aria-expanded', 'false');
      menuButton.setAttribute('aria-label', 'Open website menu');
    };
    menuButton.addEventListener('click', () => {
      const open = menuButton.getAttribute('aria-expanded') !== 'true';
      siteMenu.hidden = !open;
      menuButton.setAttribute('aria-expanded', String(open));
      menuButton.setAttribute('aria-label', open ? 'Close website menu' : 'Open website menu');
    });
    siteMenu.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));
    document.addEventListener('click', event => {
      if (!event.target.closest('.site-menu-wrap')) closeMenu();
    });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape') {
        closeMenu();
        menuButton.focus();
      }
    });
  }

  const themeButtons = [...document.querySelectorAll('[data-theme-toggle]')];
  const setTheme = theme => {
    const dark = theme === 'dark';
    document.documentElement.dataset.theme = dark ? 'dark' : 'light';
    themeButtons.forEach(button => {
      button.setAttribute('aria-pressed', String(dark));
      button.setAttribute('aria-label', dark ? 'Switch to light mode' : 'Switch to dark mode');
      const label = button.querySelector('[data-theme-label]');
      const icon = button.querySelector('[data-theme-icon]');
      if (label) label.textContent = dark ? 'Light mode' : 'Dark mode';
      if (icon) icon.textContent = dark ? '☀' : '☾';
    });
    try { localStorage.setItem('railSathiTheme', dark ? 'dark' : 'light'); } catch (_) {}
  };
  setTheme(document.documentElement.dataset.theme === 'dark' ? 'dark' : 'light');
  themeButtons.forEach(button => button.addEventListener('click', () => {
    setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
  }));

  let installPrompt = null;
  window.addEventListener('beforeinstallprompt', event => {
    event.preventDefault();
    installPrompt = event;
  });
  const installButton = document.querySelector('#install-app-button');
  const installStatus = document.querySelector('#app-install-status');
  installButton?.addEventListener('click', async () => {
    if (!installStatus) return;
    if (window.matchMedia('(display-mode: standalone)').matches || navigator.standalone) {
      installStatus.textContent = 'Rail Sathi is already installed on this device.';
    } else if (installPrompt) {
      installPrompt.prompt();
      const choice = await installPrompt.userChoice;
      installStatus.textContent = choice.outcome === 'accepted'
        ? 'Rail Sathi is being installed.'
        : 'Installation was cancelled. You can try again any time.';
      installPrompt = null;
    } else if (/iPhone|iPad|iPod/i.test(navigator.userAgent)) {
      installStatus.textContent = 'To add Rail Sathi, tap Share in Safari, then choose Add to Home Screen.';
    } else {
      installStatus.textContent = 'To install Rail Sathi, open your browser menu and choose Install app or Add to Home screen.';
    }
    installStatus.hidden = false;
  });
  if (accountRole && porterFields && passengerFields) {
    const preferredStation = porterFields.querySelector('[name="preferred_station"]');
    const dateOfBirth = passengerFields.querySelector('[name="date_of_birth"]');
    const updateSignupFields = () => {
      const applyingAsPorter = accountRole.value === 'porter';
      passengerFields.hidden = applyingAsPorter;
      porterFields.hidden = !applyingAsPorter;
      dateOfBirth.required = !applyingAsPorter;
      preferredStation.required = applyingAsPorter;
    };
    accountRole.addEventListener('change', updateSignupFields);
    updateSignupFields();
  }
  if (station && service) {
    const serviceTemplate = document.querySelector('#booking-service-options');
    const availableOptions = serviceTemplate
      ? [...serviceTemplate.content.querySelectorAll('option[data-station]')]
      : [];

    const renderStationServices = () => {
      const previousService = service.value;
      const selectedStation = station.value;
      service.replaceChildren(new Option(selectedStation ? 'Select service' : 'Select a station first', ''));
      availableOptions
        .filter(option => option.dataset.station === selectedStation)
        .forEach(option => service.add(option.cloneNode(true)));
      if ([...service.options].some(option => option.value === previousService)) {
        service.value = previousService;
      }
      updateFare();
    };

    const updateFare = () => {
      if (fare) {
        const base = Number(service.selectedOptions[0]?.dataset.fare || serviceData.find(item => String(item.id) === service.value)?.fare || 0);
        fare.textContent = base ? `₹${(base + Math.max(0, Number(bags?.value || 1) - 1) * 35).toLocaleString('en-IN')}` : 'Choose a service';
      }
    };

    const update = () => {
      updateFare();
    };
    station.addEventListener('change', renderStationServices);
    service.addEventListener('change', update);
    bags?.addEventListener('input', updateFare);
    if (serviceTemplate) renderStationServices();
    else update();
  }
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/static/sw.js').catch(() => {});
});

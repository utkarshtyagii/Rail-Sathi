(() => {
  const panels = [...document.querySelectorAll('[data-booking-tracking]')];
  if (!panels.length) return;

  const panelByBooking = new Map();
  const stateByPanel = new Map();
  let socket;

  function loadGoogleMaps() {
    return fetch('/maps/config', { credentials: 'same-origin', cache: 'no-store' }).then((response) => {
      if (!response.ok) throw new Error('config');
      return response.json();
    }).then(({ apiKey }) => {
      if (!apiKey) throw new Error('missing-key');
      return new Promise((resolve, reject) => {
        const callbackName = '__railSathiGoogleMapsReady';
        window[callbackName] = () => {
          delete window[callbackName];
          if (window.google?.maps) resolve();
          else reject(new Error('api-load'));
        };
        const script = document.createElement('script');
        script.async = true;
        script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&callback=${callbackName}&loading=async`;
        script.onerror = () => reject(new Error('api-load'));
        document.head.appendChild(script);
      });
    });
  }

  function setMessage(panel, message, isError = false) {
    const node = panel.querySelector('[data-tracking-message]');
    node.textContent = message;
    node.classList.toggle('is-error', isError);
  }

  function setConnection(panel, message, connected = false) {
    const node = panel.querySelector('[data-connection-status]');
    node.textContent = message;
    node.classList.toggle('is-connected', connected);
    node.classList.toggle('is-disconnected', !connected);
  }

  function formatTime(isoDate) {
    const date = new Date(isoDate);
    if (Number.isNaN(date.getTime())) return 'unknown time';
    return new Intl.DateTimeFormat(undefined, { hour: 'numeric', minute: '2-digit' }).format(date);
  }

  function hasValidPosition(position) {
    if (!position) return false;
    const latitude = Number(position.latitude);
    const longitude = Number(position.longitude);
    const updatedAt = Date.parse(position.updatedAt);
    if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90 ||
        !Number.isFinite(longitude) || longitude < -180 || longitude > 180 ||
        !Number.isFinite(updatedAt)) return false;
    return true;
  }

  function isFreshPosition(panel, position) {
    if (!hasValidPosition(position)) return false;
    const updatedAt = Date.parse(position.updatedAt);
    const staleAfter = Math.max(5, Number(panel.dataset.staleAfterSeconds) || 30);
    return Math.max(0, Date.now() - updatedAt) <= staleAfter * 1000;
  }

  function renderDistance(panel) {
    const state = stateByPanel.get(panel);
    const distanceNode = panel.querySelector('[data-tracking-distance]');
    const showDistance = (value) => {
      if (distanceNode.textContent !== value) distanceNode.textContent = value;
    };
    const passenger = state.positions.passenger;
    const porter = state.positions.porter;
    if (!isFreshPosition(panel, passenger) || !isFreshPosition(panel, porter)) {
      showDistance('Waiting for location');
      return;
    }

    const radians = (degrees) => degrees * Math.PI / 180;
    const lat1 = radians(Number(passenger.latitude));
    const lat2 = radians(Number(porter.latitude));
    const latDelta = lat2 - lat1;
    const lngDelta = radians(Number(porter.longitude) - Number(passenger.longitude));
    const haversine = Math.min(1, Math.sin(latDelta / 2) ** 2 +
      Math.cos(lat1) * Math.cos(lat2) * Math.sin(lngDelta / 2) ** 2);
    const distanceMetres = 6371000 * 2 * Math.atan2(Math.sqrt(haversine), Math.sqrt(1 - haversine));
    showDistance(distanceMetres < 1000
      ? `${Math.round(distanceMetres)} m`
      : `${(distanceMetres / 1000).toFixed(distanceMetres < 10000 ? 2 : 1)} km`);
  }

  function initializePanel(panel) {
    const bookingId = Number(panel.dataset.bookingId);
    const role = panel.dataset.role;
    const state = {
      bookingId,
      role,
      joined: false,
      pendingStart: false,
      status: panel.dataset.bookingStatus || 'assigned',
      optedOut: false,
      shouldResume: false,
      permissionStatus: null,
      watchId: null,
      heartbeatId: null,
      sharing: false,
      lastSentAt: 0,
      markers: { passenger: null, porter: null },
      positions: { passenger: null, porter: null },
      mapHasPosition: false,
      map: null,
      mapUnavailable: false,
      pickupMarker: null,
      destinationMarker: null,
      infoWindow: null,
      closed: false,
    };
    stateByPanel.set(panel, state);
    panelByBooking.set(bookingId, panel);

    const startButton = panel.querySelector('[data-start-sharing]');
    const stopButton = panel.querySelector('[data-stop-sharing]');
    startButton.addEventListener('click', () => beginSharing(panel));
    stopButton.addEventListener('click', () => stopSharing(panel, true));

    const mapElement = panel.querySelector('[data-tracking-map]');
    if (window.google?.maps) {
    state.map = new google.maps.Map(mapElement, {
      center: { lat: 22.5, lng: 79 }, zoom: 4, mapTypeControl: false,
      streetViewControl: false, fullscreenControl: true,
    });
    state.infoWindow = new google.maps.InfoWindow();
    panel.querySelector('[data-tracking-map-empty]').textContent = 'Waiting for a fresh location…';

    const pickupLatitude = Number(panel.dataset.pickupLatitude);
    const pickupLongitude = Number(panel.dataset.pickupLongitude);
    if (panel.dataset.pickupLatitude && panel.dataset.pickupLongitude &&
        Number.isFinite(pickupLatitude) && Number.isFinite(pickupLongitude)) {
      state.pickupMarker = new google.maps.Marker({
        map: state.map, position: { lat: pickupLatitude, lng: pickupLongitude },
        title: `Pickup · ${panel.dataset.pickupLabel}`,
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 9, fillColor: '#d9272e', fillOpacity: 1, strokeColor: '#ffffff', strokeWeight: 3 },
      });
      state.pickupMarker.addListener('click', () => {
        state.infoWindow.setContent(document.createTextNode(`Pickup · ${panel.dataset.pickupLabel}`));
        state.infoWindow.open({ map: state.map, anchor: state.pickupMarker });
      });
      state.map.setCenter({ lat: pickupLatitude, lng: pickupLongitude });
      state.map.setZoom(16);
      panel.querySelector('[data-tracking-map-empty]').hidden = true;
    }
    const destinationLatitude = Number(panel.dataset.destinationLatitude);
    const destinationLongitude = Number(panel.dataset.destinationLongitude);
    if (panel.dataset.destinationLatitude && panel.dataset.destinationLongitude &&
        Number.isFinite(destinationLatitude) && Number.isFinite(destinationLongitude)) {
      state.destinationMarker = new google.maps.Marker({
        map: state.map, position: { lat: destinationLatitude, lng: destinationLongitude },
        title: `Destination · ${panel.dataset.destinationLabel}`,
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 9, fillColor: '#2867b2', fillOpacity: 1, strokeColor: '#ffffff', strokeWeight: 3 },
      });
      state.destinationMarker.addListener('click', () => {
        state.infoWindow.setContent(document.createTextNode(`Destination · ${panel.dataset.destinationLabel}`));
        state.infoWindow.open({ map: state.map, anchor: state.destinationMarker });
      });
      panel.querySelector('[data-tracking-map-empty]').hidden = true;
    }
    } else {
      state.mapUnavailable = true;
      panel.querySelector('[data-tracking-map-empty]').textContent = 'Map unavailable. Location sharing can still run.';
    }
  }

  function refreshParticipantMarker(panel, role) {
    const state = stateByPanel.get(panel);
    if (!state?.map || !window.google?.maps) return;
    const position = state.positions[role];
    let marker = state.markers[role];
    if (!isFreshPosition(panel, position)) {
      if (marker) marker.setMap(null);
      syncMapEmptyState(panel);
      return;
    }

    const point = { lat: Number(position.latitude), lng: Number(position.longitude) };
    if (marker) {
      marker.setPosition(point);
      marker.setMap(state.map);
      syncMapEmptyState(panel);
      return;
    }
    marker = new google.maps.Marker({
      map: state.map,
      position: point,
      title: role === 'porter' ? 'Porter GPS location' : 'Passenger GPS location',
      icon: { path: google.maps.SymbolPath.CIRCLE, scale: 8, fillColor: role === 'porter' ? '#16805c' : '#d92b2f', fillOpacity: 1, strokeColor: '#ffffff', strokeWeight: 3 },
    });
    state.markers[role] = marker;
    syncMapEmptyState(panel);
  }

  function syncMapEmptyState(panel) {
    const state = stateByPanel.get(panel);
    if (!state?.map || !window.google?.maps) return;
    const hasVisibleMarker = Object.values(state.markers).some((marker) => marker?.getMap()) || Boolean(state.pickupMarker?.getMap()) || Boolean(state.destinationMarker?.getMap());
    const emptyState = panel.querySelector('[data-tracking-map-empty]');
    emptyState.textContent = 'Waiting for a fresh location…';
    emptyState.hidden = hasVisibleMarker;
  }

  function keepLiveMarkersInView(panel) {
    const state = stateByPanel.get(panel);
    const liveMarkers = ['passenger', 'porter']
      .map((role) => isFreshPosition(panel, state.positions[role]) ? state.markers[role] : null)
      .filter(Boolean);
    if (!liveMarkers.length) return;

    const bounds = new google.maps.LatLngBounds();
    liveMarkers.forEach((marker) => bounds.extend(marker.getPosition()));
    if (liveMarkers.length === 2) {
      state.map.fitBounds(bounds, 48);
      if (state.map.getZoom() > 16) state.map.setZoom(16);
      state.mapHasPosition = true;
      return;
    }

    const point = liveMarkers[0].getPosition();
    if (!state.mapHasPosition || !state.map.getBounds()?.contains(point)) state.map.panTo(point);
    state.mapHasPosition = true;
  }

  function updatePosition(panel, role, position) {
    const state = stateByPanel.get(panel);
    if (!state || !['passenger', 'porter'].includes(role) || !hasValidPosition(position)) {
      if (state && ['passenger', 'porter'].includes(role)) clearLivePosition(panel, role);
      return;
    }
    state.positions[role] = position;
    refreshParticipantMarker(panel, role);
    keepLiveMarkersInView(panel);
    renderParticipant(panel, role);
  }

  function clearLivePosition(panel, role) {
    const state = stateByPanel.get(panel);
    if (state.markers[role]) {
      state.markers[role].setMap(null);
      state.markers[role] = null;
    }
    state.positions[role] = null;
    renderParticipant(panel, role);
    if (!state.markers.passenger && !state.markers.porter && !state.pickupMarker) {
      syncMapEmptyState(panel);
    }
  }

  function renderParticipant(panel, role) {
    const state = stateByPanel.get(panel);
    const position = state.positions[role];
    const stateNode = panel.querySelector(`[data-participant-state="${role}"]`);
    const detailNode = panel.querySelector(`[data-participant-detail="${role}"]`);
    if (!position) {
      stateNode.textContent = 'Waiting for location';
      stateNode.classList.remove('is-stale');
      detailNode.textContent = '';
      refreshParticipantMarker(panel, role);
      renderDistance(panel);
      return;
    }
    const ageSeconds = Math.max(0, (Date.now() - Date.parse(position.updatedAt)) / 1000);
    const staleAfter = Number(panel.dataset.staleAfterSeconds) || 30;
    stateNode.textContent = ageSeconds > staleAfter ? 'GPS is stale' : 'Recent GPS fix';
    detailNode.textContent = `Accuracy ±${Math.round(position.accuracyM)} m · Updated ${formatTime(position.updatedAt)}`;
    stateNode.classList.toggle('is-stale', ageSeconds > staleAfter);
    refreshParticipantMarker(panel, role);
    renderDistance(panel);
  }

  function setSharingControls(panel, sharing) {
    const start = panel.querySelector('[data-start-sharing]');
    const stop = panel.querySelector('[data-stop-sharing]');
    start.hidden = sharing;
    stop.hidden = !sharing;
  }

  function pauseServerLocation(panel) {
    const state = stateByPanel.get(panel);
    if (socket?.connected && state.joined && !state.closed) {
      socket.emit('tracking:pause', { bookingId: state.bookingId, csrfToken: panel.dataset.csrfToken });
    }
    clearLivePosition(panel, state.role);
  }

  async function resumeIfGranted(panel) {
    const state = stateByPanel.get(panel);
    if (state.closed || state.optedOut || !state.joined || !socket.connected) return;
    if (!navigator.geolocation) {
      setMessage(panel, 'This browser does not support location sharing.', true);
      return;
    }
    try {
      if (navigator.permissions?.query) {
        const permission = await navigator.permissions.query({ name: 'geolocation' });
        state.permissionStatus = permission;
        permission.onchange = () => {
          if (permission.state === 'denied') {
            state.shouldResume = false;
            if (state.watchId !== null) navigator.geolocation.clearWatch(state.watchId);
            state.watchId = null;
            state.sharing = false;
            setSharingControls(panel, false);
            panel.querySelector('[data-permission-help]').hidden = false;
            pauseServerLocation(panel);
            setMessage(panel, 'Location permission was revoked in your browser. Check site settings, then choose Share my location to retry.', true);
          } else if (permission.state === 'granted' && state.shouldResume && state.joined && !state.optedOut) {
            startWatch(panel, true);
          }
        };
        if (permission.state === 'denied') {
          panel.querySelector('[data-permission-help]').hidden = false;
          setMessage(panel, 'Location permission is blocked by your browser. Check the site location setting, then choose Share my location to retry.', true);
          return;
        }
        if (permission.state === 'granted') {
          startWatch(panel, true);
          return;
        }
      } else if (localStorage.getItem(`rail-sathi-location-granted:${state.bookingId}`) === '1') {
        startWatch(panel, true);
        return;
      }
      // On a new active booking the ordinary browser prompt is appropriate once.
      beginSharing(panel, false);
    } catch (_error) {
      beginSharing(panel, false);
    }
  }

  function joinPanel(panel) {
    const state = stateByPanel.get(panel);
    if (state.closed || !socket.connected) return;
    state.joined = false;
    socket.emit('tracking:join', {
      bookingId: state.bookingId,
      csrfToken: panel.dataset.csrfToken,
    }, (response) => {
      if (!response || !response.ok) {
        state.pendingStart = false;
        setConnection(panel, 'Tracking unavailable');
        setMessage(panel, response?.message || 'Could not join this booking tracking session.', true);
        panel.querySelector('[data-start-sharing]').disabled = true;
        return;
      }
      state.joined = true;
      state.optedOut = Boolean(response.sharingOptedOut);
      if (state.mapUnavailable) {
        setConnection(panel, 'Map unavailable');
        setMessage(panel, 'The map is unavailable. Booking location updates can still be shared securely.', true);
      }
      panel.querySelector('[data-start-sharing]').disabled = false;
      if (state.pendingStart) {
        state.pendingStart = false;
        beginSharing(panel, true);
      } else if (state.shouldResume && !state.optedOut && ['accepted', 'en_route', 'arrived', 'in_progress'].includes(state.status)) {
        resumeIfGranted(panel);
      } else if (!state.optedOut && ['accepted', 'en_route', 'arrived', 'in_progress'].includes(state.status)) {
        resumeIfGranted(panel);
      }
    });
  }

  function beginSharing(panel, userRequested = false) {
    const state = stateByPanel.get(panel);
    if (state.closed) return;
    if (!['accepted', 'en_route', 'arrived', 'in_progress'].includes(state.status)) {
      setMessage(panel, 'Location sharing will become available after the porter accepts this booking.');
      return;
    }
    if (!navigator.geolocation) {
      setMessage(panel, 'This browser does not support GPS location sharing.', true);
      return;
    }
    if (!socket.connected || !state.joined) {
      state.pendingStart = true;
      setMessage(panel, 'Connecting to the secure booking session…');
      socket.connect();
      return;
    }
    if (userRequested && state.optedOut) {
      socket.emit('tracking:resume', { bookingId: state.bookingId, csrfToken: panel.dataset.csrfToken }, (response) => {
        if (!response?.ok) {
          setMessage(panel, response?.message || 'Sharing could not be resumed for this booking.', true);
          return;
        }
        state.optedOut = false;
        beginSharing(panel, true);
      });
      return;
    }
    if (userRequested) sessionStorage.removeItem(`rail-sathi-location-attempt:${state.bookingId}`);
    startWatch(panel, userRequested);
  }

  function startWatch(panel, allowPrompt = false) {
    const state = stateByPanel.get(panel);
    state.pendingStart = false;
    if (state.sharing || state.closed || state.optedOut || !['accepted', 'en_route', 'arrived', 'in_progress'].includes(state.status)) return;
    const attemptKey = `rail-sathi-location-attempt:${state.bookingId}`;
    if (!allowPrompt && sessionStorage.getItem(attemptKey)) {
      setMessage(panel, 'Location permission is needed to share GPS. Use the button to try again after checking browser settings.');
      return;
    }
    sessionStorage.setItem(attemptKey, '1');
    setMessage(panel, 'Requesting browser permission for live location…');
    const intervalSeconds = Math.max(1, Number(panel.dataset.updateIntervalSeconds) || 3);
    const sendFix = (position) => {
      if (!state.sharing || state.optedOut || state.closed) return;
      if (!socket.connected || !state.joined) {
        setMessage(panel, 'Location sharing is paused while the booking connection reconnects.');
        return;
      }
      const now = Date.now();
      if (now - state.lastSentAt < intervalSeconds * 1000) return;
      state.lastSentAt = now;
      const fix = {
        latitude: position.coords.latitude,
        longitude: position.coords.longitude,
        accuracyM: position.coords.accuracy,
        updatedAt: new Date().toISOString(),
      };
      socket.emit('tracking:location:update', {
        bookingId: state.bookingId,
        csrfToken: panel.dataset.csrfToken,
        latitude: fix.latitude,
        longitude: fix.longitude,
        accuracyM: fix.accuracyM,
      }, (response) => {
        if (response?.ok) {
          state.sharing = true;
          localStorage.setItem(`rail-sathi-location-granted:${state.bookingId}`, '1');
          updatePosition(panel, state.role, { ...fix, updatedAt: response.updatedAt });
          setSharingControls(panel, true);
          setMessage(panel, 'Your GPS fix was shared with the other participant in this booking.');
          return;
        }
        if (response?.code === 'rate_limited') return;
        setMessage(panel, response?.message || 'The GPS update could not be sent.', true);
      });
    };
    state.watchId = navigator.geolocation.watchPosition(sendFix, (error) => {
      const messages = {
        1: 'Location permission was denied. Allow location in your browser settings, then try again.',
        2: 'Your device could not determine a location. Check GPS availability and try again.',
        3: 'GPS lookup timed out. Keep sharing on and wait for another fix, or stop sharing.',
      };
      setMessage(panel, messages[error.code] || 'The browser could not read your location.', true);
      if (error.code === 1) {
        localStorage.removeItem(`rail-sathi-location-granted:${state.bookingId}`);
        state.sharing = false;
        state.shouldResume = false;
        if (state.watchId !== null) navigator.geolocation.clearWatch(state.watchId);
        state.watchId = null;
        if (state.heartbeatId !== null) window.clearInterval(state.heartbeatId);
        state.heartbeatId = null;
        setSharingControls(panel, false);
        panel.querySelector('[data-permission-help]').hidden = false;
        pauseServerLocation(panel);
      }
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 2000 });
    state.sharing = true;
    state.shouldResume = true;
    const heartbeatMs = Math.max(10000, Math.min(15000, (Number(panel.dataset.staleAfterSeconds) || 30) * 500));
    if (state.heartbeatId !== null) window.clearInterval(state.heartbeatId);
    state.heartbeatId = window.setInterval(() => {
      if (!state.sharing || !socket.connected || !state.joined) return;
      navigator.geolocation.getCurrentPosition(sendFix, () => {}, {
        enableHighAccuracy: true, timeout: 15000, maximumAge: 0,
      });
    }, heartbeatMs);
    setSharingControls(panel, true);
  }

  function stopSharing(panel, tellServer, fromOtherTab = false) {
    const state = stateByPanel.get(panel);
    state.pendingStart = false;
    if (state.watchId !== null) navigator.geolocation.clearWatch(state.watchId);
    state.watchId = null;
    if (state.heartbeatId !== null) window.clearInterval(state.heartbeatId);
    state.heartbeatId = null;
    state.sharing = false;
    if (tellServer) {
      state.optedOut = true;
      state.shouldResume = false;
    }
    setSharingControls(panel, false);
    if (tellServer && socket.connected && state.joined && !state.closed) {
      socket.emit('tracking:stop', {
        bookingId: state.bookingId,
        csrfToken: panel.dataset.csrfToken,
      }, (response) => {
        if (!response?.ok) setMessage(panel, response?.message || 'Sharing stopped on this device; the server could not confirm the stop.', true);
      });
    }
    clearLivePosition(panel, state.role);
    if (fromOtherTab) {
      setMessage(panel, 'Location sharing was stopped from another tab or device.');
    } else if (tellServer && socket.connected && state.joined && !state.closed) {
      setMessage(panel, 'Location sharing stopped. No new GPS fixes will be sent.');
    } else {
      setMessage(panel, 'Sharing stopped on this device. The last server update will become stale if the connection is offline.');
    }
  }

  if (typeof window.io !== 'function') {
    panels.forEach((panel) => {
      setConnection(panel, 'Connection unavailable');
      setMessage(panel, 'The Socket.IO client did not load, so live tracking cannot connect.', true);
      panel.querySelector('[data-start-sharing]').disabled = true;
    });
    return;
  }

  panels.forEach((panel) => setMessage(panel, 'Loading Google Map…'));
  window.gm_authFailure = () => {
    panels.forEach((panel) => {
      const state = stateByPanel.get(panel);
      if (state) state.mapUnavailable = true;
      setConnection(panel, 'Map unavailable');
      setMessage(panel, 'Google rejected the browser key. Check its website referrer restrictions, API restrictions, and Maps JavaScript API access.', true);
    });
  };
  loadGoogleMaps().then(() => {
    panels.forEach(initializePanel);
  }).catch((error) => {
    const message = error.message === 'missing-key'
      ? 'Google Maps is not configured. Add GOOGLE_MAPS_API_KEY to the server .env file.'
      : 'Google Maps could not load. Location sharing can still run without the map.';
    panels.forEach((panel) => {
      initializePanel(panel);
      const state = stateByPanel.get(panel);
      state.mapUnavailable = true;
      setConnection(panel, 'Map unavailable');
      setMessage(panel, message, true);
    });
  }).finally(() => {
    socket = window.io({ autoConnect: false });

  socket.on('connect', () => {
    panels.forEach((panel) => {
      const state = stateByPanel.get(panel);
      if (state.mapUnavailable) {
        setConnection(panel, 'Map unavailable');
      } else {
        setConnection(panel, 'Connected', true);
      }
      joinPanel(panel);
    });
  });
  socket.on('disconnect', () => {
    panels.forEach((panel) => {
      const state = stateByPanel.get(panel);
      state.shouldResume = state.shouldResume || state.sharing;
      state.joined = false;
      if (state.watchId !== null) navigator.geolocation.clearWatch(state.watchId);
      state.watchId = null;
      if (state.heartbeatId !== null) window.clearInterval(state.heartbeatId);
      state.heartbeatId = null;
      state.sharing = false;
      setSharingControls(panel, false);
      setConnection(panel, 'Connection lost');
      setMessage(panel, 'The tracking connection was interrupted. GPS capture has paused; reconnect and start sharing again.');
    });
  });
  socket.on('connect_error', () => {
    panels.forEach((panel) => setConnection(panel, 'Could not connect'));
  });
  socket.on('tracking:state', (payload) => {
    const panel = panelByBooking.get(Number(payload.bookingId));
    if (!panel) return;
    const state = stateByPanel.get(panel);
    if (payload.status) state.status = payload.status;
    if (payload.sharingOptedOut) {
      state.optedOut = true;
      state.shouldResume = false;
      setMessage(panel, 'Location sharing is paused because you stopped it previously. Choose Share my location to resume.');
    }
    const pickup = payload.pickup || {};
    if (window.google?.maps && state.map && pickup.latitude !== null && pickup.longitude !== null && pickup.latitude !== undefined && pickup.longitude !== undefined && !state.pickupMarker) {
      const point = { lat: pickup.latitude, lng: pickup.longitude };
      state.pickupMarker = new google.maps.Marker({
        map: state.map, position: point, title: `Pickup · ${pickup.label || panel.dataset.pickupLabel}`,
        icon: { path: google.maps.SymbolPath.CIRCLE, scale: 9, fillColor: '#d9272e', fillOpacity: 1, strokeColor: '#ffffff', strokeWeight: 3 },
      });
      state.pickupMarker.addListener('click', () => {
        state.infoWindow.setContent(document.createTextNode(`Pickup · ${pickup.label || panel.dataset.pickupLabel}`));
        state.infoWindow.open({ map: state.map, anchor: state.pickupMarker });
      });
      panel.querySelector('[data-tracking-map-empty]').hidden = true;
    }
    Object.entries(payload.locations || {}).forEach(([role, position]) => updatePosition(panel, role, position));
  });
  socket.on('tracking:booking_active', (payload) => {
    const panel = panelByBooking.get(Number(payload.bookingId));
    if (!panel) return;
    const state = stateByPanel.get(panel);
    state.status = payload.status || 'en_route';
    if (!state.optedOut) resumeIfGranted(panel);
  });
  socket.on('tracking:location', (payload) => {
    const panel = panelByBooking.get(Number(payload.bookingId));
    if (!panel || !['passenger', 'porter'].includes(payload.role)) return;
    updatePosition(panel, payload.role, payload);
  });
  socket.on('tracking:participant_stopped', (payload) => {
    const panel = panelByBooking.get(Number(payload.bookingId));
    if (!panel || !['passenger', 'porter'].includes(payload.role)) return;
    if (payload.role === stateByPanel.get(panel).role) {
      const state = stateByPanel.get(panel);
      state.optedOut = true;
      state.shouldResume = false;
      stopSharing(panel, false, true);
    }
    else clearLivePosition(panel, payload.role);
  });
  socket.on('tracking:closed', (payload) => {
    const panel = panelByBooking.get(Number(payload.bookingId));
    if (!panel) return;
    const state = stateByPanel.get(panel);
    stopSharing(panel, false);
    state.closed = true;
    state.joined = false;
    panel.querySelector('[data-start-sharing]').disabled = true;
    setConnection(panel, 'Tracking ended');
    setMessage(panel, 'This booking is complete, cancelled, or no longer assigned. Location sharing has ended.');
  });
  socket.on('tracking:error', (payload) => {
    const panel = panelByBooking.get(Number(payload.bookingId));
    if (panel) setMessage(panel, payload.message || 'Tracking could not be updated.', true);
  });

  window.setInterval(() => {
    panels.forEach((panel) => ['passenger', 'porter'].forEach((role) => renderParticipant(panel, role)));
  }, 5000);
    socket.connect();
  });
})();

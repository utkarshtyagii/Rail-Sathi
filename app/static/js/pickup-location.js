(() => {
  const setupPinControl = (kind) => {
    const control = document.querySelector(`[data-${kind}-location]`);
    if (!control) return;
    const prefix = kind === 'pickup' ? 'pickup' : 'destination';
    const useButton = control.querySelector(`[data-${prefix}-use-location]`);
    const clearButton = control.querySelector(`[data-${prefix}-clear-location]`);
    const latitudeInput = control.querySelector(`[data-${prefix}-latitude]`);
    const longitudeInput = control.querySelector(`[data-${prefix}-longitude]`);
    const status = control.querySelector(`[data-${prefix}-location-status]`);
    const label = kind === 'pickup' ? 'pickup' : 'destination';

    useButton.addEventListener('click', () => {
      if (!navigator.geolocation) {
        status.textContent = 'This browser does not support location. The typed point will still be saved.';
        return;
      }
      useButton.disabled = true;
      status.textContent = 'Requesting permission for a one-time map pin…';
      navigator.geolocation.getCurrentPosition((position) => {
        latitudeInput.value = position.coords.latitude;
        longitudeInput.value = position.coords.longitude;
        status.textContent = `${label[0].toUpperCase()}${label.slice(1)} pin ready (accuracy about ${Math.round(position.coords.accuracy)} m).`;
        clearButton.hidden = false;
        useButton.disabled = false;
      }, (error) => {
        const messages = {
          1: 'Location permission was denied. The typed point will still be saved.',
          2: 'Your device could not determine a location. Try again or keep the typed point.',
          3: 'Location lookup timed out. Try again or keep the typed point.',
        };
        status.textContent = messages[error.code] || 'Location is unavailable. The typed point will still be saved.';
        useButton.disabled = false;
      }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 0 });
    });
    clearButton.addEventListener('click', () => {
      latitudeInput.value = '';
      longitudeInput.value = '';
      clearButton.hidden = true;
      status.textContent = `Map pin removed. Your typed ${label} will still be saved.`;
    });
  };
  setupPinControl('pickup');
  setupPinControl('destination');
})();

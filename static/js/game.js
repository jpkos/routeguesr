(() => {
  const form = document.querySelector('#guess-form');
  const input = document.querySelector('#guess');
  const map = document.querySelector('#route-map');
  const waiting = document.querySelector('#waiting-message');
  const ownStatus = document.querySelector('#own-status');
  const opponentStatus = document.querySelector('#opponent-status');
  const counter = document.querySelector('#round-number');
  const interruptedDialog = document.querySelector('#interrupted-dialog');
  const leftPlayer = document.querySelector('#left-player');
  let round = 0;
  let busy = false;
  let refreshTimer;

  function updateOptions(options) {
    input.replaceChildren(new Option('Valitse reitti', '', true, true));
    input.options[0].disabled = true;
    options.forEach(option => input.add(new Option(option, option)));
  }

  function showInterrupted(state) {
    clearInterval(refreshTimer);
    form.hidden = true;
    waiting.hidden = true;
    leftPlayer.textContent = state.left_name || state.opponent_name || 'Vastustajasi';
    interruptedDialog.hidden = false;
  }

  function render(state) {
    if (state.status === 'finished') {
      location.href = state.results_url;
      return;
    }
    if (state.status === 'abandoned') {
      if (state.opponent_left) showInterrupted(state);
      else location.href = '/';
      return;
    }
    if (state.round !== round) {
      round = state.round;
      counter.textContent = round + 1;
      map.src = GAME.mapUrl.replace('{round}', round);
      updateOptions(state.options);
      form.hidden = false;
      waiting.hidden = true;
    }
    ownStatus.className = state.has_guessed ? 'ready' : '';
    opponentStatus.className = state.opponent_has_guessed ? 'ready' : '';
    if (state.has_guessed) {
      form.hidden = true;
      waiting.hidden = false;
    }
  }

  async function refresh() {
    try {
      const response = await fetch(GAME.stateUrl, {cache: 'no-store'});
      if (response.ok) render(await response.json());
    } catch (_) {
      // A temporary connection problem is retried on the next poll.
    }
  }

  form.onsubmit = async event => {
    event.preventDefault();
    if (busy || !input.value.trim()) return;
    busy = true;
    const button = form.querySelector('button');
    button.disabled = true;
    try {
      const response = await fetch(GAME.guessUrl, {
        method: 'POST',
        body: new FormData(form),
      });
      if (response.ok) render(await response.json());
    } finally {
      busy = false;
      button.disabled = false;
    }
  };

  refresh();
  refreshTimer = setInterval(refresh, 1100);
})();

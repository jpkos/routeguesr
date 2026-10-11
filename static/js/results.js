(() => {
  const requestDialog = document.querySelector('#rematch-request-dialog');
  const waitingDialog = document.querySelector('#rematch-waiting-dialog');
  const requester = document.querySelector('#rematch-requester');
  let timer;

  function render(state) {
    if (state.rematch_status === 'accepted' && state.rematch_id) {
      clearInterval(timer);
      location.href = RESULTS_GAME.playUrl.replace('REMATCH_ID', state.rematch_id);
      return;
    }
    if (state.rematch_status === 'declined') {
      clearInterval(timer);
      location.href = RESULTS_GAME.homeUrl;
      return;
    }
    if (state.rematch_status !== 'pending') return;

    if (state.rematch_requested_by_opponent) {
      requester.textContent = state.rematch_requested_name || state.opponent_name;
      requestDialog.hidden = false;
      waitingDialog.hidden = true;
    } else if (state.rematch_requested_by_you) {
      requestDialog.hidden = true;
      waitingDialog.hidden = false;
    }
  }

  async function refresh() {
    try {
      const response = await fetch(RESULTS_GAME.stateUrl, {cache: 'no-store'});
      if (response.ok) render(await response.json());
    } catch (_) {
      // A temporary connection problem is retried on the next poll.
    }
  }

  refresh();
  timer = setInterval(refresh, 1100);
})();

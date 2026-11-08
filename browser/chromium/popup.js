'use strict';
const statusNode = document.getElementById('status');
const toggle = document.getElementById('toggle');
const errorNode = document.getElementById('error');
function show(state) {
  statusNode.textContent = state.paused
    ? 'Website observations are paused in this browser.'
    : state.connected && state.accepted
      ? 'Website domain sharing is on and connected to the local agent.'
      : 'Website sharing is on, but the local agent is not connected. No website observations are being sent right now.';
  toggle.textContent = state.paused ? 'Resume website observations' : 'Pause website observations';
  toggle.disabled = false;
}
function refresh() {
  toggle.disabled = true;
  chrome.runtime.sendMessage({type:'website-visibility-status'}, state => {
    if (chrome.runtime.lastError || !state) {
      statusNode.textContent = 'Could not check website visibility. Close and reopen this panel.';
      return;
    }
    show(state);
  });
}
toggle.addEventListener('click', () => {
  toggle.disabled = true;
  errorNode.hidden = true;
  chrome.runtime.sendMessage({type:'website-visibility-pause', paused:toggle.textContent.startsWith('Pause')}, state => {
    if (chrome.runtime.lastError || !state) {
      errorNode.textContent = 'Could not change the website-visibility setting.';
      errorNode.hidden = false;
      refresh();
      return;
    }
    if (state.error) {
      errorNode.textContent = state.error;
      errorNode.hidden = false;
    }
    show(state);
  });
});
refresh();

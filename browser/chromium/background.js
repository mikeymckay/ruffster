importScripts('domain.js');

// Only pause and a temporary estimate-continuity reset are stored. Website
// domains are sent to the local agent and are never persisted in extension storage.
let port;
let retry;
let initialized;
let paused = false;
let connected = false;
let lastAccepted = false;
let resetContinuity = false;
let sampling = false;

function initialize() {
  if (!initialized) {
    initialized = new Promise(resolve => {
      chrome.storage.local.get({websiteObservationsPaused: false, websiteContinuityReset: false}, result => {
        paused = result?.websiteObservationsPaused === true;
        resetContinuity = paused || result?.websiteContinuityReset === true;
        updateBadge();
        resolve();
      });
    });
  }
  return initialized;
}

function updateBadge() {
  const text = paused ? 'Off' : connected && lastAccepted ? 'On' : connected ? '…' : '!';
  const title = paused
    ? 'Website observations paused. Click to review or resume.'
    : connected && lastAccepted
      ? 'Website domain observations are being sent to the local Family Activity agent.'
      : 'Website observations are waiting for the local Family Activity agent.';
  chrome.action.setBadgeText({text});
  chrome.action.setBadgeBackgroundColor({color: paused ? '#6c756f' : connected && lastAccepted ? '#27734d' : '#aa5a20'});
  chrome.action.setTitle({title});
}

function setContinuityReset(value = true) {
  resetContinuity = value;
  chrome.storage.local.set({websiteContinuityReset: value}, () => {});
}

function connect() {
  initialize().then(() => {
    if (paused || port) return;
    try {
      const channel = chrome.runtime.connectNative('org.familyactivity.browser');
      port = channel;
      connected = true;
      lastAccepted = false;
      channel.onDisconnect.addListener(() => {
        if (port === channel) port = undefined;
        connected = false;
        lastAccepted = false;
        setContinuityReset();
        updateBadge();
        if (!paused) {
          clearTimeout(retry);
          retry = setTimeout(connect, 15000);
        }
      });
      channel.onMessage.addListener(message => {
        lastAccepted = message?.accepted === true;
        updateBadge();
      });
      updateBadge();
      if (!paused) sample();
    } catch (_) {
      connected = false;
      setContinuityReset();
      updateBadge();
      clearTimeout(retry);
      retry = setTimeout(connect, 15000);
    }
  });
}

async function sample() {
  await initialize();
  if (!port || paused || sampling) return;
  sampling = true;
  try {
    const window = await chrome.windows.getLastFocused();
    if (window.incognito) {
      setContinuityReset();
      return;
    }
    const tabs = await chrome.tabs.query({active: true, windowId: window.id});
    const tab = tabs?.[0];
    if (tab?.incognito) {
      setContinuityReset();
      return;
    }
    const domain = domainFromTab(window, tab);
    if (!port || paused) return;
    if (resetContinuity) {
      try { port.postMessage({domain: null}); }
      catch (_) { return; }
      setContinuityReset(false);
    }
    try { port.postMessage({domain}); } catch (_) { /* Connection state is shown by the badge. */ }
  } catch (_) { /* No valid foreground domain is an unknown observation. */ }
  finally { sampling = false; }
}

function setPaused(value) {
  return initialize().then(() => new Promise(resolve => {
    const previous = paused;
    const previousReset = resetContinuity;
    paused = value;
    if (paused) resetContinuity = true;
    chrome.storage.local.set({websiteObservationsPaused: paused, websiteContinuityReset: resetContinuity}, () => {
      if (chrome.runtime.lastError) {
        paused = previous;
        resetContinuity = previousReset;
        updateBadge();
        resolve({paused, error: 'Could not save this website-visibility setting.'});
        return;
      }
      updateBadge();
      if (paused) {
        clearTimeout(retry);
      } else {
        connect();
        sample();
      }
      resolve({paused});
    });
  }));
}

chrome.runtime.onMessage.addListener((message, _sender, respond) => {
  if (message?.type === 'website-visibility-status') {
    initialize().then(() => respond({paused, connected, accepted: lastAccepted}));
    return true;
  }
  if (message?.type === 'website-visibility-pause') {
    setPaused(message.paused === true).then(respond);
    return true;
  }
  return false;
});

chrome.tabs.onActivated.addListener(sample);
chrome.tabs.onUpdated.addListener((_id, info, tab) => { if (tab.active && info.url) sample(); });
chrome.windows.onFocusChanged.addListener(sample);
chrome.runtime.onStartup.addListener(connect);
chrome.runtime.onInstalled.addListener(connect);
connect();
setInterval(sample, 15000);

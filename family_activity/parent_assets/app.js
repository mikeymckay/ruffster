'use strict';
const $ = id => document.getElementById(id);
let status;
let keyShareTimer;
let backupDownloadedThisSession = false;
let selectedDeviceId;
let reportDeviceInitialized = false;
function show(message) { $('message').textContent = message; }
async function api(path, options = {}) {
  const response = await fetch(path, {credentials:'same-origin', ...options});
  const body = await response.json();
  if (!response.ok) throw new Error(body.error || 'The request failed.');
  return body;
}
function post(path, value) {
  return api(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(value)});
}
function formatUtcTimestamp(value) {
  const date = new Date(value);
  if (!value || !Number.isFinite(date.getTime())) return 'time unavailable';
  return new Intl.DateTimeFormat(undefined, {
    year:'numeric', month:'short', day:'numeric', hour:'numeric', minute:'2-digit',
    timeZone:'UTC', timeZoneName:'short'
  }).format(date);
}
async function refresh() {
  status = await api('/api/status');
  updateSetupProgress();
  $('key-form').hidden = status.unlocked;
  $('key-state').hidden = !status.unlocked;
  $('restore-wrap').hidden = status.has_key;
  $('key-button').textContent = status.has_key ? 'Unlock parent access' : 'Set up parent access';
  $('password').autocomplete = status.has_key ? 'current-password' : 'new-password';
  $('confirm').autocomplete = status.has_key ? 'off' : 'new-password';
  $('password').inputMode = status.has_key ? 'text' : 'numeric';
  $('confirm').inputMode = 'numeric';
  if (status.has_key) {
    $('password').removeAttribute('minlength'); $('password').removeAttribute('maxlength');
    $('confirm').removeAttribute('minlength'); $('confirm').removeAttribute('maxlength');
    $('password').removeAttribute('pattern'); $('password').removeAttribute('title');
    $('confirm').removeAttribute('pattern'); $('confirm').removeAttribute('title');
    $('access-label').textContent = 'Your parent access PIN or older phrase';
    $('phrase-help').textContent = 'Enter the six-digit PIN you chose, or the longer phrase from an older setup.';
    $('confirm-label').textContent = 'Repeat only when creating parent access';
  } else {
    $('password').minLength = 6; $('password').maxLength = 6;
    $('confirm').minLength = 6; $('confirm').maxLength = 6;
    $('password').pattern = '[0-9]{6}'; $('password').title = 'Enter six digits.';
    $('confirm').pattern = '[0-9]{6}'; $('confirm').title = 'Enter six digits.';
    $('access-label').textContent = 'Your parent access PIN';
    $('phrase-help').textContent = "Choose six numbers your child doesn't know. Keep the recovery copy somewhere you can find it.";
    $('confirm-label').textContent = 'Enter the PIN again';
  }
  $('confirm-wrap').hidden = status.has_key;
  $('confirm').required = !status.has_key;
  $('change-pin').hidden = !status.unlocked;
  $('backup-required').hidden = !(status.unlocked && !status.backup_confirmed);
  $('download-backup').hidden = !status.unlocked || !status.backup_confirmed;
  $('download-public').hidden = !status.unlocked || !status.backup_confirmed;
  $('download-public-fallback').hidden = !status.unlocked || !status.backup_confirmed;
  $('lock').hidden = !status.unlocked;
  $('import').disabled = !status.unlocked;
  $('connect').disabled = !status.unlocked || !/^[0-9]{2}$/.test($('connection-code').value);
  $('child-setup').hidden = !(status.unlocked && status.backup_confirmed);
  $('report-transfer').hidden = !status.unlocked;
  $('school-settings').hidden = !(status.unlocked && status.has_report);
  $('retention-settings').hidden = !(status.unlocked && status.has_report);
  $('download-report-backup').hidden = !(status.unlocked && status.has_report);
  $('delete-report').hidden = !(status.unlocked && status.has_report);
  $('prepare-key-share').disabled = !status.unlocked || !status.backup_confirmed;
  if (!status.unlocked || status.backup_confirmed) {
    backupDownloadedThisSession = false;
    $('backup-confirm-check').checked = false;
    $('confirm-backup').disabled = true;
  }
  if (status.unlocked) {
    const settings = await api('/api/settings');
    $('retention-days').value = String(settings.retention_days);
    const config = (await api('/api/schedule')).schedule;
    if (config) {
      $('zone').value=config.timezone; $('school-start').value=config.start; $('school-end').value=config.end;
      document.querySelectorAll('[name=school-day]').forEach(box => { box.checked=config.days.includes(Number(box.value)); });
    } else if (!$('zone').value) {
      let localZone = '';
      try { localZone = Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (_) {}
      $('zone').value = localZone;
      if (!localZone) $('zone-help').textContent = 'This computer did not provide a time zone. Enter the local time zone where your child attends school.';
    }
  }
  $('report').hidden = !(status.unlocked && status.has_report);
  if (status.unlocked && status.has_report) await render();
}
function updateSetupProgress() {
  const current = !status.has_key || !status.unlocked || !status.backup_confirmed ? 0 : !status.has_report ? 1 : 3;
  const titles = [...document.querySelectorAll('#setup-progress li')];
  titles.forEach((step, index) => {
    step.classList.toggle('complete', index < current);
    step.classList.toggle('current', index === current);
    if (index === current) step.setAttribute('aria-current', 'step');
    else step.removeAttribute('aria-current');
  });
  $('step-one-title').textContent = !status.has_key ? 'Set up parent access' : !status.unlocked ? 'Unlock parent access' : !status.backup_confirmed ? 'Save your recovery copy' : 'Parent access is ready';
  $('step-one-state').textContent = current > 0 ? 'Ready on this device.' : !status.has_key ? 'Choose a six-digit PIN only you know.' : !status.unlocked ? 'Enter your PIN below to continue.' : 'Save your recovery copy before setting up the child computer.';
  $('step-two-state').textContent = status.has_report ? 'A report has arrived; add another computer if needed.' : !status.backup_confirmed ? 'Save your recovery copy before setting up a child computer.' : current === 1 ? 'Enter these two digits on one child computer.' : 'Ready after parent access is unlocked.';
  $('step-three-state').textContent = status.has_report ? 'Encrypted report received on this device.' : 'Later, bring the encrypted report back here.';
  const messages = [
    !status.has_key ? 'Next: set up parent access with a six-digit PIN only you know.' : !status.unlocked ? 'Next: unlock parent access with your PIN.' : !status.backup_confirmed ? 'Next: save your recovery copy somewhere you control before setting up the child computer.' : 'Parent access is ready. You can continue with child setup.',
    'Next: set up one child computer together. Repeat for each child, then bring encrypted reports back here.',
    'Next: set up one child computer together. Repeat for each child, then bring encrypted reports back here.',
    'Next: name each computer and review its report together. Times are estimates, and missing observations do not explain why they are missing.'
  ];
  $('next-step').textContent = messages[current];
}
// Let a parent check for typing mistakes, then return both fields to masking.
$('toggle-passphrase').addEventListener('click', () => {
  const reveal = $('password').type === 'password';
  $('password').type = reveal ? 'text' : 'password';
  $('confirm').type = reveal ? 'text' : 'password';
  $('toggle-passphrase').textContent = reveal ? 'Hide PIN' : 'Show PIN';
  $('toggle-passphrase').setAttribute('aria-pressed', String(reveal));
});
$('download-backup-required').addEventListener('click', () => {
  backupDownloadedThisSession = true;
  $('backup-note').textContent = 'After the download finishes, save this file somewhere you control. The child computer only receives the part that can lock reports.';
  $('confirm-backup').disabled = !$('backup-confirm-check').checked;
});
$('backup-confirm-check').addEventListener('change', () => {
  $('confirm-backup').disabled = !backupDownloadedThisSession || !$('backup-confirm-check').checked;
});
$('confirm-backup').addEventListener('click', async () => {
  if (!backupDownloadedThisSession || !$('backup-confirm-check').checked) return;
  $('confirm-backup').disabled = true;
  try {
    await post('/api/confirm-key-backup', {confirmed:true});
    show('Recovery copy saved. Child setup is now available.');
    await refresh();
  } catch (error) {
    $('backup-note').textContent = error.message;
    $('confirm-backup').disabled = false;
  }
});
$('restore-key').addEventListener('click', async () => {
  const file = $('restore-file').files[0];
  const passphrase = $('restore-passphrase').value;
  if (!file) { $('restore-note').textContent = 'Choose your encrypted recovery copy first.'; return; }
  if (file.size > 512) { $('restore-note').textContent = 'That file is too large to be a recovery copy. Choose the encrypted .vault file.'; return; }
  if (!passphrase) { $('restore-note').textContent = 'Enter your parent access PIN (or the older phrase used for this recovery copy).'; return; }
  $('restore-key').disabled = true;
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const backup = btoa(String.fromCharCode(...bytes));
    await post('/api/restore-key', {backup, passphrase});
    $('restore-note').textContent = 'Parent access restored and unlocked on this device.';
    show('Parent access restored. Your encrypted reports can now be opened on this device.');
    await refresh();
  } catch (error) {
    $('restore-note').textContent = error.message;
  } finally {
    $('restore-passphrase').value = '';
    $('restore-file').value = '';
    $('restore-key').disabled = false;
  }
});
$('prepare-key-share').addEventListener('click', async () => {
  $('prepare-key-share').disabled = true;
  try {
    const result = await post('/api/public-key-share', {});
    $('public-key-code').value = result.code;
    $('public-key-code').hidden = false;
    $('copy-key-code').hidden = false;
    $('stop-key-share').hidden = false;
    if (keyShareTimer) clearInterval(keyShareTimer);
    let remaining = result.expires_in;
    $('key-share-note').textContent = `Use these two digits on the child's setup screen within about five minutes. Keep both computers on the same Wi-Fi. If time runs out, choose Show two digits again.`;
    keyShareTimer = setInterval(() => {
      remaining -= 1;
      if (remaining <= 0) {
        clearInterval(keyShareTimer); keyShareTimer = undefined;
        $('public-key-code').value = '';
        $('public-key-code').hidden = true;
        $('copy-key-code').hidden = true;
        $('stop-key-share').hidden = true;
        $('key-share-note').textContent = 'These digits are no longer active. If the child is still setting up, choose Show two digits again.';
      } else {
        $('key-share-note').textContent = `Use these two digits on the child's setup screen within about five minutes. Keep both computers on the same Wi-Fi. If time runs out, choose Show two digits again.`;
      }
    }, 1000);
    show('Two digits ready. Enter them on the child computer setup screen.');
  } catch (error) {
    $('key-share-note').textContent = error.message;
    show(error.message);
  } finally {
    $('prepare-key-share').disabled = !status.unlocked;
  }
});
$('copy-key-code').addEventListener('click', async () => {
  try { await navigator.clipboard.writeText($('public-key-code').value); show('Digits copied. Enter them on the child computer setup screen.'); }
  catch (_) { $('public-key-code').focus(); $('public-key-code').select(); show('Select and copy the two digits.'); }
});
$('stop-key-share').addEventListener('click', async () => {
  try {
    await post('/api/public-key-share/stop', {});
    if (keyShareTimer) clearInterval(keyShareTimer);
    keyShareTimer = undefined;
    $('public-key-code').value = ''; $('public-key-code').hidden = true;
    $('copy-key-code').hidden = true; $('stop-key-share').hidden = true;
    $('key-share-note').textContent = 'Sharing stopped.';
  } catch (error) { show(error.message); }
});
function list(id, entries, formatter, emptyMessage = 'No observations available.') {
  const container = $(id); container.replaceChildren();
  if (!entries.length) { const item=document.createElement('li'); item.textContent=emptyMessage; container.appendChild(item); return; }
  for (const entry of entries) { const item=document.createElement('li'); item.textContent=formatter(entry); container.appendChild(item); }
}
async function render() {
  let data = await api('/api/report');
  const deviceIds = (data.devices || []).map(device => device.device_id);
  if (!reportDeviceInitialized || !deviceIds.includes(selectedDeviceId)) {
    selectedDeviceId = deviceIds[0] || '';
    reportDeviceInitialized = true;
  }
  if (selectedDeviceId && data.selected_device !== selectedDeviceId) {
    data = await api(`/api/report?device=${encodeURIComponent(selectedDeviceId)}`);
  }
  const picker = $('report-device'); picker.replaceChildren();
  for (const device of data.devices || []) {
    const option = document.createElement('option');
    option.value = device.device_id; option.textContent = device.label;
    picker.appendChild(option);
  }
  picker.value = selectedDeviceId;
  const selected = (data.devices || []).find(device => device.device_id === selectedDeviceId);
  $('device-label-form').hidden = !selected;
  $('delete-computer').hidden = !selected;
  $('device-label').value = selected ? selected.label : '';
  $('device-last-seen').textContent = selected
    ? `Most recent recorded session: ${formatUtcTimestamp(selected.last_seen)}. Bring back another report to update this view.`
    : 'No computer sessions have been added to this report yet.';
  list('conversation-prompts', data.conversation_prompts || [], value => value);
  const freshness = data.recorded_through
    ? `Data in this imported snapshot was recorded through ${formatUtcTimestamp(data.recorded_through)}. Bring back another report to see more recent activity.`
    : 'No dated activity has been added to this report yet.';
  const runtime = data.agent_runtime || {seconds:0,sessions:0,gaps:0,restarts:0};
  const runtimeHours = Math.floor(runtime.seconds / 3600);
  const runtimeMinutes = Math.floor((runtime.seconds % 3600) / 60);
  const restartCount = runtime.restarts || 0;
  const restartSummary = restartCount === 1
    ? '1 observed restart followed a session without a recorded stop'
    : restartCount === 0
      ? 'No restarts followed a session without a recorded stop'
      : `${restartCount} observed restarts followed sessions without recorded stops`;
  const sessionLabel = `${runtime.sessions} session${runtime.sessions === 1 ? '' : 's'}`;
  const intervalSummary = runtime.gaps === 1
    ? '1 unobserved interval is listed below'
    : `${runtime.gaps} unobserved intervals are listed below`;
  const runtimeSummary = runtime.sessions
    ? `Ruffster was running for about ${runtimeHours} hr ${runtimeMinutes} min across ${sessionLabel} in the past ${runtime.days} days. ${restartSummary}. The report cannot tell why. ${intervalSummary}.`
    : `No Ruffster uptime was recorded in the past ${runtime.days || 7} days.`;
  $('monitoring-summary').textContent = runtimeSummary;
  const runtimeText = runtime.sessions
    ? `${runtimeSummary} A restart record does not say why the earlier session ended; that can follow a crash, sleep, power-off, or another interruption. Ruffster uptime shows when the agent was running; it is separate from estimated app time.`
    : runtimeSummary;
  $('snapshot-note').textContent = freshness;
  $('report-timezone-note').textContent = `Daily and weekly calendar days use ${data.report_timezone || 'UTC'}. Observation timestamps remain in UTC.`;
  const websiteObservations = data.website_observations || {count: 0, latest_at: null};
  const hasWebsiteDetails = websiteObservations.count > 0;
  for (const section of document.querySelectorAll('.website-observation-section')) {
    section.hidden = !hasWebsiteDetails;
  }
  $('website-status').textContent = websiteObservations.count > 0
    ? `Website details from the optional add-on: ${websiteObservations.count}. Most recent: ${formatUtcTimestamp(websiteObservations.latest_at)}.`
    : 'No website details were recorded in this report. Website sharing is optional; see “How website information works” for details.';
  $('coverage').textContent = `${runtimeText} ${data.incomplete ? 'Some older session starts are unavailable, so coverage may be incomplete. ' : ''}${data.sessions.length} recent session record(s) and ${data.gaps.length} unobserved interval(s) shown (up to 20 of each).`;
  const formatTime = ([name,seconds]) => `${name}: about ${(seconds/60).toFixed(1)} min`;
  const formatBytes = value => {
    const units = ['B', 'kB', 'MB', 'GB', 'TB'];
    let amount = value, unit = 0;
    while (amount >= 1000 && unit < units.length - 1) { amount /= 1000; unit += 1; }
    return `${amount.toLocaleString(undefined, {maximumFractionDigits: unit ? 1 : 0})} ${units[unit]}`;
  };
  const formatTrafficTotal = ([iface,received,sent]) => `${iface}: ${formatBytes(received)} received · ${formatBytes(sent)} sent`;
  list('apps', data.apps.today, formatTime, 'No app details were recorded for this period.');
  list('sites', data.sites.today, formatTime, 'No website details were recorded for this period.');
  list('apps-week', data.apps.week, formatTime, 'No app details were recorded for this period.');
  list('sites-week', data.sites.week, formatTime, 'No website details were recorded for this period.');
  const categoryFormat = ([name,seconds]) => `${name}: about ${(seconds/60).toFixed(1)} min`;
  list('categories-today', data.site_categories.today, categoryFormat, 'No website observations could be categorized.');
  list('categories-week', data.site_categories.week, categoryFormat, 'No website observations could be categorized.');
  const format = ([name,seconds]) => `${name}: about ${(seconds/60).toFixed(1)} min`;
  list('school-apps', data.contexts.apps.school, format, 'No app observations are available for these scheduled hours.');
  list('school-sites', data.contexts.sites.school, format, 'No website observations are available for these scheduled hours.');
  list('school-traffic', data.traffic_contexts.school, formatTrafficTotal,
       'No network measurements were available for these scheduled hours.');
  list('home-apps', data.contexts.apps.home, format, 'No app observations are available for this network label.');
  list('home-sites', data.contexts.sites.home, format, 'No website observations are available for this network label.');
  list('home-traffic', data.traffic_contexts.home, formatTrafficTotal,
       'No network measurements were available for this Home-labeled network.');
  list('school-network-apps', data.contexts.apps.school_network, format, 'No app details were recorded for this School-labeled network.');
  list('school-network-sites', data.contexts.sites.school_network, format, 'No website observations are linked to a School-labeled network.');
  list('school-network-traffic', data.traffic_contexts.school_network, formatTrafficTotal, 'No network measurements were available for this School-labeled network.');
  list('other-network-apps', data.contexts.apps.other_network, format, 'No app observations are linked to an Other-labeled network.');
  list('other-network-sites', data.contexts.sites.other_network, format, 'No website observations are linked to an Other-labeled network.');
  list('other-network-traffic', data.traffic_contexts.other_network, formatTrafficTotal, 'No network measurements were available for this Other-labeled network.');
  list('categories-school', data.category_contexts.school, categoryFormat, 'No categorized website observations are available for these hours.');
  list('categories-home', data.category_contexts.home, categoryFormat, 'No categorized website observations are available for this network label.');
  list('categories-school-network', data.category_contexts.school_network, categoryFormat, 'No categorized website observations are linked to a School-labeled network.');
  list('categories-other-network', data.category_contexts.other_network, categoryFormat, 'No categorized website observations are linked to an Other-labeled network.');
  $('schedule-note').textContent = !data.contexts.schedule_configured ? 'Save school hours above to see this view.' : (data.contexts.apps.schedule_uncertain || data.contexts.sites.schedule_uncertain || data.traffic_contexts.schedule_uncertain ? 'Some times could not be classified because a schedule boundary was ambiguous.' : 'School hours use your chosen time zone.');
  const settings = data.network_settings;
  const settingLines = [];
  if (settings) {
    $('settings-observed').textContent = `Last observed ${formatUtcTimestamp(settings.sampled_at)}. These are indicators from the operating-system settings the agent can inspect.`;
    settingLines.push(`DNS configuration: ${settings.dns_observed === true ? 'a resolver address appeared in the settings Ruffster can inspect' : settings.dns_observed === false ? 'no resolver address appeared in the settings Ruffster can inspect' : 'unavailable'}`);
    settingLines.push(`System proxy: ${settings.proxy_indicator === true ? 'a supported proxy setting was enabled' : settings.proxy_indicator === false ? 'no enabled supported proxy setting was reported' : 'unknown'}`);
    settingLines.push(`VPN connection: ${settings.vpn_indicator === true ? 'a supported VPN connection appears active; other VPN apps may not be detected' : settings.vpn_indicator === false ? 'no built-in VPN connection appeared active; other VPN apps may not be detected' : 'could not check VPN status; some VPN apps may not be detected'}`);
  } else {
    $('settings-observed').textContent = 'No system settings observation is in this report.';
  }
  list('settings-list', settingLines, value => value);
  list('traffic-today', data.traffic_usage.today, formatTrafficTotal,
       'No network measurements are available for today.');
  list('traffic-week-summary', data.traffic_usage.week, formatTrafficTotal,
       'No network measurements are available for these seven days.');
  list('traffic', data.traffic, ([at,iface,received,sent]) => `${formatUtcTimestamp(at)} · ${iface}: ${formatBytes(received)} received, ${formatBytes(sent)} sent`, 'No interface measurements were recorded in this report.');
  const processTraffic = data.process_traffic || {status: null, today: [], week: []};
  $('process-traffic-status').textContent = processTraffic.status === 'enabled'
    ? 'This optional Mac source was enabled. It records process-associated byte deltas, not website traffic. Some connections may belong to helper services.'
    : processTraffic.status === 'unavailable'
      ? 'The optional process-based network measurement was unavailable during this session.'
      : processTraffic.status === 'disabled'
        ? 'Process-associated network totals were turned off during the latest monitoring session.'
        : processTraffic.status === 'unsupported'
          ? 'Process-associated network totals are currently available only on macOS.'
          : 'Process-associated network totals were not included in this report. They may not have been enabled on the child’s Mac.';
  const formatProcessTraffic = ([process,received,sent]) => `${process}: ${formatBytes(received)} received · ${formatBytes(sent)} sent`;
  list('process-traffic-today', processTraffic.today, formatProcessTraffic,
       'No process-based network measurements were recorded today.');
  list('process-traffic-week', processTraffic.week, formatProcessTraffic,
       'No process-based network measurements were recorded for these seven days.');
  const networks = $('networks'); networks.replaceChildren();
  if (!data.networks.length) networks.textContent = 'No network changes could be identified in this report.';
  for (const network of data.networks) {
    const row = document.createElement('div'), label = document.createElement('label'), select = document.createElement('select');
    const id = `network-${network.identifier}`;
    label.htmlFor = id; label.textContent = `Network ${network.identifier.slice(0, 8)}… · last seen ${formatUtcTimestamp(network.last_seen)}`; select.id = id;
    for (const [value, text] of [['','Unknown'], ['home','Home'], ['school','School'], ['other','Other']]) {
      const option = document.createElement('option'); option.value=value; option.textContent=text; select.appendChild(option);
    }
    select.value=network.label || '';
    select.addEventListener('change', async () => {
      try { await post('/api/network-label', {identifier:network.identifier, label:select.value || null}); show('Network label saved on this device.'); await render(); }
      catch(error) { show(error.message); await render(); }
    });
    row.append(label,select); networks.appendChild(row);
  }
  list('gaps', data.gaps, ([start,end]) => `${formatUtcTimestamp(start)} to ${formatUtcTimestamp(end)} — no observations recorded`, 'No pauses are listed in this report.');
}
$('report-device').addEventListener('change', async () => {
  selectedDeviceId = $('report-device').value;
  try { await render(); }
  catch (error) { show(error.message); }
});
$('device-label-form').addEventListener('submit', async event => {
  event.preventDefault();
  if (!selectedDeviceId) return;
  try {
    await post('/api/device-label', {device_id:selectedDeviceId, label:$('device-label').value});
    show('Computer name saved encrypted on this device.');
    await render();
  } catch (error) { show(error.message); }
});
$('delete-computer').addEventListener('click', async () => {
  const selected = selectedDeviceId && document.querySelector('#report-device option:checked');
  if (!selectedDeviceId || !selected) return;
  if (!window.confirm(`Remove “${selected.textContent}” and its observations from this parent report? Earlier exported backups and data on the child computer will remain.`)) return;
  try {
    await post('/api/delete-device', {device_id:selectedDeviceId});
    selectedDeviceId = '';
    reportDeviceInitialized = false;
    show('This computer was removed from the parent report. Earlier backups and the child computer’s copy remain.');
    await refresh();
  } catch (error) { show(error.message); }
});
$('schedule-form').addEventListener('submit', async e => {
  e.preventDefault();
  const days = [...document.querySelectorAll('[name=school-day]:checked')].map(box => Number(box.value));
  try { await post('/api/schedule', {timezone:$('zone').value, days, start:$('school-start').value, end:$('school-end').value}); show('School hours saved on this device.'); if (status.has_report) await render(); }
  catch(error) { show(error.message); }
});
$('retention-form').addEventListener('submit', async e => {
  e.preventDefault();
  try {
    const result = await post('/api/retention', {retention_days:Number($('retention-days').value)});
    show(`Parent report retention is ${result.retention_days} days. Older local records were removed where needed.`);
    if (status.has_report) await render();
  } catch(error) { show(error.message); }
});
$('delete-report').addEventListener('click', async () => {
  if (!window.confirm('Delete the encrypted report stored on this device? Other copies and parent access will remain.')) return;
  try {
    await post('/api/delete-report', {});
    show('The local encrypted report was deleted. Other copies and parent access remain.');
    await refresh();
  } catch(error) { show(error.message); }
});
$('key-form').addEventListener('submit', async e => {
  e.preventDefault();
  const passphrase = $('password').value, confirm = $('confirm').value;
  if (!status.has_key && !/^[0-9]{6}$/.test(passphrase)) { show('Choose exactly six digits for your parent access PIN.'); return; }
  $('password').value=''; $('confirm').value='';
  try { await post(status.has_key ? '/api/unlock' : '/api/create', {passphrase,confirm}); show('Parent access is ready.'); await refresh(); }
  catch (error) { show(error.message); }
});
$('change-pin-form').addEventListener('submit', async event => {
  event.preventDefault();
  const currentPin = $('current-pin').value;
  const newPin = $('new-pin').value;
  const confirmPin = $('confirm-new-pin').value;
  if (!/^[0-9]{6}$/.test(newPin)) { $('change-pin-note').textContent = 'Choose exactly six digits for the new PIN.'; return; }
  if (newPin !== confirmPin) { $('change-pin-note').textContent = 'The new PINs do not match.'; return; }
  if (newPin === currentPin) { $('change-pin-note').textContent = 'Choose a different six-digit PIN.'; return; }
  $('change-pin-button').disabled = true;
  try {
    await post('/api/change-pin', {current_pin:currentPin, new_pin:newPin, confirm_pin:confirmPin});
    $('change-pin-note').textContent = 'PIN changed on this computer. Save and confirm a new recovery copy before setting up another child computer.';
    $('change-pin').open = false;
    show('Parent PIN changed. Your reports and connected child computers still use the same parent key.');
    await refresh();
  } catch (error) {
    $('change-pin-note').textContent = error.message;
  } finally {
    $('current-pin').value = '';
    $('new-pin').value = '';
    $('confirm-new-pin').value = '';
    $('change-pin-button').disabled = false;
  }
});
$('lock').addEventListener('click', async () => { try { await post('/api/lock', {}); show('Parent access locked.'); await refresh(); } catch(error) { show(error.message); } });
$('connection-code').addEventListener('input', () => {
  const input = $('connection-code');
  input.value = input.value.replace(/[^0-9]/g, '').slice(0, 2);
  $('connect').disabled = !status || !status.unlocked || input.value.length !== 2;
});
$('connect').addEventListener('click', async () => {
  const code = $('connection-code').value.trim(); $('connection-code').value=''; $('connect').disabled = true;
  if (!/^[0-9]{2}$/.test(code)) { show('Enter the two digits shown on the child computer.'); return; }
  try { show('Connecting on the local network…'); await post('/api/sync', {code}); show('Report received. Earlier observations were kept, and exact repeats were ignored.'); await refresh(); }
  catch(error) { show(error.message); }
});
$('import').addEventListener('click', async () => {
  const file = $('report-file').files[0];
  if (!file) { show('Choose an encrypted report file first.'); return; }
  try { await api('/api/import', {method:'POST',headers:{'Content-Type':'application/octet-stream'},body:file}); $('report-file').value=''; show('Report opened. Earlier observations were kept, and exact repeats were ignored.'); await refresh(); }
  catch(error) { show(error.message); }
});
(async () => {
  const token = location.hash.slice(1);
  history.replaceState(null, '', '/');
  try { if (token) await post('/api/login', {token}); await refresh(); }
  catch(error) { show(error.message); }
})();
setInterval(async () => {
  if (!status || !status.unlocked) return;
  try {
    const current = await api('/api/status');
    if (!current.unlocked) {
      show('Parent access locked after inactivity. Enter your PIN to continue.');
      await refresh();
    }
  } catch (_) { /* Leave the current screen intact if a brief status check fails. */ }
}, 30000);

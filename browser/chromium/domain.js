// Runs only in the extension. URLs never leave this function.
function domainFromTab(windowInfo, tab) {
  if (!windowInfo?.focused || windowInfo.incognito || !tab || tab.incognito || !tab.url) return null;
  try {
    const url = new URL(tab.url);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    const host = url.hostname.toLowerCase();
    const domain = /^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/;
    if (!domain.test(host) || /^\d+\.\d+\.\d+\.\d+$/.test(host)) return null;
    return host;
  } catch (_) { return null; }
}
if (typeof module !== 'undefined') module.exports = {domainFromTab};

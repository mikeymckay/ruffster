"""Small, conservative hostname-to-category hints for parent summaries.

This is a local hand-maintained list, not a content classifier. Unknown hosts
remain visible as "Other or uncategorized"; categories never imply intent.
"""
from collections import defaultdict
import math


_DOMAINS = {
    'Learning': (
        'khanacademy.org', 'coursera.org', 'edx.org', 'duolingo.com',
        'quizlet.com', 'wikipedia.org', 'britannica.com', 'ck12.org',
        'schoology.com', 'canvaslms.com', 'classroom.google.com',
    ),
    'Video': (
        'youtube.com', 'youtube-nocookie.com', 'netflix.com', 'disneyplus.com',
        'hulu.com', 'primevideo.com', 'vimeo.com', 'twitch.tv',
    ),
    'Social': (
        'facebook.com', 'instagram.com', 'tiktok.com', 'snapchat.com',
        'reddit.com', 'pinterest.com', 'x.com', 'twitter.com',
    ),
    'Games': (
        'roblox.com', 'minecraft.net', 'steampowered.com', 'epicgames.com',
        'xbox.com', 'playstation.com', 'nintendo.com', 'fortnite.com',
    ),
    'Communication': (
        'discord.com', 'discord.gg', 'whatsapp.com', 'telegram.org',
        'signal.org', 'messenger.com', 'slack.com', 'zoom.us', 'meet.google.com',
    ),
    'Search': ('google.com', 'bing.com', 'duckduckgo.com', 'search.yahoo.com'),
    'Shopping': ('amazon.com', 'ebay.com', 'etsy.com', 'walmart.com', 'shopify.com'),
    'News': ('bbc.com', 'bbc.co.uk', 'theguardian.com', 'nytimes.com', 'reuters.com'),
    'Productivity': ('docs.google.com', 'drive.google.com', 'microsoft365.com', 'office.com', 'notion.so'),
}
_LOOKUP = {domain: category for category, domains in _DOMAINS.items() for domain in domains}
OTHER = 'Other or uncategorized'


def classify(domain):
    """Return a broad hint based only on exact hostname suffix matching."""
    if not isinstance(domain, str):
        return OTHER
    hostname = domain.lower().rstrip('.')
    matches = (base for base in _LOOKUP if hostname == base or hostname.endswith('.' + base))
    base = max(matches, key=len, default=None)
    return _LOOKUP.get(base, OTHER)


def aggregate(rows):
    """Sum estimated seconds by broad category; input is (domain, seconds)."""
    totals = defaultdict(float)
    for domain, seconds in rows:
        if type(seconds) in (int, float) and math.isfinite(seconds) and seconds > 0:
            totals[classify(domain)] += seconds
    return sorted(totals.items(), key=lambda row: (-row[1], row[0]))

import unittest
from family_activity.website_categories import OTHER, aggregate, classify


class WebsiteCategoryTests(unittest.TestCase):
    def test_curated_domains_and_subdomains(self):
        self.assertEqual(classify('youtube.com'), 'Video')
        self.assertEqual(classify('m.youtube.com'), 'Video')
        self.assertEqual(classify('classroom.google.com'), 'Learning')
        self.assertEqual(classify('drive.google.com'), 'Productivity')
        self.assertEqual(classify('not-google.com'), OTHER)

    def test_unknown_hosts_remain_uncategorized_and_aggregate(self):
        self.assertEqual(classify('unlisted.example'), OTHER)
        self.assertEqual(aggregate([('youtube.com', 30), ('www.youtube.com', 15),
                                   ('unlisted.example', 10), ('facebook.com', 20)]),
                         [('Video', 45.0), ('Social', 20.0), (OTHER, 10.0)])

    def test_nonpositive_or_invalid_duration_is_not_counted(self):
        self.assertEqual(aggregate([('youtube.com', 0), ('facebook.com', -1),
                                   ('reddit.com', 'unknown'), ('twitch.tv', True),
                                   ('tiktok.com', float('inf'))]), [])


if __name__ == '__main__':
    unittest.main()

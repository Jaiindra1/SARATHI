import unittest
from services.specification_extractor import extract_highlights


class HighlightTests(unittest.TestCase):
    def test_title_measurements(self):
        self.assertEqual(extract_highlights('Phone 12GB RAM 256GB Storage 5000mAh Battery'),
                         ['12GB RAM', '256GB Storage', '5000mAh Battery'])

    def test_no_inferred_features(self):
        self.assertEqual(extract_highlights('Samsung Galaxy S25 Ultra'), [])
        self.assertEqual(extract_highlights('Headphones without 40 hours battery'), [])

    def test_generic_specs_and_duplicates(self):
        self.assertEqual(extract_highlights('Chair', specifications={'Material': 'Oak', 'features': ['Foldable', 'Foldable']}),
                         ['Material: Oak', 'Foldable'])

    def test_missing_and_limit(self):
        self.assertEqual(extract_highlights(None), [])
        self.assertEqual(len(extract_highlights('Item', specifications={'features': ['A','B','C','D','E','F']})), 5)
        self.assertEqual(extract_highlights('Item', specifications={'features': ['x' * 101]}), [])


if __name__ == '__main__':
    unittest.main()

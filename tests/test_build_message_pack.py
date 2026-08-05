import unittest

import build_message_pack


class BuildMessagePackTests(unittest.TestCase):
    def test_total_breakdown_preserves_unassigned_volume(self):
        self.assertEqual(
            build_message_pack.parse_total_breakdown(
                "8238(4790+0+3448)",
                province_count=0,
            ),
            (8238, 4790, 0, 3448),
        )

    def test_legacy_total_breakdown_derives_missing_unassigned_volume(self):
        self.assertEqual(
            build_message_pack.parse_total_breakdown(
                "8238(4790+0)",
                province_count=0,
            ),
            (8238, 4790, 0, 3448),
        )


if __name__ == "__main__":
    unittest.main()

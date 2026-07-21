from pathlib import Path
import tempfile
import unittest

import pandas as pd

import update_report_data


class UpdateReportDataTests(unittest.TestCase):
    def test_manual_english_export_headers_are_canonicalized(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "Central Waybill Query.xlsx"
            pd.DataFrame(
                {
                    "Waybill Number": ["6072126000001"],
                    "Routing Code": ["305"],
                    "Delivery Station S-Code": ["AKL"],
                    "Client Code": ["C2103960401"],
                }
            ).to_excel(source, index=False)

            frame = update_report_data.read_source_xlsx(source)

            self.assertEqual(list(frame.columns), update_report_data.REQUIRED_COLUMNS)
            self.assertEqual(frame.loc[0, "运单号"], "6072126000001")
            self.assertEqual(frame.loc[0, "派件网点简码"], "AKL")


if __name__ == "__main__":
    unittest.main()

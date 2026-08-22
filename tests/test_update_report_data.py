from pathlib import Path
from collections import Counter
import tempfile
import unittest

import pandas as pd
from openpyxl import Workbook

import update_report_data


class UpdateReportDataTests(unittest.TestCase):
    def test_blank_display_alias_does_not_count_blank_station_rows(self):
        counts = Counter({"": 3448, "AKL": 4790})

        self.assertEqual(
            update_report_data.station_count_with_display_alias(
                counts,
                "PMN",
                "",
            ),
            0,
        )

    def test_real_display_alias_is_counted_once(self):
        counts = Counter({"HMT": 10, "Hamilton": 2})

        self.assertEqual(
            update_report_data.station_count_with_display_alias(
                counts,
                "HMT",
                "Hamilton",
            ),
            12,
        )

    def test_auckland_route_counts_exclude_other_and_blank_stations(self):
        frame = pd.DataFrame(
            {
                "路由码": ["301", "301", ""],
                "派件网点简码": ["AKL", "HMT", ""],
            }
        )

        self.assertEqual(
            update_report_data.auckland_route_counts(frame),
            Counter({"301": 1}),
        )

    def test_total_breakdown_keeps_unassigned_orders_once(self):
        workbook = Workbook()
        worksheet = workbook.active

        update_report_data.write_total_breakdown(
            worksheet,
            auckland_total=4790,
            non_auckland_total=0,
            source_total=8238,
        )

        self.assertEqual(
            worksheet.cell(13, 6).value,
            "当天总量（奥克兰 + 外省 + 未分配）",
        )
        self.assertEqual(worksheet.cell(14, 6).value, "8238(4790+0+3448)")

    def test_clean_route_code_normalizes_excel_integer_decimals(self):
        self.assertEqual(update_report_data.clean_route_code("306.0"), "306")
        self.assertEqual(update_report_data.clean_route_code(" 403.00 "), "403")

    def test_clean_route_code_preserves_meaningful_decimal_or_text_codes(self):
        self.assertEqual(update_report_data.clean_route_code("201.5"), "201.5")
        self.assertEqual(update_report_data.clean_route_code("201A"), "201A")
        self.assertEqual(update_report_data.clean_route_code("501 C"), "501C")

    def test_404a_supplier_is_overridden_to_feng(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "奥克兰"
        worksheet.cell(3, 1).value = "404 A"
        worksheet.cell(3, 7).value = "PANDA"
        worksheet.cell(4, 1).value = "总计"

        update_report_data.update_auckland_sheet(
            workbook,
            Counter({"404A": 10}),
        )

        self.assertEqual(worksheet.cell(3, 7).value, "Feng")

    def test_501c_supplier_is_overridden_to_panda(self):
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "奥克兰"
        worksheet.cell(3, 1).value = "501 C"
        worksheet.cell(3, 7).value = "EMPIRE COURIER"
        worksheet.cell(4, 1).value = "总计"

        update_report_data.update_auckland_sheet(
            workbook,
            Counter({"501C": 4}),
        )

        self.assertEqual(worksheet.cell(3, 3).value, 4)
        self.assertEqual(worksheet.cell(3, 7).value, "PANDA")

    def test_3l_board_forecast_uses_200_piece_capacity(self):
        workbook = Workbook()
        worksheet = workbook.active
        arrivals = {
            "HMT": 1570,
            "TRG": 1190,
            "WLTV2": 1574,
            "NPL": 494,
            "PMN": 679,
            "TPO": 201,
            "RTR": 440,
            "WGR": 417,
            "HST": 345,
        }
        for row, (station, arrival) in enumerate(arrivals.items(), start=3):
            worksheet.cell(row, 1).value = station
            worksheet.cell(row, 3).value = arrival
        worksheet.cell(12, 1).value = "总计"
        worksheet.cell(2, 8).value = 135
        worksheet.cell(13, 8).value = 350

        update_report_data.write_board_forecast_values(worksheet)

        self.assertEqual(worksheet.cell(2, 8).value, 200)
        self.assertEqual(
            [worksheet.cell(row, 8).value for row in range(3, 11)],
            ["HMT", "TRG", "RTR", "TPO", "NPL", "HST", "PMN", "WLTV2"],
        )
        self.assertEqual(
            [worksheet.cell(row, 9).value for row in range(3, 11)],
            [7.85, 5.95, 2.2, 1.0, 2.47, 1.73, 3.4, 7.87],
        )
        self.assertEqual(worksheet.cell(11, 9).value, 32.47)
        self.assertEqual(
            [worksheet.cell(row, 8).value for row in range(14, 22)],
            ["HMT", "TRG", "RTR", "TPO", "NPL", "HST", "PMN", "WLTV2"],
        )
        self.assertEqual(worksheet.cell(22, 9).value, 18.56)

    def test_non_auckland_arrivals_follow_dispatch_distance_order(self):
        self.assertEqual(
            update_report_data.NON_AUCKLAND_STATIONS,
            ["HMT", "TRG", "RTR", "TPO", "NPL", "HST", "PMN", "WLTV2", "WGR"],
        )

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

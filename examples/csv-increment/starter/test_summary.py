import json
from pathlib import Path
import tempfile
import unittest

from csv_tool import read_rows, summary


class ExistingSummaryTests(unittest.TestCase):
    def test_public_summary_and_reader_preserve_columns_and_quoted_data(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "data.csv"
            source.write_text('id,name\n1,"甲,乙"\n2,丙\n', encoding="utf-8")
            self.assertEqual(summary(source), {"columns": ["id", "name"], "rows": 2})
            self.assertEqual(read_rows(source)[1][0], {"id": "1", "name": "甲,乙"})

    def test_empty_dataset_and_invalid_header(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "data.csv"
            source.write_text("id,name\n", encoding="utf-8")
            self.assertEqual(summary(source)["rows"], 0)
            for text in ("", "id,id\n1,2\n", "id,\n1,2\n"):
                source.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError):
                    summary(source)


if __name__ == "__main__":
    unittest.main()

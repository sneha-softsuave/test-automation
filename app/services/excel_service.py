import pandas as pd
import io
import os
from typing import List, Dict, Any, Tuple
from openpyxl import load_workbook
from datetime import datetime


class ExcelService:
    """Service for handling Excel file operations."""

    def read_excel(self, file) -> Dict[str, Any]:
        """
        Read Excel file and return data as records.

        Args:
            file: File object with .file attribute (UploadFile)

        Returns:
            Dictionary with filename, rows count, and data as records
        """
        # Determine engine based on file extension
        engine = 'openpyxl' if file.filename.endswith('.xlsx') else 'xlrd'
        # Read file content into bytes first to avoid SpooledTemporaryFile issues
        content = file.file.read()
        df = pd.read_excel(io.BytesIO(content), engine=engine)
        data = df.to_dict(orient="records")

        print(f"\n{'='*50}")
        print(f"Reading Excel file: {file.filename}")
        print(f"Total rows: {len(data)}")
        print(f"Columns: {list(df.columns)}")
        print(f"{'='*50}\n")

        return {
            "filename": file.filename,
            "rows": len(data),
            "data": data
        }

    def read_excel_from_bytes(self, content: bytes, filename: str) -> Dict[str, Any]:
        """
        Read Excel file from bytes content.

        Args:
            content: File content as bytes
            filename: Name of the file

        Returns:
            Dictionary with filename, rows count, and data as records
        """
        # Determine engine based on file extension
        engine = 'openpyxl' if filename.endswith('.xlsx') else 'xlrd'
        df = pd.read_excel(io.BytesIO(content), engine=engine)
        data = df.to_dict(orient="records")

        print(f"\n{'='*50}")
        print(f"Reading Excel file: {filename}")
        print(f"Total rows: {len(data)}")
        print(f"Columns: {list(df.columns)}")
        print(f"{'='*50}\n")

        return {
            "filename": filename,
            "rows": len(data),
            "data": data
        }

    def read_excel_with_headers(self, content: bytes, filename: str) -> Tuple[List[str], List[List[Any]]]:
        """
        Read Excel file and separate headers from data rows.

        Args:
            content: File content as bytes
            filename: Name of the file for logging

        Returns:
            Tuple of (headers, data_rows)
        """
        # Determine engine based on file extension
        engine = 'openpyxl' if filename.endswith('.xlsx') else 'xlrd'
        df = pd.read_excel(io.BytesIO(content), engine=engine)
        headers = list(df.columns)
        rows_data = df.values.tolist()

        print(f"\n{'='*50}")
        print(f"Reading Excel file: {filename}")
        print(f"Headers: {headers}")
        print(f"Total rows: {len(rows_data)}")
        print(f"{'='*50}\n")

        return headers, rows_data

    def save_custom_selector(
        self,
        file_path: str,
        test_case_id: str,
        step_number: int,
        custom_selector: str,
        captured_by: str = "user"
    ) -> bool:
        """
        Save custom selector to Excel file for future runs.

        Args:
            file_path: Path to Excel file
            test_case_id: Test case identifier
            step_number: Step number within test case
            custom_selector: The manually captured selector
            captured_by: User/session who captured it

        Returns:
            True if saved successfully
        """
        if not os.path.exists(file_path):
            print(f"Excel file not found: {file_path}")
            return False

        try:
            workbook = load_workbook(file_path)
            sheet = workbook.active

            # Get headers
            headers = [cell.value for cell in sheet[1]]

            # Check if "Custom Selector" column exists
            if "Custom Selector" not in headers:
                # Add new columns
                col_idx = len(headers) + 1
                sheet.cell(row=1, column=col_idx, value="Custom Selector")
                sheet.cell(row=1, column=col_idx + 1, value="Captured By")
                sheet.cell(row=1, column=col_idx + 2, value="Captured At")
            else:
                col_idx = headers.index("Custom Selector") + 1

            # Find the row for this test case and step
            tc_col = headers.index("T.C.No") + 1 if "T.C.No" in headers else 1

            for row_idx in range(2, sheet.max_row + 1):
                tc_no = sheet.cell(row=row_idx, column=tc_col).value
                # Match test case ID (may need fuzzy matching)
                if str(tc_no) == str(test_case_id).replace("TC_", "").replace("_", ""):
                    # Update this row
                    sheet.cell(row=row_idx, column=col_idx, value=custom_selector)
                    sheet.cell(row=row_idx, column=col_idx + 1, value=captured_by)
                    sheet.cell(row=row_idx, column=col_idx + 2, value=datetime.now().isoformat())
                    break

            workbook.save(file_path)
            workbook.close()

            print(f"Saved custom selector to Excel: {file_path}")
            return True

        except Exception as e:
            print(f"Error saving custom selector: {e}")
            return False

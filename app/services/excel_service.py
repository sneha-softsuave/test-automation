import pandas as pd
import io
from typing import List, Dict, Any, Tuple


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
        df = pd.read_excel(file.file)
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
        df = pd.read_excel(io.BytesIO(content))
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
        df = pd.read_excel(io.BytesIO(content))
        headers = list(df.columns)
        rows_data = df.values.tolist()

        print(f"\n{'='*50}")
        print(f"Reading Excel file: {filename}")
        print(f"Headers: {headers}")
        print(f"Total rows: {len(rows_data)}")
        print(f"{'='*50}\n")

        return headers, rows_data

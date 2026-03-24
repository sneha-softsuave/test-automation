"""
ExcelExportService
Converts an EnhancedTestSuite dict back to Excel (.xlsx) format
matching the exact column structure expected by the existing upload pipeline.
"""

import io
from typing import Any, Dict, List


def _steps_to_text(steps: List[Dict]) -> str:
    """
    Convert step list into numbered plain-text steps for the Excel cell.
    - goto steps → "Navigate to Application url"
    - fill steps → "Fill <field> with <Key>" (plain key name, no literal value)
    """
    lines = []
    for num, step in enumerate(steps, start=1):
        instruction = step.get("instruction", "")
        action_type = (step.get("action") or {}).get("type", "")
        td = step.get("test_data") or {}

        if action_type == "goto":
            instruction = "Navigate to Application url"

        elif action_type == "fill":
            # Replace literal values with plain key names
            for k, v in td.items():
                if v and str(v) in instruction:
                    label = {"email": "Email", "password": "Password"}.get(
                        k.lower(), k.replace("_", " ").title()
                    )
                    instruction = instruction.replace(str(v), label)

        lines.append(f"{num}. {instruction}")
    return "\n".join(lines)


def _steps_to_input_data(steps: List[Dict], test_data_global: Dict) -> str:
    """
    Collect all key-value test data from steps + global test_data
    into the 'Input data' cell format: "Key: Value\nKey: Value".
    """
    collected: Dict[str, str] = {}

    # Global credentials
    creds = test_data_global.get("default_credentials", {})
    if creds.get("email"):
        collected["Email"] = creds["email"]
    if creds.get("password"):
        collected["Password"] = creds["password"]

    # Per-step test data
    for step in steps:
        action_type = (step.get("action") or {}).get("type", "")
        td = step.get("test_data") or {}

        # Capture URL from goto steps
        if action_type == "goto" and td.get("url"):
            collected["Application url"] = str(td["url"])

        for k, v in td.items():
            if k == "url":
                pass  # already handled above
            elif k == "email":
                collected["Email"] = str(v)
            elif k == "password":
                collected["Password"] = str(v)
            elif k == "text":
                collected["Test data"] = str(v)
            else:
                collected[k.replace("_", " ").title()] = str(v)

        # Assertions → expected values
        assertions = step.get("assertions") or []
        for assertion in assertions:
            a_type = assertion.get("type", "")
            expected = assertion.get("expected_value", "")
            if not expected:
                continue
            if a_type == "url":
                collected["Expected URL"] = expected
            elif a_type in ("heading", "text"):
                collected["Expected heading"] = expected
            elif a_type == "toast":
                collected["Expected Toast Message"] = expected
            elif a_type == "status":
                collected["Expected status"] = expected
            else:
                collected[f"Expected {a_type}"] = expected

    lines = [f"{k}: {v}" for k, v in collected.items()]
    return "\n".join(lines)


def _expected_results_text(test_case: Dict) -> str:
    """Format expected results list into a single string."""
    results = test_case.get("expected_results", [])
    if not results:
        return ""
    if len(results) == 1:
        return results[0]
    return "\n".join(f"{i+1}. {r}" for i, r in enumerate(results))


def export_test_suite_to_excel(suite: Dict[str, Any]) -> bytes:
    """
    Convert an EnhancedTestSuite dict to Excel bytes.

    Output columns (matching input format):
        T.C.No | Test Case | Test Case Steps | Expected Result | Input data

    Args:
        suite: EnhancedTestSuite dict (from /generate-from-url or /parse-enhanced)

    Returns:
        Excel file as bytes (ready for HTTP response)
    """
    try:
        import pandas as pd
    except ImportError:
        raise ImportError("pandas is required for Excel export. Run: pip install pandas openpyxl")

    test_cases: List[Dict] = suite.get("test_cases", [])
    test_data_global: Dict = suite.get("test_data", {})
    base_url: str = suite.get("base_url", "")

    rows = []
    for i, tc in enumerate(test_cases, start=1):
        tc_id = tc.get("id", f"TC_{i:03d}")
        tc_name = tc.get("name", f"Test Case {i}")
        steps = tc.get("steps", [])

        # Build numeric TC number from id or index
        try:
            tc_no = int("".join(filter(str.isdigit, tc_id))) or i
        except Exception:
            tc_no = i

        steps_text = _steps_to_text(steps)
        input_data = _steps_to_input_data(steps, test_data_global)
        expected = _expected_results_text(tc)

        rows.append({
            "T.C.No": tc_no,
            "Test Case": tc_name,
            "Test Case Steps": steps_text,
            "Expected Result": expected,
            "Input data": input_data,
        })

    df = pd.DataFrame(rows, columns=["T.C.No", "Test Case", "Test Case Steps", "Expected Result", "Input data"])

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Test Cases")

        # Auto-fit column widths
        worksheet = writer.sheets["Test Cases"]
        col_widths = {"T.C.No": 8, "Test Case": 30, "Test Case Steps": 60, "Expected Result": 40, "Input data": 40}
        for col_name, width in col_widths.items():
            col_idx = df.columns.get_loc(col_name) + 1  # 1-based
            col_letter = worksheet.cell(row=1, column=col_idx).column_letter
            worksheet.column_dimensions[col_letter].width = width

        # Enable text wrapping for step and input columns
        from openpyxl.styles import Alignment
        for row in worksheet.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = Alignment(wrap_text=True, vertical="top")

    buffer.seek(0)
    return buffer.read()

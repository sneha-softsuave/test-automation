import subprocess
import sys
import json
import os
from typing import Dict, Any


class SelectorExtractor:
    """Tool for extracting selectors from web pages using Playwright."""

    def __init__(self, headless: bool = True, timeout: int = 30000):
        self.headless = headless
        self.timeout = timeout

    async def extract_selectors(self, url: str) -> Dict[str, Any]:
        """
        Extract all selectors from a given URL.
        Runs Playwright in a separate subprocess to avoid Windows asyncio issues.

        Args:
            url: The URL to extract selectors from

        Returns:
            Dictionary containing all extracted selectors and elements
        """
        print(f"\n{'='*50}")
        print(f"SELECTOR EXTRACTOR - Starting")
        print(f"URL: {url}")
        print(f"{'='*50}\n")

        # Get the path to the runner script
        script_path = os.path.join(os.path.dirname(__file__), "playwright_runner.py")

        # Run Playwright in a separate subprocess
        result = subprocess.run(
            [
                sys.executable,
                script_path,
                url,
                str(self.headless).lower(),
                str(self.timeout)
            ],
            capture_output=True,
            text=True,
            timeout=self.timeout // 1000 + 30  # Add buffer time
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            print(f"Error: {error_msg}")
            raise Exception(f"Playwright extraction failed: {error_msg}")

        # Parse JSON output
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError as e:
            print(f"Failed to parse output: {result.stdout}")
            raise Exception(f"Failed to parse Playwright output: {str(e)}")

        if "error" in data:
            raise Exception(data["error"])

        print(f"\n{'='*50}")
        print(f"Extraction completed")
        print(f"Total elements: {data['summary']['total_elements']}")
        print(f"{'='*50}\n")

        return data

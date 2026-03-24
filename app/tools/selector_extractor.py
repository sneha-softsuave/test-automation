import asyncio
import subprocess
import sys
import json
import os
from typing import Dict, Any


class SelectorExtractor:
    """Tool for extracting selectors from web pages using Playwright."""

    def __init__(self, headless: bool = True, timeout: int = 60000):
        self.headless = headless
        self.timeout = timeout

    async def extract_selectors(self, url: str, storage_state: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Extract all selectors from a given URL.
        Runs Playwright in a separate subprocess to avoid Windows asyncio issues.

        Args:
            url: The URL to extract selectors from
            storage_state: Optional Playwright storage state dict (cookies + localStorage)
                           so authenticated pages are scraped correctly.

        Returns:
            Dictionary containing all extracted selectors and elements
        """
        import tempfile

        print(f"\n{'='*50}")
        print(f"SELECTOR EXTRACTOR - Starting")
        print(f"URL: {url}")
        print(f"Authenticated: {storage_state is not None}")
        print(f"{'='*50}\n")

        # Get the path to the runner script
        script_path = os.path.join(os.path.dirname(__file__), "playwright_runner.py")

        # Write storage_state to a temp file so the subprocess can load it
        storage_state_file = None
        tmp = None
        if storage_state:
            try:
                tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False)
                json.dump(storage_state, tmp)
                tmp.flush()
                tmp.close()
                storage_state_file = tmp.name
            except Exception as e:
                print(f"[SelectorExtractor] Could not write storage_state: {e}")

        cmd = [
            sys.executable,
            script_path,
            url,
            str(self.headless).lower(),
            str(self.timeout),
        ]
        if storage_state_file:
            cmd.append(storage_state_file)

        # Run Playwright in a separate subprocess (non-blocking)
        _timeout = self.timeout // 1000 + 30  # Add buffer time
        result = await asyncio.to_thread(
            subprocess.run,
            cmd,
            capture_output=True,
            text=True,
            timeout=_timeout,
        )

        # Clean up temp file
        if storage_state_file:
            try:
                os.unlink(storage_state_file)
            except Exception:
                pass

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

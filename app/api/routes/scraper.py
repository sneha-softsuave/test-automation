import json
import os
from datetime import datetime
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, HttpUrl
from typing import Optional

from app.tools.selector_extractor import SelectorExtractor

router = APIRouter()

LOGS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "..", "logs")
LAST_SCRAPE_JSON = os.path.join(LOGS_DIR, "last_scrape.json")
LAST_SCRAPE_TXT  = os.path.join(LOGS_DIR, "last_scrape.txt")


def _save_last_scrape(data: dict) -> None:
    """Overwrite last_scrape.json and last_scrape.txt with the latest scrape result."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    with open(LAST_SCRAPE_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    with open(LAST_SCRAPE_TXT, "w", encoding="utf-8") as f:
        f.write(json.dumps(data, indent=2, ensure_ascii=False))


class UrlInput(BaseModel):
    url: str


@router.post("/extract-selectors")
async def extract_selectors(
    input_data: UrlInput,
    headless: Optional[bool] = Query(
        default=True,
        description="Run browser in headless mode"
    ),
    timeout: Optional[int] = Query(
        default=30000,
        description="Page load timeout in milliseconds"
    )
):
    """
    Extract all selectors from a given URL using Playwright.

    Returns all elements with their:
    - IDs, classes, names
    - Placeholders, roles, aria-labels
    - data-testid attributes
    - XPath and CSS selectors
    - Text content

    - **url**: The URL to extract selectors from
    - **headless**: Run browser in headless mode (default: True)
    - **timeout**: Page load timeout in ms (default: 30000)
    """
    try:
        extractor = SelectorExtractor(headless=headless, timeout=timeout)
        result = await extractor.extract_selectors(input_data.url)

        response = {
            "message": "Selectors extracted successfully",
            "url": result.get("url"),
            "title": result.get("title"),
            "summary": result.get("summary"),
            "inputs": result.get("inputs"),
            "buttons": result.get("buttons"),
            "links": result.get("links"),
            "forms": result.get("forms"),
            "headings": result.get("headings"),
            "interactive": result.get("interactive"),
            "elements_with_id": result.get("elements_with_id"),
            "elements_with_testid": result.get("elements_with_testid")
        }
        _save_last_scrape({**response, "scraped_at": datetime.utcnow().isoformat()})
        return response

    except Exception as e:
        import traceback
        error_detail = str(e) if str(e) else traceback.format_exc()
        print(f"Error: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Error extracting selectors: {error_detail}")


@router.get("/extract-selectors")
async def extract_selectors_get(
    url: str = Query(..., description="The URL to extract selectors from"),
    headless: Optional[bool] = Query(
        default=True,
        description="Run browser in headless mode"
    ),
    timeout: Optional[int] = Query(
        default=30000,
        description="Page load timeout in milliseconds"
    )
):
    """
    Extract all selectors from a given URL using Playwright (GET method).

    - **url**: The URL to extract selectors from
    - **headless**: Run browser in headless mode (default: True)
    - **timeout**: Page load timeout in ms (default: 30000)
    """
    try:
        extractor = SelectorExtractor(headless=headless, timeout=timeout)
        result = await extractor.extract_selectors(url)

        response = {
            "message": "Selectors extracted successfully",
            "url": result.get("url"),
            "title": result.get("title"),
            "summary": result.get("summary"),
            "inputs": result.get("inputs"),
            "buttons": result.get("buttons"),
            "links": result.get("links"),
            "forms": result.get("forms"),
            "headings": result.get("headings"),
            "interactive": result.get("interactive"),
            "elements_with_id": result.get("elements_with_id"),
            "elements_with_testid": result.get("elements_with_testid")
        }
        _save_last_scrape({**response, "scraped_at": datetime.utcnow().isoformat()})
        return response

    except Exception as e:
        import traceback
        error_detail = str(e) if str(e) else traceback.format_exc()
        print(f"Error: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Error extracting selectors: {error_detail}")

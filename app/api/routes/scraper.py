from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, HttpUrl
from typing import Optional

from app.tools.selector_extractor import SelectorExtractor

router = APIRouter()


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

        return {
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

        return {
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

    except Exception as e:
        import traceback
        error_detail = str(e) if str(e) else traceback.format_exc()
        print(f"Error: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Error extracting selectors: {error_detail}")

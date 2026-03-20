"""
Standalone Playwright script that runs in a separate process.
This avoids Windows asyncio event loop issues.
"""
import sys
import json
from playwright.sync_api import sync_playwright


def extract_selectors(url: str, headless: bool = True, timeout: int = 30000, storage_state_file: str = None) -> dict:
    """Extract all selectors from a given URL.

    storage_state_file: optional path to a JSON file containing Playwright
    storage state (cookies + localStorage) so authenticated pages can be
    scraped without re-logging in.
    """

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        ctx_kwargs = {}
        if storage_state_file:
            try:
                ctx_kwargs["storage_state"] = storage_state_file
            except Exception:
                pass
        context = browser.new_context(**ctx_kwargs)
        page = context.new_page()

        try:
            page.goto(url, timeout=timeout, wait_until="networkidle")
            # Give SPA frameworks extra time to render dynamic content
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass

            # JavaScript to extract all elements with their selectors
            extraction_script = """
            () => {
                const elements = [];
                const allElements = document.querySelectorAll('*');

                allElements.forEach((el, index) => {
                    if (el.tagName === 'SCRIPT' || el.tagName === 'STYLE' || el.tagName === 'NOSCRIPT') {
                        return;
                    }

                    const ARIA_INTERACTIVE_ROLES = new Set([
                        'button','checkbox','radio','switch','combobox','listbox',
                        'option','menuitem','menuitemcheckbox','menuitemradio',
                        'tab','treeitem','slider','spinbutton','textbox',
                        'searchbox','link','gridcell','columnheader','rowheader'
                    ]);
                    const elRole = el.getAttribute('role') || '';

                    // Resolve the best available label for this element
                    function resolveLabel(elem) {
                        // 1. aria-label attribute
                        const direct = elem.getAttribute('aria-label');
                        if (direct && direct.trim()) return direct.trim();

                        // 2. aria-labelledby — resolve referenced element(s) text
                        const labelledBy = elem.getAttribute('aria-labelledby');
                        if (labelledBy) {
                            const labelText = labelledBy.split(/\s+/)
                                .map(id => { const ref = document.getElementById(id); return ref ? ref.innerText.trim() : ''; })
                                .filter(Boolean).join(' ');
                            if (labelText) return labelText;
                        }

                        // 3. innerText of the element itself (non-empty)
                        const ownText = elem.innerText ? elem.innerText.trim() : '';
                        if (ownText) return ownText.substring(0, 80);

                        // 4. For ARIA widgets — look at closest sibling or parent label text
                        const parent = elem.parentElement;
                        if (parent) {
                            // Try sibling text nodes / spans next to the widget
                            for (const sibling of parent.childNodes) {
                                if (sibling === elem) continue;
                                const sibText = sibling.innerText ? sibling.innerText.trim()
                                              : (sibling.textContent ? sibling.textContent.trim() : '');
                                if (sibText && sibText.length <= 80) return sibText;
                            }
                            // Try parent's own direct text (label wrapping pattern)
                            const parentLabel = parent.getAttribute('aria-label') || '';
                            if (parentLabel.trim()) return parentLabel.trim();
                        }

                        return null;
                    }

                    const resolvedLabel = resolveLabel(el);

                    const element = {
                        index: index,
                        tag: el.tagName.toLowerCase(),
                        id: el.id || null,
                        classes: el.className ? (typeof el.className === 'string' ? el.className.split(' ').filter(c => c.trim()) : []) : [],
                        name: el.getAttribute('name') || null,
                        type: el.getAttribute('type') || null,
                        placeholder: el.getAttribute('placeholder') || null,
                        text: el.innerText ? el.innerText.substring(0, 100).trim() : null,
                        value: el.value || null,
                        href: el.getAttribute('href') || null,
                        src: el.getAttribute('src') || null,
                        role: elRole || null,
                        ariaLabel: resolvedLabel,
                        ariaChecked: el.getAttribute('aria-checked'),
                        ariaExpanded: el.getAttribute('aria-expanded'),
                        ariaSelected: el.getAttribute('aria-selected'),
                        dataTestId: el.getAttribute('data-testid') || el.getAttribute('data-test-id') || null,
                        dataId: el.getAttribute('data-id') || null,
                        isVisible: el.offsetParent !== null,
                        isInteractive: ['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName)
                                        || ARIA_INTERACTIVE_ROLES.has(elRole),
                        rect: el.getBoundingClientRect ? {
                            x: Math.round(el.getBoundingClientRect().x),
                            y: Math.round(el.getBoundingClientRect().y),
                            width: Math.round(el.getBoundingClientRect().width),
                            height: Math.round(el.getBoundingClientRect().height)
                        } : null
                    };

                    const classSelector = element.classes.length > 0 ? '.' + element.classes.join('.') : null;

                    element.selectors = {
                        byId: el.id ? '#' + el.id : null,
                        byClass: classSelector,
                        byName: el.getAttribute('name') ? '[name="' + el.getAttribute('name') + '"]' : null,
                        byPlaceholder: el.getAttribute('placeholder') ? '[placeholder="' + el.getAttribute('placeholder') + '"]' : null,
                        byRole: el.getAttribute('role') ? '[role="' + el.getAttribute('role') + '"]' : null,
                        byTestId: element.dataTestId ? '[data-testid="' + element.dataTestId + '"]' : null,
                        byText: element.text && element.text.length < 50 ? 'text=' + element.text : null,
                        xpath: getXPath(el)
                    };

                    elements.push(element);
                });

                function getXPath(element) {
                    if (element.id) {
                        return '//*[@id="' + element.id + '"]';
                    }
                    if (element === document.body) {
                        return '/html/body';
                    }

                    let ix = 0;
                    const siblings = element.parentNode ? element.parentNode.childNodes : [];
                    for (let i = 0; i < siblings.length; i++) {
                        const sibling = siblings[i];
                        if (sibling === element) {
                            const parentPath = element.parentNode ? getXPath(element.parentNode) : '';
                            return parentPath + '/' + element.tagName.toLowerCase() + '[' + (ix + 1) + ']';
                        }
                        if (sibling.nodeType === 1 && sibling.tagName === element.tagName) {
                            ix++;
                        }
                    }
                    return '';
                }

                return elements;
            }
            """

            all_elements = page.evaluate(extraction_script)
            title = page.title()

            # Categorize elements
            result = categorize_elements(all_elements)
            result["url"] = url
            result["title"] = title

            return result

        finally:
            browser.close()


ARIA_WIDGET_ROLES = {
    'switch', 'checkbox', 'radio', 'combobox', 'listbox', 'slider',
    'spinbutton', 'textbox', 'searchbox', 'menuitem', 'menuitemcheckbox',
    'menuitemradio', 'tab', 'treeitem', 'option', 'gridcell',
    'columnheader', 'rowheader',
}

# Tags that are already captured in their own dedicated lists —
# only add to aria_widgets when the tag is NOT one of these
NATIVE_INTERACTIVE_TAGS = {'input', 'button', 'a', 'select', 'textarea', 'form'}


def categorize_elements(elements: list) -> dict:
    """Categorize extracted elements."""
    inputs = []
    buttons = []
    links = []
    forms = []
    images = []
    headings = []
    interactive = []
    aria_widgets = []
    all_with_id = []
    all_with_testid = []

    for el in elements:
        if not el.get("isVisible") and not el.get("id") and not el.get("classes"):
            continue

        tag = el.get("tag", "")
        role = el.get("role") or ""
        simplified = simplify_element(el)

        if tag == "input":
            inputs.append(simplified)
        elif tag == "button" or (tag == "input" and el.get("type") in ["submit", "button"]):
            buttons.append(simplified)
        elif tag == "a":
            links.append(simplified)
        elif tag == "form":
            forms.append(simplified)
        elif tag == "img":
            images.append(simplified)
        elif tag in ["h1", "h2", "h3", "h4", "h5", "h6"]:
            headings.append(simplified)

        # ARIA widget: non-native tag with an interactive ARIA role
        if role in ARIA_WIDGET_ROLES and tag not in NATIVE_INTERACTIVE_TAGS:
            aria_widgets.append(simplified)

        if el.get("isInteractive"):
            interactive.append(simplified)
        if el.get("id"):
            all_with_id.append(simplified)
        if el.get("dataTestId"):
            all_with_testid.append(simplified)

    return {
        "summary": {
            "total_elements": len(elements),
            "inputs": len(inputs),
            "buttons": len(buttons),
            "links": len(links),
            "forms": len(forms),
            "images": len(images),
            "headings": len(headings),
            "interactive": len(interactive),
            "aria_widgets": len(aria_widgets),
            "with_id": len(all_with_id),
            "with_testid": len(all_with_testid)
        },
        "inputs": inputs,
        "buttons": buttons,
        "links": links,
        "forms": forms,
        "headings": headings,
        "interactive": interactive,
        "aria_widgets": aria_widgets,
        "elements_with_id": all_with_id,
        "elements_with_testid": all_with_testid
    }


def simplify_element(el: dict) -> dict:
    """Simplify element for output."""
    return {
        "tag": el.get("tag"),
        "id": el.get("id"),
        "classes": el.get("classes"),
        "name": el.get("name"),
        "type": el.get("type"),
        "placeholder": el.get("placeholder"),
        "text": el.get("text"),
        "role": el.get("role"),
        "ariaLabel": el.get("ariaLabel"),
        "ariaChecked": el.get("ariaChecked"),
        "ariaExpanded": el.get("ariaExpanded"),
        "ariaSelected": el.get("ariaSelected"),
        "dataTestId": el.get("dataTestId"),
        "href": el.get("href"),
        "selectors": el.get("selectors"),
        "isVisible": el.get("isVisible")
    }


if __name__ == "__main__":
    # Parse command line arguments
    if len(sys.argv) < 2:
        print(json.dumps({"error": "URL required"}))
        sys.exit(1)

    url = sys.argv[1]
    headless = sys.argv[2].lower() == "true" if len(sys.argv) > 2 else True
    timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 30000
    storage_state_file = sys.argv[4] if len(sys.argv) > 4 else None

    try:
        result = extract_selectors(url, headless, timeout, storage_state_file)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        sys.exit(1)

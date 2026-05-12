# GovNotify: Agent Guide for Source Integration & Scraping

This guide documents the evolutionary journey of building robust document scrapers for complex, modern government portals (specifically Liferay/React based sites like Income Tax India). It is designed to serve as a playbook for LLMs and AI Agents tasked with adding new sources or debugging existing ones.

## 1. The Core Philosophy: Determinism over Guesswork

When building a source integration, the instinct is often to write a traditional web scraper: load the HTML, find the `<a href="...">` tags, or extract the title and guess the URL slug (e.g., `title.replace(' ', '-') + '.pdf'`).

**Why this fails:**
*   **Dynamic UIs:** Modern portals render cards via React/JS. The `href` might not exist until a button is clicked.
*   **Inconsistent Slugs:** A title like "Notification 64/2026" might be mapped to `notification-no-64-2026-pdf`, `ennotification-64-pdf`, or `notification-64-2026-1-pdf`. Guessing slugs leads to high volumes of `404 Not Found` errors.
*   **Missing Content:** Relying purely on visual layout ("What's New" tabs) might miss items categorized differently in the backend.

**The "Real Thing" Approach:**
Find the underlying data contract. Modern websites are frontends consuming a backend API (Headless CMS, REST, GraphQL). Your goal as an agent is to find and consume that exact same API. It provides 100% deterministic mapping.

---

## 2. The Agent Playbook: Discovering Deterministic APIs

When assigned to integrate a new source or fix 404s, follow this progression:

### Phase A: Network & Behavior Tracing (The Easiest Path)
Don't just parse the initial HTML dump. Mimic user interaction to see what the site requests.
1.  **Use Playwright to click elements:** Write a script to click a "Read More" or "Print" button and intercept the resulting network requests or popup URLs.
2.  **Monitor XHR/Fetch:** Inject JS into the page to wrap `window.fetch` and `XMLHttpRequest.prototype.open` to log the exact API URLs the site uses when loading data.

### Phase B: JS Bundle Analysis (The Detective Work)
If network tracing fails (e.g., clicks just open a new tab with a generated ID), inspect the site's JavaScript.
1.  **Find the logic bundle:** Look for scripts loaded by the page (e.g., `index-[hash].js`).
2.  **Grep for clues:** Search the minified JS for:
    *   `/api/`, `v1.0/`, `headless`
    *   `fetch(`, `axios`
    *   `structureKey`, `ERC`, `categoryId`
3.  **Identify Endpoints:** In Liferay sites, look for `/o/search/v1.0/search` or `/o/headless-delivery/v1.0/`.

### Phase C: DOM & Metadata Mapping
If you find the API but don't know the parameters to send:
1.  **Look for `data-` attributes:** Inspect the HTML wrapper around the items (e.g., `<div data-fileentryid="1234">` or `<custom-element structureid="36050">`).
2.  **Find Category/Taxonomy IDs:** Government sites heavily use category tagging. Use the CMS's taxonomy API (e.g., `/o/headless-admin-taxonomy/...`) to list all vocabularies and categories. Find the numeric ID for "Notifications" or "Circulars".

---

## 3. Dealing with Anti-Bot Protections (403 / 503 Errors)

Government portals often use WAFs (Web Application Firewalls) or bot-protection that block standard `httpx` or `requests` calls, returning `403 Forbidden` or `503 Service Unavailable` (Maintenance pages).

**Escalation Strategies:**
1.  **High-Quality Headers:** Always mimic a real browser perfectly.
    ```python
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:124.0) Gecko/20100101 Firefox/124.0",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.5",
        "Origin": "https://www.example.gov.in",
        "Referer": "https://www.example.gov.in/page"
    }
    ```
2.  **HTTP Method Swapping:** Sometimes `POST` requests to search APIs are heavily guarded, but `GET` requests to direct REST endpoints are open.
3.  **Browser Context Execution (The Ultimate Bypass):** If standard HTTP clients fail, use `playwright` or `crawl4ai` to load the actual webpage, establish a valid session (cookies/tokens), and execute the `fetch()` call *from within the page's console via JS*.

---

## 4. Case Study: The Income Tax Portal Migration

**The Initial Struggle:**
The legacy scraper relied on parsing titles and generating predictable URL slugs. This resulted in numerous `404` errors because Liferay's internal slug generator would inconsistently append `en-` or `-1` to filenames. Furthermore, items categorized as "Orders" were missing from the "Notifications" visual tab.

**The Investigation Process:**
1.  **Failed Network Tracing:** Tried intercepting clicks via Playwright. The buttons didn't have `href`s; they executed JS that was hard to intercept cleanly due to timeouts.
2.  **JS Bundle Breakthrough:** Downloaded the main React bundle (`index.js`). Grepped for `api/` and `ERC` (External Reference Code). Discovered `CIRCULAR_BP_ERC` and `NOTIFICATION_BP_ERC`.
3.  **API Probing:** Called the Liferay Search API `/o/search/v1.0/search` with the discovered blueprints. It returned clean JSON, but the `NOTIFICATION_BP_ERC` returned irrelevant Tax Calendar data.
4.  **Taxonomy Discovery:** Realized the site filtered by internal Category IDs, not just blueprints. Called the Taxonomy API to map names to IDs:
    *   Notifications = `37788`
    *   Circulars = `37776`
    *   Others = `37791`
5.  **Data Extraction:** Called the Structured Contents API `GET /o/headless-delivery/v1.0/sites/{siteId}/structured-contents?filter=taxonomyCategoryIds/any(t:t eq {id})`.
    *   This returned the exact JSON metadata.
    *   The definitive PDF URL was securely nestled in the `reportFile.document.contentUrl` field.

**The Final Result:**
We replaced hundreds of lines of brittle regex and HTML parsing with a concise, OData-filtered API call that is 100% deterministic and guarantees no 404s. By fetching multiple Category IDs, we also ensured 100% coverage of edge cases (like Orders miscategorized as "Others").

---

## 5. Standard Operating Procedure for Future Sources

1. **Never guess a URL.** If a URL isn't explicitly provided in an `href` or an API response, you haven't found the root data source yet.
2. **Prioritize APIs over HTML.** Always check network tabs, JS bundles, and common Headless CMS paths (Liferay, Drupal, WordPress JSON API) before writing BeautifulSoup logic.
3. **Use the built-in deduplication.** Once you have deterministic metadata, pass the `title` and `url` to the base class methods. Rely on `content_hash` and `is_duplicate_callback` to save bandwidth and OCR costs.
4. **Assume Anti-Bot.** Start with high-quality headers immediately. If blocked, fallback to Playwright JS evaluation.
5. **Verify Edge Cases.** Always test the final logic against a known complex item (e.g., an item with a weird title or an old item with no PDF attached) to ensure fallbacks (like reading `documentContent` HTML) work.

---

## 6. Best Practices for Adding a New Source

Follow these steps to ensure a high-quality, maintainable integration:

### 1. Research the Data Source
*   **Check for APIs first**: Use browser DevTools (Network tab) to see if the site loads data via JSON/XHR.
*   **Check for RSS/Atom**: Many government sites have hidden or legacy RSS feeds which are the most reliable.
*   **Identify dynamic content**: If the site requires JavaScript execution (React, Angular, Vue), use `crawl4ai` or `playwright`.

### 2. Implementation Standards
*   **Inherit from `WebScrapeSource`**: Always extend the base class to get rate-limiting and standard headers for free.
*   **Use `self._get()`**: Never use bare `httpx` or `requests`. Use the rate-limited helper.
*   **Deterministic URL Mapping**: As discovered in the Income Tax portal case, look for IDs or metadata that provide direct document links rather than parsing titles.
*   **Robust Date Parsing**: Use `govnotify.sources.utils.parse_indian_date` for consistent handling of various formats (DD-MM-YYYY, DD-MMM-YYYY, etc.).

### 3. Optimization & Deduplication
*   **Title-based Pre-fetch Check**: Always pass the `title` and `url` to `_fetch_pdf_content` or `_fetch_html_content`. This prevents unnecessary downloads/OCR of existing documents.
*   **Date Filtering**: If the source provides a date, compare it against the `since` parameter and skip items older than the threshold.
*   **Graceful Fallbacks**: If PDF extraction fails, fallback to HTML extraction or the document description so the user at least gets a summary.

### 4. Testing & Validation
*   **Edge Case Verification**: Test with documents that have special characters in titles, no PDF attachments, or very large file sizes.
*   **Anti-Bot Verification**: Ensure the source works in the production Docker environment, where network paths might differ from local dev.
*   **Memory Efficiency**: Don't load massive amounts of data into memory at once. Use generators (`yield`) where possible.

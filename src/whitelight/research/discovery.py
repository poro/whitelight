"""Discover trading strategies from TradingView and Reddit."""

from __future__ import annotations

import logging
import re
import time
from typing import Optional
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

from whitelight.research.database import StrategyDB

logger = logging.getLogger(__name__)

SCRAPER_API_KEY = "6ee7d4d212143dfc8511dbcadd47af68"
SCRAPER_API_BASE = "http://api.scraperapi.com"


def _scraper_get(url: str, timeout: int = 60) -> str:
    """Fetch a URL through ScraperAPI for anti-bot bypass."""
    api_url = f"{SCRAPER_API_BASE}?api_key={SCRAPER_API_KEY}&url={quote_plus(url)}"
    resp = httpx.get(api_url, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# TradingView Discovery
# ---------------------------------------------------------------------------

TV_SCRIPT_BASE = "https://www.tradingview.com"

# Category slugs on TradingView /scripts/ page
TV_CATEGORIES = {
    "trend-following": "trend-following",
    "momentum": "momentum",
    "mean-reversion": "mean-reversion",
    "volatility": "volatility",
    "moving-average": "moving-averages",
    "oscillators": "oscillators",
    "all": "",
}


def discover_tradingview(
    db: StrategyDB,
    category: str = "trend-following",
    limit: int = 20,
    sort: str = "popular",
) -> list[dict]:
    """Scrape TradingView /scripts/ for public strategies.

    Returns list of discovered strategy metadata dicts.
    """
    cat_slug = TV_CATEGORIES.get(category, category)
    
    # Build URL — TradingView scripts page with filters
    # Type: strategies (not indicators)
    if cat_slug:
        url = f"{TV_SCRIPT_BASE}/scripts/{cat_slug}/?script_type=strategies"
    else:
        url = f"{TV_SCRIPT_BASE}/scripts/?script_type=strategies"
    
    logger.info("Scraping TradingView: %s (limit=%d)", url, limit)
    
    discovered = []
    page = 1
    
    while len(discovered) < limit:
        page_url = f"{url}&page={page}" if page > 1 else url
        
        try:
            html = _scraper_get(page_url)
        except Exception as e:
            logger.error("Failed to scrape TV page %d: %s", page, e)
            break
        
        soup = BeautifulSoup(html, "lxml")
        
        # TradingView script cards — they use various class patterns
        # Look for script links in the content
        script_links = soup.select('a[href*="/script/"]')
        
        if not script_links:
            # Try alternative selectors
            script_links = soup.find_all("a", href=re.compile(r"/script/[A-Za-z0-9]"))
        
        if not script_links:
            logger.warning("No script links found on page %d — may need selector update", page)
            # Try to find any links that look like scripts
            all_links = soup.find_all("a", href=True)
            script_links = [a for a in all_links if "/script/" in a.get("href", "")]
        
        if not script_links:
            logger.info("No more scripts found, stopping at page %d", page)
            break
        
        seen_urls = set()
        for link in script_links:
            if len(discovered) >= limit:
                break
            
            href = link.get("href", "")
            if not href.startswith("/script/"):
                continue
            
            full_url = f"{TV_SCRIPT_BASE}{href}"
            if full_url in seen_urls:
                continue
            seen_urls.add(full_url)
            
            # Skip if already in DB
            if db.strategy_exists(full_url):
                continue
            
            # Extract what we can from the listing
            title = link.get_text(strip=True) or href.split("/")[-1]
            
            # Look for author/description in parent elements
            parent = link.find_parent("div")
            author = ""
            description = ""
            if parent:
                author_el = parent.select_one('a[href*="/u/"]') or parent.select_one('.tv-feed-item__author')
                if author_el:
                    author = author_el.get_text(strip=True)
                desc_el = parent.select_one('.tv-feed-item__description') or parent.select_one('p')
                if desc_el:
                    description = desc_el.get_text(strip=True)[:500]
            
            strategy_id = db.add_strategy(
                source="tradingview",
                name=title,
                author=author,
                description=description,
                category=category,
                source_url=full_url,
            )
            
            discovered.append({
                "id": strategy_id,
                "name": title,
                "author": author,
                "url": full_url,
                "category": category,
            })
            logger.info("Discovered: %s by %s", title, author)
        
        page += 1
        time.sleep(2)  # Be nice to ScraperAPI rate limits
    
    logger.info("Discovered %d strategies from TradingView (%s)", len(discovered), category)
    return discovered


def extract_pine_script(db: StrategyDB, strategy_id: int, url: str) -> Optional[str]:
    """Fetch a TradingView script page and extract the Pine Script source code."""
    try:
        html = _scraper_get(url)
    except Exception as e:
        logger.error("Failed to fetch script page %s: %s", url, e)
        db.update_status(strategy_id, "failed", str(e))
        return None
    
    soup = BeautifulSoup(html, "lxml")
    
    # Pine Script source is usually in a <pre> or code block
    # TradingView uses various selectors
    pine_code = None
    
    # Method 1: Look for Pine Script in pre/code tags
    for tag in soup.find_all(["pre", "code"]):
        text = tag.get_text()
        if _looks_like_pine_script(text):
            pine_code = text
            break
    
    # Method 2: Look for script content in specific divs
    if not pine_code:
        for div in soup.select('.tv-chart-view__script-wrap, .pine-editor-view, [class*="script"], [class*="pine"]'):
            text = div.get_text()
            if _looks_like_pine_script(text):
                pine_code = text
                break
    
    # Method 3: Search all text for Pine Script patterns
    if not pine_code:
        page_text = soup.get_text()
        # Look for //@version= marker
        match = re.search(
            r'(//@version=\d[\s\S]*?)(?:\n\n\n|\Z)',
            page_text,
        )
        if match:
            pine_code = match.group(1).strip()
    
    if pine_code:
        db.update_pine_script(strategy_id, pine_code)
        logger.info("Extracted Pine Script for strategy #%d (%d chars)", strategy_id, len(pine_code))
        return pine_code
    else:
        db.update_status(strategy_id, "failed", "Could not extract Pine Script — may be protected/invite-only")
        logger.warning("Could not extract Pine Script from %s", url)
        return None


def _looks_like_pine_script(text: str) -> bool:
    """Heuristic check if text looks like Pine Script."""
    if len(text) < 50:
        return False
    pine_markers = [
        "//@version=", "strategy(", "indicator(",
        "ta.sma", "ta.ema", "ta.rsi", "ta.macd",
        "strategy.entry", "strategy.close", "strategy.exit",
        "input.int", "input.float", "input.bool",
        "plot(", "plotshape(", "bgcolor(",
    ]
    matches = sum(1 for m in pine_markers if m in text)
    return matches >= 2


# ---------------------------------------------------------------------------
# Reddit Discovery
# ---------------------------------------------------------------------------


def discover_reddit(
    db: StrategyDB,
    subreddits: list[str] | None = None,
    limit: int = 20,
    client_id: str = "",
    client_secret: str = "",
) -> list[dict]:
    """Search Reddit for trading strategy posts with code.

    Note: Requires PRAW credentials. If not provided, uses ScraperAPI fallback.
    """
    if not subreddits:
        subreddits = ["algotrading", "quant"]
    
    discovered = []
    
    # Use ScraperAPI to scrape Reddit search results
    for sub in subreddits:
        search_queries = [
            "pine script strategy backtest",
            "trading strategy python code",
            "TQQQ strategy backtest results",
            "momentum strategy code",
            "mean reversion strategy",
        ]
        
        for query in search_queries:
            if len(discovered) >= limit:
                break
            
            url = f"https://old.reddit.com/r/{sub}/search?q={quote_plus(query)}&restrict_sr=on&sort=top&t=year"
            
            try:
                html = _scraper_get(url)
            except Exception as e:
                logger.error("Failed to scrape Reddit %s: %s", sub, e)
                continue
            
            soup = BeautifulSoup(html, "lxml")
            
            # Find post links
            for post in soup.select('a.title[href*="/comments/"]'):
                if len(discovered) >= limit:
                    break
                
                href = post.get("href", "")
                if not href.startswith("http"):
                    href = f"https://old.reddit.com{href}"
                
                if db.strategy_exists(href):
                    continue
                
                title = post.get_text(strip=True)
                
                # Only include posts that look strategy-related
                strategy_keywords = ["strategy", "backtest", "pine", "algorithm", "systematic", 
                                   "signal", "indicator", "trading system", "entry", "exit"]
                if not any(kw in title.lower() for kw in strategy_keywords):
                    continue
                
                strategy_id = db.add_strategy(
                    source="reddit",
                    name=title,
                    category=f"r/{sub}",
                    source_url=href,
                )
                
                discovered.append({
                    "id": strategy_id,
                    "name": title,
                    "url": href,
                    "category": f"r/{sub}",
                })
                logger.info("Discovered (Reddit): %s", title)
            
            time.sleep(2)
    
    logger.info("Discovered %d strategies from Reddit", len(discovered))
    return discovered


def extract_reddit_code(db: StrategyDB, strategy_id: int, url: str) -> Optional[str]:
    """Fetch a Reddit post and extract any code blocks."""
    try:
        html = _scraper_get(url)
    except Exception as e:
        logger.error("Failed to fetch Reddit post %s: %s", url, e)
        db.update_status(strategy_id, "failed", str(e))
        return None
    
    soup = BeautifulSoup(html, "lxml")
    
    # Find code blocks in the post
    code_blocks = []
    for pre in soup.find_all("pre"):
        code = pre.get_text()
        if len(code) > 100:  # Skip tiny snippets
            code_blocks.append(code)
    
    if not code_blocks:
        for code_tag in soup.find_all("code"):
            code = code_tag.get_text()
            if len(code) > 100:
                code_blocks.append(code)
    
    if code_blocks:
        # Take the longest code block (most likely the strategy)
        best_code = max(code_blocks, key=len)
        
        if _looks_like_pine_script(best_code):
            db.update_pine_script(strategy_id, best_code)
            return best_code
        elif "import" in best_code or "def " in best_code:
            # Already Python
            db.update_python_code(strategy_id, best_code)
            return best_code
    
    db.update_status(strategy_id, "failed", "No code blocks found in post")
    return None

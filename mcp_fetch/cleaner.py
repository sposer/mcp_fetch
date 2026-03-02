from bs4 import BeautifulSoup, Comment, Tag
import re
import logging

_log = logging.getLogger(__name__)

def clean_html(html: str) -> str:
    """
    Clean HTML content by removing irrelevant elements like scripts, styles, ads, navigation, etc.
    """
    if not html:
        return ""

    try:
        soup = BeautifulSoup(html, "html.parser")

        # 1. Remove standard irrelevant tags
        for tag_name in ["script", "style", "noscript", "iframe", "svg", "header", "footer", "nav", "aside", "form", "object", "embed", "applet"]:
            for tag in soup.find_all(tag_name):
                tag.decompose()

        # 2. Remove comments
        for element in soup(string=lambda text: isinstance(text, Comment)):
            element.extract()

        # 3. Heuristic removal based on class/id names
        # Patterns that are almost always irrelevant, even if they contain "post" or "content"
        # Added: hot, trending, login, sign, auth, global, appheader, columnpageheader
        force_remove_patterns = re.compile(r"sidebar|ads|advert|banner|cookie|popup|modal|share|social|recommend|promo|subscription|newsletter|toast|floating|sticky|hot|trending|login|sign|auth|global|appheader|columnpageheader|cornerbuttons|topstory|related|internal-ad|external-ad", re.I)

        # Patterns that might be irrelevant (like header/footer), but we should be careful if they also match keep_patterns
        potential_irrelevant_patterns = re.compile(r"copyright|footer|header|menu|nav|comment|button|action|widget|module|control|tool|card", re.I)
        
        # Patterns for content we want to keep even if they match potential_irrelevant_patterns
        keep_patterns = re.compile(r"main|article|content|body|post|entry|text|story|rich", re.I)

        # Use reversed() to process children before parents, avoiding issues where decomposing a parent
        # makes its children invalid (AttributeError: 'NoneType' object has no attribute 'get')
        for tag in reversed(soup.find_all(["div", "section", "aside", "ul", "ol", "li", "span", "a", "button"])):
            if not isinstance(tag, Tag):
                continue
            
            # 0. Check href for specific unwanted links (topics, ads)
            if tag.name == 'a':
                href = tag.get('href', '')
                if href and (re.search(r'click\.aliyun\.com|/topic/|/people/|/search\?', href) or 
                             re.search(r'login|signin|register', href, re.I)):
                     tag.decompose()
                     continue

            # Check ID & Class
            id_val = tag.get("id", "")
            if isinstance(id_val, list): id_val = " ".join(id_val)
            
            class_val = tag.get("class", [])
            if isinstance(class_val, list): class_val = " ".join(class_val)
            
            check_str = f"{id_val} {class_val}"
            
            # 1. Force remove check
            if force_remove_patterns.search(check_str):
                # Double check for "Topstory" which might contain the main feed content in some contexts
                # But for article pages, Topstory usually refers to the sidebar recommendation list or header
                # We should be careful with "Topstory" if it's the main container
                if "Topstory" in check_str and ("Main" in check_str or "Content" in check_str):
                     pass # Might be main content
                else:
                    tag.decompose()
                    continue

            # 2. Potential irrelevant check
            if potential_irrelevant_patterns.search(check_str):
                # If it looks like main content, keep it
                if keep_patterns.search(check_str):
                    continue
                tag.decompose()
                continue
            
            # 3. Text content check (for stubborn elements without clear classes)
            # Remove specific text patterns like "Login to view", "Open in App", etc.
            text_content = tag.get_text(strip=True)
            if len(text_content) < 50: # Only check short texts to avoid false positives in main content
                if re.search(r"登录.*查看|Open in App|下载.*APP|Hot Search|热搜|相关推荐|想来.*工作", text_content, re.I):
                     tag.decompose()
                     continue

        # 4. Remove empty tags (optional, but good for cleanup)
        # Iterate in reverse to handle nested empty tags
        # (This is tricky with bs4 in one pass, let's skip for now to avoid over-aggressive removal)

        return str(soup)

    except Exception as e:
        _log.error(f"Error cleaning HTML: {e}")
        return html  # Fallback to original HTML

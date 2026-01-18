import asyncio

from playwright.async_api import async_playwright


async def main():
    print("Starting Playwright...")
    async with async_playwright() as p:
        print("Playwright started.")
        print("Launching browser...")
        browser = await p.chromium.launch(headless=True)
        print("Browser launched.")
        page = await browser.new_page()
        print("Page created. Navigating...")
        await page.goto("http://example.com", timeout=10000)
        print("Navigated. Getting content...")
        title = await page.title()
        print(f"Title: {title}")
        await browser.close()
        print("Browser closed.")


if __name__ == "__main__":
    asyncio.run(main())

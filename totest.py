from playwright.sync_api import sync_playwright

url = "https://www.instagram.com/p/Dbi-k58lx-H/"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # Set to True to run in background
    page = browser.new_page()
    page.goto(url)
    
    # Wait for content to load
    page.wait_for_timeout(5000)
    
    # Save the fully rendered HTML
    html_content = page.content()
    with open(r"C:\Users\user\Downloads\python-output.html", "w", encoding="utf-8") as f:
        f.write(html_content)
        
    browser.close()
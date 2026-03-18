# Website Test Scripts

A collection of lightweight, no-dependency Python testing scripts designed to audit and generate beautiful HTML reports for any website.

## Scripts Included

### 1. Dead Link Checker (`check_dead_links.py`)
A fast web crawler that traverses all internal pages to find and validate outgoing links (both underlying URLs and image sources). 
- Generates a dark-themed HTML report grouping broken links by the page they are found on.
- Highlights HTTP error codes directly in the report.
- Configure domains to ignore (like third-party pages that block bots) at the top of the file using the `IGNORE_URLS` list.
- Safety limits to prevent infinite crawling.

### 2. Social Preview Scraper (`scrape_social_previews.py`)
Crawls all pages and extracts crucial metadata intended for social media platforms (WhatsApp, Slack, iMessage, Twitter, LinkedIn).
- Extracts `<title>`, `<meta description>`, Open Graph (`og:tags`), and Twitter card metadata.
- Generates an HTML report table showcasing exactly how links will preview in chat applications with simulated preview chips.
- Uses `lynx` for rapid initial URL discovery. 

## Requirements
- Python 3.6+
- (Optional but recommended) `lynx` installed in your system for the social preview scraper to run at maximum speed.

## Quickstart

1. Open the `config.json` file in your editor.
2. Edit the `start_url` and any other configurations to point to your target website, and set any URLs you wish to ignore:
   ```json
   {
     "start_url": "https://example.com/",
     "dead_link_checker": {
       "ignore_urls": ["blog.example.com"]
     }
   }
   ```
3. Run the desired script:
   ```bash
   python3 check_dead_links.py
   # or
   python3 scrape_social_previews.py
   ```
4. A richly formatted HTML report (e.g., `dead_links_report.html`) will be generated in the same directory!

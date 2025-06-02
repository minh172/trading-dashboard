from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import threading
import time
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
import pytz
import logging
import re
import requests
import xml.etree.ElementTree as ET

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Cho phép CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

vn_tz = pytz.timezone("Asia/Ho_Chi_Minh")
news_data = []
btmc_gold_data = []
exchange_data = []

# Hàm cào giá vàng BTMC
def fetch_btmc_gold():
    global btmc_gold_data
    try:
        logger.info("Đang lấy dữ liệu giá vàng từ BTMC...")
        response = requests.get("https://btmc.vn/")
        soup = BeautifulSoup(response.text, "html.parser")
        gold_prices = []
        rows = soup.find_all("tr", style=lambda x: x and "background-color: #FEEEB3" in x)
        for row in rows:
            cols = row.find_all("td")
            if len(cols) >= 5:
                product_img = cols[0].find("img")["src"] if cols[0].find("img") else ""
                product_name = cols[1].get_text(strip=True)
                purity = cols[2].get_text(strip=True)
                buy_price = cols[3].get_text(strip=True)
                sell_price = cols[4].get_text(strip=True)
                gold_prices.append({
                    "product_name": product_name,
                    "purity": purity,
                    "buy_price": buy_price,
                    "sell_price": sell_price,
                    "product_img": f"https://btmc.vn{product_img}" if product_img.startswith("/") else product_img
                })
        if gold_prices:
            btmc_gold_data = gold_prices
            logger.info(f"✅ Đã lấy {len(gold_prices)} mục giá vàng từ BTMC.")
        else:
            logger.warning("Không tìm thấy dữ liệu giá vàng từ BTMC.")
    except Exception as e:
        logger.error(f"🚨 Lỗi khi lấy giá vàng từ BTMC: {e}")

def schedule_fetch_btmc(interval_seconds=600):
    def run():
        while True:
            fetch_btmc_gold()
            time.sleep(interval_seconds)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()

schedule_fetch_btmc()

@app.get("/btmc-gold")
def get_btmc_gold():
    return {
        "timestamp": datetime.now(vn_tz).isoformat(),
        "data": btmc_gold_data
    }

# Hàm cào tỷ giá từ API XML Vietcombank
def fetch_exchange_rates():
    global exchange_data
    try:
        logger.info("Đang lấy dữ liệu tỷ giá từ API XML Vietcombank...")
        response = requests.get("https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx?b=10")
        response.encoding = 'utf-8'
        root = ET.fromstring(response.text)
        rates = []
        allowed_currencies = ["USD", "EUR", "GBP", "JPY"]  # Chỉ lấy các đồng này

        for item in root.findall('Exrate'):
            currency_code = item.get('CurrencyCode')
            if currency_code.upper() not in allowed_currencies:
                continue  # Bỏ qua đồng không nằm trong danh sách

            currency_name = item.get('CurrencyName')
            buy_price = item.get('Buy')
            transfer_price = item.get('Transfer')
            sell_price = item.get('Sell')
            rates.append({
                "currency_code": currency_code,
                "currency_name": currency_name,
                "buy_price": buy_price,
                "transfer_price": transfer_price,
                "sell_price": sell_price
            })

        if rates:
            exchange_data = rates
            logger.info(f"✅ Đã lấy {len(rates)} mục tỷ giá từ API XML Vietcombank.")
        else:
            logger.warning("Không tìm thấy dữ liệu tỷ giá từ API XML Vietcombank.")
    except Exception as e:
        logger.error(f"🚨 Lỗi khi lấy tỷ giá từ API XML Vietcombank: {e}")


def schedule_fetch_exchange(interval_seconds=3600):
    def run():
        while True:
            fetch_exchange_rates()
            time.sleep(interval_seconds)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()

schedule_fetch_exchange()

@app.get("/exchange-rates")
def get_exchange_rates():
    return {
        "timestamp": datetime.now(vn_tz).isoformat(),
        "data": exchange_data
    }

# Hàm cào tin tức Investing
def fetch_investing_news():
    global news_data
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({'User-Agent': 'Mozilla/5.0'})
            logger.info("Đang lấy tin tức từ Investing...")
            page.goto("https://vn.investing.com/news/economy", timeout=60000)
            page.wait_for_selector('article', timeout=20000)
            soup = BeautifulSoup(page.content(), 'html.parser')
            browser.close()
            now = datetime.now(vn_tz)
            articles = soup.find_all('article', class_=lambda x: x and 'news-analysis-v2_article_w0pT' in x)
            if not articles:
                articles = soup.find_all('article')
            existing_links = set(item["link"] for item in news_data)
            new_items = []
            for article in articles:
                try:
                    title_elem = article.find('a', class_=lambda x: x and 'text-inv-blue-500' in x)
                    if not title_elem:
                        continue
                    title = title_elem.text.strip()
                    href = title_elem.get('href') or "#"
                    href = re.sub(r'^https?://vn\.investing\.com', '', href).lstrip('/')
                    link = f"https://vn.investing.com/{href}"
                    if link in existing_links:
                        break
                    time_elem = article.find('time') or article.find('span', class_='date')
                    raw_time = time_elem.text.strip() if time_elem else None
                    if raw_time:
                        if "giờ trước" in raw_time:
                            published_dt = now - timedelta(hours=int(re.search(r"(\d+)", raw_time).group(1)))
                        elif "phút trước" in raw_time:
                            published_dt = now - timedelta(minutes=int(re.search(r"(\d+)", raw_time).group(1)))
                        elif "ngày trước" in raw_time:
                            published_dt = now - timedelta(days=int(re.search(r"(\d+)", raw_time).group(1)))
                        else:
                            try:
                                published_dt = datetime.strptime(raw_time, "%d/%m/%Y %H:%M")
                                published_dt = vn_tz.localize(published_dt)
                            except:
                                published_dt = now
                    else:
                        published_dt = now
                    published_str = published_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
                    summary_elem = article.find('p', {'data-test': 'article-description'})
                    summary = summary_elem.text.strip() if summary_elem else ""
                    news_item = {
                        "title": title,
                        "summary": summary,
                        "link": link,
                        "source": "Investing.com",
                        "published_time": published_str
                    }
                    new_items.append(news_item)
                    logger.info(f"🆕 {title}")
                except Exception as e:
                    logger.warning(f"Lỗi phân tích bài viết: {e}")
                    continue
            if new_items:
                news_data = new_items + news_data
                logger.info(f"✅ Đã thêm {len(new_items)} bài mới.")
            else:
                logger.info("📭 Không có bài viết mới.")
    except Exception as e:
        logger.error(f"🚨 Lỗi khi lấy tin tức: {e}")

def schedule_fetch(interval_seconds=60):
    def run():
        while True:
            fetch_investing_news()
            time.sleep(interval_seconds)
    thread = threading.Thread(target=run, daemon=True)
    thread.start()

schedule_fetch()

@app.get("/news")
def get_news(page: int = Query(1, ge=1)):
    per_page = 10
    start = (page - 1) * per_page
    end = start + per_page
    total = len(news_data)
    paginated = news_data[start:end]
    return {
        "timestamp": datetime.now(vn_tz).isoformat(),
        "page": page,
        "per_page": per_page,
        "total": total,
        "total_pages": (total + per_page - 1) // per_page,
        "latest_news": paginated
    }

@app.get("/refresh")
def refresh_news():
    fetch_investing_news()
    return {"message": "✅ Tin tức đã được làm mới"}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)

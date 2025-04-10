import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from googleapiclient.discovery import build
import pandas as pd
import time
import sqlite3
import schedule
import requests
from bs4 import BeautifulSoup
from youtube_transcript_api import YouTubeTranscriptApi
from pytube import YouTube
import re
import os
from datetime import datetime
import whisper
import logging
import MetaTrader5 as mt5
import numpy as np
import concurrent.futures
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
import threading
import pyperclip
from urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

# تنظیم لاگ‌گیری
logging.basicConfig(filename='N:/python/crawler.log', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# YouTube API Key
youtube_api_key = "AIzaSyDICrTqdB6zJOhutD8KED20TpUwziLK618"
youtube_channel_id = "UC2-JF8X_LDFEtSa3Ohfwvpg"

# مسیر برای ذخیره ویدیوها
VIDEO_DOWNLOAD_PATH = "N:/python/videos"
if not os.path.exists(VIDEO_DOWNLOAD_PATH):
    os.makedirs(VIDEO_DOWNLOAD_PATH)

# مسیر برای ذخیره فایل‌های CSV بایگانی و ارتباط با MT5
MT5_FILES_PATH = "C:/Users/ArturShah/AppData/Roaming/MetaQuotes/Terminal/D0E8209F77C8CF37AD8BF550E51FF075/MQL5/Files"
ARCHIVE_PATH = "N:/python/archive"
if not os.path.exists(ARCHIVE_PATH):
    os.makedirs(ARCHIVE_PATH)
if not os.path.exists(MT5_FILES_PATH):
    os.makedirs(MT5_FILES_PATH)

# تابع برای ایجاد اتصال دیتابیس جدید برای هر نخ
def get_db_connection():
    conn = sqlite3.connect("N:/python/brooks_data.db")
    cursor = conn.cursor()
    return conn, cursor

# ایجاد دیتابیس و جداول (فقط یک بار در نخ اصلی)
def initialize_database():
    conn, cursor = get_db_connection()
    
    cursor.execute('''CREATE TABLE IF NOT EXISTS youtube_videos (
        video_id TEXT PRIMARY KEY,
        title TEXT,
        description TEXT,
        published_at TEXT,
        view_count INTEGER,
        like_count INTEGER,
        comment_count INTEGER,
        duration TEXT,
        transcript TEXT,
        file_path TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS market_data_5min (
        date TEXT,
        symbol TEXT,
        open REAL,
        high REAL,
        low REAL,
        close REAL,
        volume INTEGER
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS price_action_tips (
        video_id TEXT,
        tip TEXT,
        pattern TEXT,
        description TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS trades (
        trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
        symbol TEXT,
        entry_time TEXT,
        entry_price REAL,
        exit_time TEXT,
        exit_price REAL,
        position_type TEXT,
        profit_loss REAL,
        pattern TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS crawler_reports (
        datetime TEXT,
        new_videos INTEGER,
        pending_videos INTEGER,
        market_candles INTEGER,
        patterns_found INTEGER,
        signals_generated INTEGER
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS last_update (
        id INTEGER PRIMARY KEY,
        last_updated TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS pending_downloads (
        video_id TEXT PRIMARY KEY,
        title TEXT,
        video_url TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS activities (
        datetime TEXT,
        activity TEXT
    )''')

    cursor.execute('''CREATE TABLE IF NOT EXISTS errors (
        datetime TEXT,
        error_message TEXT
    )''')

    # جدول برای ذخیره مقالات آموزشی از سایت‌ها
    cursor.execute('''CREATE TABLE IF NOT EXISTS educational_articles (
        source TEXT,
        title TEXT,
        content TEXT,
        url TEXT,
        published_at TEXT
    )''')

    # جدول برای ذخیره اخبار
    cursor.execute('''CREATE TABLE IF NOT EXISTS financial_news (
        source TEXT,
        title TEXT,
        content TEXT,
        url TEXT,
        published_at TEXT
    )''')

    # جدول برای ذخیره تحلیل‌ها
    cursor.execute('''CREATE TABLE IF NOT EXISTS market_analysis (
        source TEXT,
        title TEXT,
        content TEXT,
        url TEXT,
        published_at TEXT
    )''')
    
    conn.commit()
    conn.close()

# اجرای اولیه برای ایجاد جداول
initialize_database()

# تنظیم Session با Retry برای مدیریت خطاهای HTTP
session = requests.Session()
retries = Retry(total=3, backoff_factor=1, status_forcelist=[400, 403, 429, 500, 502, 503, 504])
session.mount('http://', HTTPAdapter(max_retries=retries))
session.mount('https://', HTTPAdapter(max_retries=retries))

# تابع برای گرفتن اخبار از Investing.com (جایگزین Forex Factory)
def fetch_economic_events(gui):
    gui.log_activity("Fetching economic events from Investing.com...")
    events = []
    
    try:
        url = "https://www.investing.com/economic-calendar/"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        important_events = ["Non-Farm Payrolls", "Inflation Rate", "Interest Rate"]
        for event in soup.find_all('tr', class_='js-event-item'):
            event_time = event.find('td', class_='time').text.strip()
            event_name = event.find('td', class_='event').text.strip()
            importance = event.find('td', class_='sentiment').get('data-img_key', '')
            
            if 'high' in importance.lower() and any(imp_event in event_name for imp_event in important_events):
                event_date = datetime.now().strftime('%Y-%m-%d')
                event_datetime = f"{event_date} {event_time}:00"
                events.append((event_datetime, event_name))
    except Exception as e:
        error_msg = f"Error fetching events from Investing.com: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        gui.log_activity("Skipping Investing.com due to error, moving to next step...")
    
    gui.log_activity(f"Economic events fetched: {len(events)} important events found")
    return events

# تابع برای جمع‌آوری مقالات آموزشی از Investopedia
def fetch_investopedia_articles(gui, topic="price action"):
    gui.log_activity(f"Fetching educational articles from Investopedia on topic: {topic}...")
    articles = []
    
    try:
        url = f"https://www.investopedia.com/search?q={topic.replace(' ', '+')}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for article in soup.find_all('div', class_='card__content'):
            title_elem = article.find('a', class_='card__title')
            if not title_elem:
                continue
            title = title_elem.text.strip()
            article_url = title_elem['href']
            if not article_url.startswith('http'):
                article_url = f"https://www.investopedia.com{article_url}"
            
            # گرفتن محتوای مقاله
            article_response = session.get(article_url, headers=headers, timeout=30)
            article_response.raise_for_status()
            article_soup = BeautifulSoup(article_response.text, 'html.parser')
            content_elem = article_soup.find('div', class_='article-content')
            content = content_elem.text.strip() if content_elem else "No content found"
            
            published_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            articles.append(("Investopedia", title, content, article_url, published_at))
            
            if len(articles) >= 5:  # محدود کردن به 5 مقاله
                break
    
    except Exception as e:
        error_msg = f"Error fetching articles from Investopedia: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return []
    
    if articles:
        conn, cursor = get_db_connection()
        cursor.executemany("INSERT INTO educational_articles (source, title, content, url, published_at) VALUES (?, ?, ?, ?, ?)", articles)
        conn.commit()
        conn.close()
    gui.log_activity(f"Fetched {len(articles)} articles from Investopedia")
    return articles

# تابع برای جمع‌آوری اخبار از Investing.com
def fetch_investing_news(gui):
    gui.log_activity("Fetching financial news from Investing.com...")
    news_items = []
    
    try:
        url = "https://www.investing.com/news/forex-news"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for article in soup.find_all('article', class_='articleItem'):
            title_elem = article.find('a', class_='title')
            if not title_elem:
                continue
            title = title_elem.text.strip()
            article_url = title_elem['href']
            if not article_url.startswith('http'):
                article_url = f"https://www.investing.com{article_url}"
            
            # گرفتن محتوای خبر
            article_response = session.get(article_url, headers=headers, timeout=30)
            article_response.raise_for_status()
            article_soup = BeautifulSoup(article_response.text, 'html.parser')
            content_elem = article_soup.find('div', class_='WYSIWYG articlePage')
            content = content_elem.text.strip() if content_elem else "No content found"
            
            published_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            news_items.append(("Investing.com", title, content, article_url, published_at))
            
            if len(news_items) >= 5:  # محدود کردن به 5 خبر
                break
    
    except Exception as e:
        error_msg = f"Error fetching news from Investing.com: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return []
    
    if news_items:
        conn, cursor = get_db_connection()
        cursor.executemany("INSERT INTO financial_news (source, title, content, url, published_at) VALUES (?, ?, ?, ?, ?)", news_items)
        conn.commit()
        conn.close()
    gui.log_activity(f"Fetched {len(news_items)} news items from Investing.com")
    return news_items

# تابع برای جمع‌آوری تحلیل‌ها از FX Street
def fetch_fxstreet_analysis(gui):
    gui.log_activity("Fetching market analysis from FX Street...")
    analyses = []
    
    try:
        url = "https://www.fxstreet.com/analysis"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for article in soup.find_all('div', class_='fxs_article'):
            title_elem = article.find('a', class_='fxs_article_title')
            if not title_elem:
                continue
            title = title_elem.text.strip()
            article_url = title_elem['href']
            
            # گرفتن محتوای تحلیل
            article_response = session.get(article_url, headers=headers, timeout=30)
            article_response.raise_for_status()
            article_soup = BeautifulSoup(article_response.text, 'html.parser')
            content_elem = article_soup.find('div', class_='fxs_article_content')
            content = content_elem.text.strip() if content_elem else "No content found"
            
            published_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            analyses.append(("FX Street", title, content, article_url, published_at))
            
            if len(analyses) >= 5:  # محدود کردن به 5 تحلیل
                break
    
    except Exception as e:
        error_msg = f"Error fetching analysis from FX Street: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return []
    
    if analyses:
        conn, cursor = get_db_connection()
        cursor.executemany("INSERT INTO market_analysis (source, title, content, url, published_at) VALUES (?, ?, ?, ?, ?)", analyses)
        conn.commit()
        conn.close()
    gui.log_activity(f"Fetched {len(analyses)} analyses from FX Street")
    return analyses

# تابع برای جمع‌آوری مطالب آموزشی از Baby Pips
def fetch_babypips_education(gui):
    gui.log_activity("Fetching educational content from Baby Pips...")
    articles = []
    
    try:
        url = "https://www.babypips.com/learn/forex"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = session.get(url, headers=headers, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        
        for article in soup.find_all('div', class_='course-lesson'):
            title_elem = article.find('a')
            if not title_elem:
                continue
            title = title_elem.text.strip()
            article_url = title_elem['href']
            
            # گرفتن محتوای مقاله
            article_response = session.get(article_url, headers=headers, timeout=30)
            article_response.raise_for_status()
            article_soup = BeautifulSoup(article_response.text, 'html.parser')
            content_elem = article_soup.find('div', class_='content-body')
            content = content_elem.text.strip() if content_elem else "No content found"
            
            published_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            articles.append(("Baby Pips", title, content, article_url, published_at))
            
            if len(articles) >= 5:  # محدود کردن به 5 مقاله
                break
    
    except Exception as e:
        error_msg = f"Error fetching education from Baby Pips: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return []
    
    if articles:
        conn, cursor = get_db_connection()
        cursor.executemany("INSERT INTO educational_articles (source, title, content, url, published_at) VALUES (?, ?, ?, ?, ?)", articles)
        conn.commit()
        conn.close()
    gui.log_activity(f"Fetched {len(articles)} articles from Baby Pips")
    return articles

# تابع برای جمع‌آوری داده‌های بازار از متاتریدر ۵
def crawl_market_data(symbol="XAUUSD", gui=None):
    if gui:
        gui.log_activity("Connecting to MetaTrader 5 to fetch market data...")
    retries = 3
    for attempt in range(retries):
        try:
            if not mt5.initialize():
                raise Exception("Failed to connect to MetaTrader 5")
            
            if gui:
                gui.log_activity(f"Fetching 5-minute data for {symbol}...")
            rates = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 1000)
            if rates is None or len(rates) == 0:
                raise Exception(f"Failed to get market data for {symbol}")
            
            market_data = [(datetime.fromtimestamp(rate['time']).strftime('%Y-%m-%d %H:%M:%S'), symbol, 
                            rate['open'], rate['high'], rate['low'], rate['close'], int(rate['tick_volume'])) 
                           for rate in rates]
            conn, cursor = get_db_connection()
            cursor.executemany("INSERT OR IGNORE INTO market_data_5min (date, symbol, open, high, low, close, volume) VALUES (?, ?, ?, ?, ?, ?, ?)", market_data)
            conn.commit()
            conn.close()
            
            mt5.shutdown()
            if gui:
                gui.log_activity(f"Market data collected: {len(market_data)} candles")
            return len(market_data)
        except Exception as e:
            if gui:
                error_msg = f"Error on attempt {attempt+1}/{retries}: {str(e)}"
                gui.log_activity(error_msg)
                conn, cursor = get_db_connection()
                cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                               (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
                conn.commit()
                conn.close()
                gui.show_errors()
                gui.notify_error(error_msg)
            if attempt == retries - 1:
                if gui:
                    gui.log_activity(f"Failed to fetch market data after {retries} attempts")
                    conn, cursor = get_db_connection()
                    cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                                   (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), f"Failed to fetch market data for {symbol}: {str(e)}"))
                    conn.commit()
                    conn.close()
                    gui.show_errors()
                logging.error(f"Failed to fetch market data for {symbol}: {str(e)}")
                return 0
            time.sleep(5)

# تابع برای تحلیل پرایس اکشن (سبک ال بروکس) و یادگیری الگوهای جدید
def analyze_price_action(symbol="XAUUSD", gui=None):
    if gui:
        gui.log_activity(f"Analyzing price action for {symbol}...")
    try:
        conn, cursor = get_db_connection()
        cursor.execute("SELECT * FROM market_data_5min WHERE symbol=? ORDER BY date DESC LIMIT 1000", (symbol,))
        data = cursor.fetchall()
        df = pd.DataFrame(data, columns=['date', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
        
        if gui:
            gui.log_activity("Fetching price action tips from database...")
        cursor.execute("SELECT * FROM price_action_tips")
        tips = cursor.fetchall()
        
        patterns = []
        for i in range(len(df) - 5):
            if df['high'][i] > df['high'][i+1] and df['high'][i+1] > df['high'][i+2] and df['low'][i] < df['low'][i+1] and df['low'][i+1] < df['low'][i+2]:
                patterns.append((df['date'][i], symbol, "Parabolic Wedge", "Potential reversal pattern detected"))
            
            if i > 2 and df['close'][i] > df['close'][i+1] and df['close'][i+1] > df['close'][i+2] and df['close'][i+2] > df['close'][i+3]:
                if df['close'][i] < df['close'][i-1] and df['close'][i-1] < df['close'][i-2]:
                    patterns.append((df['date'][i], symbol, "Bull Flag", "Bullish continuation pattern"))
            
            if i > 4 and abs(df['high'][i] - df['high'][i+2]) < 0.01 * df['high'][i] and df['low'][i+1] < df['low'][i] and df['low'][i+1] < df['low'][i+2]:
                patterns.append((df['date'][i], symbol, "Double Top", "Bearish reversal pattern"))
            
            if i > 2 and df['close'][i] > df['open'][i] and df['close'][i-1] < df['open'][i-1] and df['close'][i-2] > df['open'][i-2]:
                patterns.append((df['date'][i], symbol, "High 1", "Bullish entry after pullback"))
            
            if i > 4 and df['close'][i] > df['open'][i] and df['close'][i-1] < df['open'][i-1] and df['close'][i-2] > df['open'][i-2] and df['close'][i-3] < df['open'][i-3] and df['close'][i-4] > df['open'][i-4]:
                patterns.append((df['date'][i], symbol, "High 2", "Strong bullish entry after double pullback"))
            
            if i > 1 and (df['high'][i] - df['close'][i]) > 2 * (df['close'][i] - df['low'][i]) and df['close'][i] < df['open'][i]:
                patterns.append((df['date'][i], symbol, "Bearish Reversal Bar", "Potential bearish reversal"))
            
            if i > 1 and abs(df['close'][i] - df['open'][i]) > 2 * (df['high'][i] - df['close'][i]) and df['close'][i] > df['open'][i]:
                patterns.append((df['date'][i], symbol, "Trend Bar", "Strong bullish trend bar"))
        
        for tip in tips:
            pattern = tip[2]
            if "bull" in pattern.lower() and df['close'][i] > df['open'][i]:
                patterns.append((df['date'][i], symbol, pattern, tip[3]))
        
        cursor.execute("INSERT INTO analysis (date, symbol, pattern, description) VALUES (?, ?, ?, ?)", patterns)
        conn.commit()
        conn.close()
        if gui:
            gui.log_activity(f"Price action analysis completed: {len(patterns)} patterns found")
        return patterns
    except Exception as e:
        error_msg = f"Error in analyzing price action: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return []

# تابع برای محاسبه استاپ‌لاس و تیک‌پرافیت (مدیریت ریسک)
def calculate_risk_reward(df, i, position_type, gui):
    try:
        if position_type == "buy":
            entry_price = df['close'][i]
            stop_loss = min(df['low'][i-1], df['low'][i-2])
            risk = entry_price - stop_loss
            take_profit = entry_price + 2 * risk
        else:  # sell
            entry_price = df['close'][i]
            stop_loss = max(df['high'][i-1], df['high'][i-2])
            risk = stop_loss - entry_price
            take_profit = entry_price - 2 * risk
        return stop_loss, take_profit
    except Exception as e:
        error_msg = f"Error in calculating risk-reward: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return 0, 0

# تابع برای گرفتن آخرین زمان به‌روزرسانی
def get_last_update(gui):
    try:
        conn, cursor = get_db_connection()
        cursor.execute("SELECT last_updated FROM last_update WHERE id=1")
        result = cursor.fetchone()
        conn.close()
        if result:
            return result[0]
        return "1970-01-01T00:00:00Z"
    except Exception as e:
        error_msg = f"Error in getting last update: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return "1970-01-01T00:00:00Z"

# تابع برای به‌روزرسانی زمان آخرین اجرا
def update_last_update(gui):
    try:
        current_time = datetime.utcnow().isoformat() + "Z"
        conn, cursor = get_db_connection()
        cursor.execute("INSERT OR REPLACE INTO last_update (id, last_updated) VALUES (1, ?)", (current_time,))
        conn.commit()
        conn.close()
    except Exception as e:
        error_msg = f"Error in updating last update: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)

# تابع برای ذخیره داده‌ها در فایل CSV
def archive_data(gui):
    try:
        conn, cursor = get_db_connection()
        cursor.execute("SELECT * FROM youtube_videos")
        youtube_data = cursor.fetchall()
        youtube_df = pd.DataFrame(youtube_data, columns=['video_id', 'title', 'description', 'published_at', 
                                                         'view_count', 'like_count', 'comment_count', 'duration', 
                                                         'transcript', 'file_path'])
        youtube_df.to_csv(os.path.join(ARCHIVE_PATH, 'youtube_videos_archive.csv'), index=False)
        
        cursor.execute("SELECT * FROM market_data_5min")
        market_data = cursor.fetchall()
        market_df = pd.DataFrame(market_data, columns=['date', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
        market_df.to_csv(os.path.join(ARCHIVE_PATH, 'market_data_5min_archive.csv'), index=False)
        
        cursor.execute("SELECT * FROM price_action_tips")
        tips_data = cursor.fetchall()
        tips_df = pd.DataFrame(tips_data, columns=['video_id', 'tip', 'pattern', 'description'])
        tips_df.to_csv(os.path.join(ARCHIVE_PATH, 'price_action_tips_archive.csv'), index=False)
        
        cursor.execute("SELECT * FROM trades")
        trades_data = cursor.fetchall()
        trades_df = pd.DataFrame(trades_data, columns=['trade_id', 'symbol', 'entry_time', 'entry_price', 
                                                       'exit_time', 'exit_price', 'position_type', 'profit_loss', 'pattern'])
        trades_df.to_csv(os.path.join(ARCHIVE_PATH, 'trades_archive.csv'), index=False)
        
        cursor.execute("SELECT * FROM educational_articles")
        articles_data = cursor.fetchall()
        articles_df = pd.DataFrame(articles_data, columns=['source', 'title', 'content', 'url', 'published_at'])
        articles_df.to_csv(os.path.join(ARCHIVE_PATH, 'educational_articles_archive.csv'), index=False)
        
        cursor.execute("SELECT * FROM financial_news")
        news_data = cursor.fetchall()
        news_df = pd.DataFrame(news_data, columns=['source', 'title', 'content', 'url', 'published_at'])
        news_df.to_csv(os.path.join(ARCHIVE_PATH, 'financial_news_archive.csv'), index=False)
        
        cursor.execute("SELECT * FROM market_analysis")
        analysis_data = cursor.fetchall()
        analysis_df = pd.DataFrame(analysis_data, columns=['source', 'title', 'content', 'url', 'published_at'])
        analysis_df.to_csv(os.path.join(ARCHIVE_PATH, 'market_analysis_archive.csv'), index=False)
        
        conn.close()
        logging.info("Data archived to CSV files")
    except Exception as e:
        error_msg = f"Error in archiving data: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)

# تابع برای چک کردن زمان شلوغی (با ساعت سیستم)
def is_busy_time(gui):
    try:
        current_time = datetime.now().strftime("%H:%M")
        start_time = "01:30"
        end_time = "10:30"
        return not (start_time <= current_time <= end_time)
    except Exception as e:
        error_msg = f"Error in checking busy time: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return False

# تابع برای جمع‌آوری داده‌های یوتیوب (فقط ویدیوهای مرتبط با ترید)
def crawl_youtube(gui):
    global youtube
    try:
        youtube = build('youtube', 'v3', developerKey=youtube_api_key)
        videos = []
        
        gui.log_activity("Fetching YouTube channel info...")
        last_update = get_last_update(gui)
        request = youtube.channels().list(part="contentDetails", id=youtube_channel_id)
        response = request.execute()
        playlist_id = response['items'][0]['contentDetails']['relatedPlaylists']['uploads']
        
        request = youtube.playlistItems().list(part="snippet", playlistId=playlist_id, maxResults=50)
        while request:
            gui.log_activity("Fetching video list...")
            response = request.execute()
            video_ids = [item['snippet']['resourceId']['videoId'] for item in response['items']]
            
            gui.log_activity("Fetching detailed video info...")
            video_request = youtube.videos().list(part="snippet,statistics,contentDetails", id=",".join(video_ids))
            video_response = video_request.execute()
            
            file_paths = []
            for item in video_response['items']:
                published_at = item['snippet']['publishedAt']
                if published_at <= last_update:
                    gui.log_activity(f"Video {item['id']} is old, skipped")
                    continue
                
                title = item['snippet']['title'].lower()
                description = item['snippet']['description'].lower()
                trading_keywords = ["price action", "trading", "forex", "bull flag", "bear flag", "double top", "double bottom", "high 1", "high 2"]
                if not any(keyword in title or keyword in description for keyword in trading_keywords):
                    gui.log_activity(f"Video {item['id']} is not related to trading, skipped")
                    continue
                
                video_info, tips = process_video(item, gui)
                if video_info and tips:
                    videos.append(video_info)
                    conn, cursor = get_db_connection()
                    cursor.executemany("INSERT INTO price_action_tips (video_id, tip, pattern, description) VALUES (?, ?, ?, ?)", tips)
                    conn.commit()
                    conn.close()
                    if video_info[9]:
                        file_paths.append((video_info[9], item['id'], item['snippet']['title']))
            
            if file_paths:
                gui.log_activity("Converting speech to text in parallel (3 tasks at a time)...")
                with concurrent.futures.ProcessPoolExecutor(max_workers=3) as executor:
                    futures = {executor.submit(speech_to_text, fp[0], gui): fp for fp in file_paths}
                    for future in concurrent.futures.as_completed(futures):
                        video_id = futures[future][1]
                        title = futures[future][2]
                        try:
                            transcript = future.result()
                            conn, cursor = get_db_connection()
                            cursor.execute("UPDATE youtube_videos SET transcript=? WHERE video_id=?", (transcript, video_id))
                            conn.commit()
                            conn.close()
                            gui.log_activity(f"Speech to text conversion completed for {title} (ID: {video_id})")
                        except Exception as e:
                            error_msg = f"Error converting speech to text for {title} (ID: {video_id}): {str(e)}"
                            gui.log_activity(error_msg)
                            conn, cursor = get_db_connection()
                            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
                            conn.commit()
                            conn.close()
                            gui.show_errors()
                            gui.notify_error(error_msg)
            
            request = youtube.playlistItems().list_next(request, response)
            time.sleep(1)
        
        if videos:
            conn, cursor = get_db_connection()
            cursor.executemany("INSERT INTO youtube_videos VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", videos)
            conn.commit()
            conn.close()
        gui.log_activity(f"Video collection completed: {len(videos)} new videos")
        return len(videos)
    except Exception as e:
        error_msg = f"Error in crawling YouTube: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return 0

# تابع برای پردازش ویدیو (دانلود و تبدیل)
def process_video(item, gui):
    video_id = item['id']
    try:
        conn, cursor = get_db_connection()
        cursor.execute("SELECT video_id FROM youtube_videos WHERE video_id=?", (video_id,))
        if cursor.fetchone():
            gui.log_activity(f"Video {video_id} already processed, skipped")
            conn.close()
            return None, None
        
        transcript = get_transcript(video_id, gui)
        file_path = ""
        if not transcript:
            file_path = download_video(video_id, item['snippet']['title'], gui)
            if file_path:
                transcript = speech_to_text(file_path, gui)
            else:
                conn.close()
                return None, None
        
        video_info = (
            video_id,
            item['snippet']['title'],
            item['snippet']['description'],
            item['snippet']['publishedAt'],
            int(item['statistics'].get('viewCount', 0)),
            int(item['statistics'].get('likeCount', 0)),
            int(item['statistics'].get('commentCount', 0)),
            item['contentDetails']['duration'],
            transcript,
            file_path
        )
        tips = extract_price_action_tips(video_id, transcript, gui)
        conn.close()
        return video_info, tips
    except Exception as e:
        error_msg = f"Error in processing video {video_id}: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return None, None

# تابع برای گرفتن زیرنویس
def get_transcript(video_id, gui):
    try:
        gui.log_activity(f"Fetching transcript for video {video_id}...")
        transcript = YouTubeTranscriptApi.get_transcript(video_id, languages=['en'], proxies=None)  # حذف timeout
        gui.log_activity(f"Transcript fetched for video {video_id}")
        return " ".join([entry['text'] for entry in transcript])
    except Exception as e:
        error_msg = f"Error fetching transcript for video {video_id}: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return ""

# تابع برای استخراج نکته‌های پرایس اکشن (سبک ال بروکس)
def extract_price_action_tips(video_id, transcript, gui):
    try:
        gui.log_activity(f"Extracting price action tips from video {video_id}...")
        tips = []
        patterns = {
            "bull trend": "Bullish trend detected",
            "bear trend": "Bearish trend detected",
            "parabolic wedge": "Potential reversal pattern",
            "bull channel": "Bullish channel detected",
            "bear channel": "Bearish channel detected",
            "bull flag": "Bullish flag pattern",
            "bear flag": "Bearish flag pattern",
            "double top": "Double top reversal pattern",
            "double bottom": "Double bottom reversal pattern",
            "high 1": "High 1 entry pattern",
            "high 2": "High 2 entry pattern",
            "low 1": "Low 1 entry pattern",
            "low 2": "Low 2 entry pattern",
            "stop entry": "Stop entry strategy",
            "limit order": "Limit order strategy",
            "failed breakout": "Failed breakout detected",
            "reversal bar": "Reversal bar detected",
            "trend bar": "Trend bar detected",
            "doji bar": "Doji bar detected",
            "breakout pullback": "Breakout pullback detected",
            "micro channel": "Micro channel detected"
        }
        
        for pattern, description in patterns.items():
            if re.search(pattern, transcript, re.IGNORECASE):
                tips.append((video_id, pattern, description, transcript))
        
        gui.log_activity(f"Tip extraction completed for video {video_id}: {len(tips)} tips found")
        return tips
    except Exception as e:
        error_msg = f"Error extracting price action tips for video {video_id}: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return []

# تابع برای دانلود ویدیو با محدودیت حجم (ترتیبی)
def download_video(video_id, title, gui):
    try:
        gui.log_activity(f"Downloading video {video_id}...")
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        yt = YouTube(video_url, use_oauth=False, allow_oauth_cache=False)
        stream = yt.streams.filter(progressive=True, file_extension='mp4').order_by('resolution').desc().first()
        if not stream:
            gui.log_activity(f"Error: No suitable stream found for video {video_id}")
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), f"No suitable stream found for video {video_id}"))
            conn.commit()
            conn.close()
            gui.show_errors()
            gui.notify_error(f"No suitable stream found for video {video_id}")
            return ""
        
        file_size_mb = stream.filesize / (1024 * 1024)
        if is_busy_time(gui) and file_size_mb > 20:
            conn, cursor = get_db_connection()
            cursor.execute("INSERT OR IGNORE INTO pending_downloads (video_id, title, video_url) VALUES (?, ?, ?)", 
                           (video_id, title, video_url))
            conn.commit()
            conn.close()
            gui.log_activity(f"Video {video_id} (size: {file_size_mb:.2f} MB) added to pending downloads for non-busy hours")
            logging.warning(f"Video {video_id} (size: {file_size_mb:.2f} MB) added to pending downloads for non-busy hours")
            return ""
        
        safe_title = "".join(c if c.isalnum() or c in (' ', '_') else '_' for c in title)
        file_path = os.path.join(VIDEO_DOWNLOAD_PATH, f"{safe_title}_{video_id}.mp4")
        if not os.path.exists(file_path):
            gui.log_activity(f"Downloading video {video_id} (size: {file_size_mb:.2f} MB)...")
            stream.download(output_path=VIDEO_DOWNLOAD_PATH, filename=f"{safe_title}_{video_id}.mp4")
            gui.log_activity(f"Video {video_id} downloaded: {file_path}")
            gui.add_downloaded_file(file_path)
        return file_path
    except Exception as e:
        error_msg = f"Error downloading video {video_id}: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return ""

# تابع برای تبدیل گفتار به متن با Whisper
def speech_to_text(file_path, gui):
    try:
        if not file_path:
            return ""
        gui.log_activity(f"Converting speech to text for {file_path}...")
        result = whisper_model.transcribe(file_path)
        gui.log_activity(f"Speech to text conversion completed for {file_path}")
        logging.info(f"Processed video file: {file_path}")
        return result["text"]
    except Exception as e:
        error_msg = f"Error converting speech to text for {file_path}: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return ""

# تابع برای بک‌تست استراتژی‌ها
def backtest_strategy(patterns, gui):
    try:
        gui.log_activity("Starting backtesting of trading strategies...")
        conn, cursor = get_db_connection()
        cursor.execute("SELECT * FROM market_data_5min WHERE symbol='XAUUSD' ORDER BY date DESC LIMIT 1000")
        df = pd.DataFrame(cursor.fetchall(), columns=['date', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
        conn.close()
        
        trades = []
        for i in range(len(df)):
            for pattern in patterns:
                if pattern[0] != df['date'][i]:
                    continue
                pattern_name = pattern[2]
                if "bull" in pattern_name.lower() or "high 1" in pattern_name.lower() or "high 2" in pattern_name.lower():
                    position_type = "buy"
                    stop_loss, take_profit = calculate_risk_reward(df, i, position_type, gui)
                    entry_price = df['close'][i]
                    for j in range(i+1, len(df)):
                        if df['low'][j] <= stop_loss:
                            exit_price = stop_loss
                            profit_loss = (exit_price - entry_price) * 1000
                            trades.append((df['date'][i], df['date'][j], entry_price, exit_price, profit_loss, position_type, pattern_name))
                            break
                        elif df['high'][j] >= take_profit:
                            exit_price = take_profit
                            profit_loss = (exit_price - entry_price) * 1000
                            trades.append((df['date'][i], df['date'][j], entry_price, exit_price, profit_loss, position_type, pattern_name))
                            break
                elif "bear" in pattern_name.lower() or "double top" in pattern_name.lower():
                    position_type = "sell"
                    stop_loss, take_profit = calculate_risk_reward(df, i, position_type, gui)
                    entry_price = df['close'][i]
                    for j in range(i+1, len(df)):
                        if df['high'][j] >= stop_loss:
                            exit_price = stop_loss
                            profit_loss = (entry_price - exit_price) * 1000
                            trades.append((df['date'][i], df['date'][j], entry_price, exit_price, profit_loss, position_type, pattern_name))
                            break
                        elif df['low'][j] <= take_profit:
                            exit_price = take_profit
                            profit_loss = (entry_price - exit_price) * 1000
                            trades.append((df['date'][i], df['date'][j], entry_price, exit_price, profit_loss, position_type, pattern_name))
                            break
        
        conn, cursor = get_db_connection()
        cursor.executemany("INSERT INTO trades (symbol, entry_time, entry_price, exit_time, exit_price, profit_loss, position_type, pattern) VALUES ('XAUUSD', ?, ?, ?, ?, ?, ?, ?)", 
                           [(t[0], t[2], t[1], t[3], t[4], t[5], t[6]) for t in trades])
        conn.commit()
        conn.close()
        
        total_profit_loss = sum(t[4] for t in trades)
        successful_trades = sum(1 for t in trades if t[4] > 0)
        success_rate = (successful_trades / len(trades) * 100) if len(trades) > 0 else 0
        gui.log_activity(f"Backtesting completed: Total Profit/Loss: {total_profit_loss:.2f}, Success Rate: {success_rate:.2f}%")
        return trades
    except Exception as e:
        error_msg = f"Error in backtesting strategy: {str(e)}"
        gui.log_activity(error_msg)
        conn, cursor = get_db_connection()
        cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                       (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
        conn.commit()
        conn.close()
        gui.show_errors()
        gui.notify_error(error_msg)
        return []
                   (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), new_videos, pending_count, market_count, patterns_found, signals_generated))
            conn.commit()
            conn.close()
        except Exception as e:
            error_msg = f"Error in updating stats: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def update_trades(self):
        try:
            conn, cursor = get_db_connection()
            cursor.execute("SELECT * FROM trades WHERE exit_time IS NULL")
            open_trades = cursor.fetchall()
            self.trades_text.delete(1.0, tk.END)
            for trade in open_trades:
                self.trades_text.insert(tk.END, f"Trade ID: {trade[0]}, Symbol: {trade[1]}, Entry Time: {trade[2]}, Entry Price: {trade[3]}, Type: {trade[6]}, Pattern: {trade[8]}\n")
            conn.close()
        except Exception as e:
            error_msg = f"Error in updating trades: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def update_trade_reports(self):
        try:
            conn, cursor = get_db_connection()
            cursor.execute("SELECT * FROM trades WHERE exit_time IS NOT NULL")
            closed_trades = cursor.fetchall()
            cursor.execute("SELECT SUM(profit_loss) FROM trades WHERE exit_time IS NOT NULL")
            total_profit_loss = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM trades WHERE exit_time IS NOT NULL AND profit_loss > 0")
            successful_trades = cursor.fetchone()[0]
            success_rate = (successful_trades / len(closed_trades) * 100) if len(closed_trades) > 0 else 0
            
            self.trade_reports_text.delete(1.0, tk.END)
            self.trade_reports_text.insert(tk.END, f"Closed Trades: {len(closed_trades)}\nTotal Profit/Loss: {total_profit_loss:.2f}\nSuccess Rate: {success_rate:.2f}%\n\n")
            for trade in closed_trades:
                self.trade_reports_text.insert(tk.END, f"Trade ID: {trade[0]}, Symbol: {trade[1]}, Entry Time: {trade[2]}, Exit Time: {trade[4]}, Profit/Loss: {trade[7]}\n")
            conn.close()
        except Exception as e:
            error_msg = f"Error in updating trade reports: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def update_news(self, events):
        try:
            self.news_text.delete(1.0, tk.END)
            for event in events:
                self.news_text.insert(tk.END, f"Time: {event[0]}, Event: {event[1]}\n")
        except Exception as e:
            error_msg = f"Error in updating news: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def set_alert(self):
        try:
            alert_time = self.alert_time_entry.get()
            datetime.strptime(alert_time, '%H:%M:%S')
            self.alert_time = alert_time
            self.alert_status_label.config(text=f"Alert set for {alert_time}")
            self.check_alert()
        except ValueError:
            error_msg = "Error: Alert time format must be HH:MM:SS"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def check_alert(self):
        try:
            if self.alert_time:
                current_time = datetime.now().strftime('%H:%M:%S')
                if current_time == self.alert_time:
                    self.alert_status_label.config(text="Alert triggered!")
                    self.alert_time = None
                self.root.after(1000, self.check_alert)
        except Exception as e:
            error_msg = f"Error in checking alert: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def show_chart(self):
        try:
            conn, cursor = get_db_connection()
            cursor.execute("SELECT pattern, COUNT(*) as count FROM analysis GROUP BY pattern")
            data = cursor.fetchall()
            patterns = [row[0] for row in data]
            counts = [row[1] for row in data]
            conn.close()
            
            fig, ax = plt.subplots(figsize=(8, 4))
            ax.bar(patterns, counts, color='#2196F3')
            ax.set_title("Number of Price Action Patterns", fontname="Arial", fontsize=14)
            ax.set_xlabel("Pattern", fontname="Arial", fontsize=12)
            ax.set_ylabel("Count", fontname="Arial", fontsize=12)
            plt.xticks(rotation=45, fontname="Arial")
            
            chart_window = tk.Toplevel(self.root)
            chart_window.title("Pattern Chart")
            canvas = FigureCanvasTkAgg(fig, master=chart_window)
            canvas.draw()
            canvas.get_tk_widget().pack()
        except Exception as e:
            error_msg = f"Error in showing chart: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def show_errors(self):
        try:
            conn, cursor = get_db_connection()
            cursor.execute("SELECT * FROM errors")
            errors = cursor.fetchall()
            self.error_text.delete(1.0, tk.END)
            for error in errors:
                self.error_text.insert(tk.END, f"{error[0]}: {error[1]}\n")
            conn.close()
        except Exception as e:
            error_msg = f"Error in showing errors: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.notify_error(error_msg)
    
    def fix_errors(self):
        try:
            self.log_activity("Fixing errors...")
            conn, cursor = get_db_connection()
            cursor.execute("DELETE FROM errors")
            conn.commit()
            conn.close()
            self.log_activity("Errors cleared")
            self.show_errors()
        except Exception as e:
            error_msg = f"Error in fixing errors: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def copy_errors(self):
        try:
            conn, cursor = get_db_connection()
            cursor.execute("SELECT * FROM errors")
            errors = cursor.fetchall()
            conn.close()
            if not errors:
                self.log_activity("No errors to copy.")
                return
            
            error_text = "\n".join(f"{error[0]}: {error[1]}" for error in errors)
            pyperclip.copy(error_text)
            self.log_activity("Errors copied to clipboard.")
        except Exception as e:
            error_msg = f"Error in copying errors: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def copy_activity_text(self):
        try:
            text = self.activity_text.get(1.0, tk.END).strip()
            if not text:
                self.log_activity("No text to copy in Crawler tab.")
                return
            pyperclip.copy(text)
            self.log_activity("Crawler text copied to clipboard.")
        except Exception as e:
            error_msg = f"Error in copying Crawler text: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def copy_trades_text(self):
        try:
            text = self.trades_text.get(1.0, tk.END).strip()
            if not text:
                self.log_activity("No text to copy in Trades tab.")
                return
            pyperclip.copy(text)
            self.log_activity("Trades text copied to clipboard.")
        except Exception as e:
            error_msg = f"Error in copying Trades text: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def copy_trade_reports_text(self):
        try:
            text = self.trade_reports_text.get(1.0, tk.END).strip()
            if not text:
                self.log_activity("No text to copy in Trade Reports tab.")
                return
            pyperclip.copy(text)
            self.log_activity("Trade Reports text copied to clipboard.")
        except Exception as e:
            error_msg = f"Error in copying Trade Reports text: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def copy_news_text(self):
        try:
            text = self.news_text.get(1.0, tk.END).strip()
            if not text:
                self.log_activity("No text to copy in News tab.")
                return
            pyperclip.copy(text)
            self.log_activity("News text copied to clipboard.")
        except Exception as e:
            error_msg = f"Error in copying News text: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
    
    def notify_error(self, error_msg):
        messagebox.showerror("Error", error_msg)
    
    def start_crawler(self):
        if not self.is_running:
            self.should_stop = False
            self.update_status("On")
            self.log_activity("Crawler started...")
            threading.Thread(target=self.run_job, daemon=True).start()
    
    def stop_crawler(self):
        if self.is_running:
            self.should_stop = True
            self.update_status("Off")
            self.log_activity("Crawler stopped...")
    
    def start_trading_thread(self):
        threading.Thread(target=self.start_trading, daemon=True).start()
    
    def start_trading(self):
        try:
            self.log_activity("Connecting to MetaTrader 5 to start trading...")
            if not mt5.initialize():
                raise Exception("Failed to connect to MetaTrader 5")
            
            self.log_activity("Connected to MetaTrader 5 successfully")
            
            conn, cursor = get_db_connection()
            cursor.execute("SELECT * FROM market_data_5min WHERE symbol='XAUUSD' ORDER BY date DESC LIMIT 1000")
            df = pd.DataFrame(cursor.fetchall(), columns=['date', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
            conn.close()
            patterns = analyze_price_action(gui=self)
            signals = []
            for i in range(len(df)):
                for pattern in patterns:
                    if pattern[0] != df['date'][i]:
                        continue
                    pattern_name = pattern[2]
                    if "bull" in pattern_name.lower() or "high 1" in pattern_name.lower() or "high 2" in pattern_name.lower():
                        position_type = "buy"
                        stop_loss, take_profit = calculate_risk_reward(df, i, position_type, self)
                        signals.append((df['date'][i], pattern[1], position_type, df['close'][i], stop_loss, take_profit, pattern_name))
                    elif "bear" in pattern_name.lower() or "double top" in pattern_name.lower():
                        position_type = "sell"
                        stop_loss, take_profit = calculate_risk_reward(df, i, position_type, self)
                        signals.append((df['date'][i], pattern[1], position_type, df['close'][i], stop_loss, take_profit, pattern_name))
            
            for signal in signals:
                time, symbol, position_type, entry_price, stop_loss, take_profit, pattern = signal
                lot_size = 0.1
                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": symbol,
                    "volume": lot_size,
                    "type": mt5.ORDER_TYPE_BUY if position_type == "buy" else mt5.ORDER_TYPE_SELL,
                    "price": entry_price,
                    "sl": stop_loss,
                    "tp": take_profit,
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": mt5.ORDER_FILLING_IOC,
                }
                result = mt5.order_send(request)
                if result.retcode != mt5.TRADE_RETCODE_DONE:
                    self.log_activity(f"Error executing trade: {result.comment}")
                    conn, cursor = get_db_connection()
                    cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                                   (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), f"Trade execution failed: {result.comment}"))
                    conn.commit()
                    conn.close()
                    self.show_errors()
                    self.notify_error(f"Trade execution failed: {result.comment}")
                else:
                    self.log_activity(f"Trade executed: {position_type} {symbol} at price {entry_price}, Pattern: {pattern}")
                    conn, cursor = get_db_connection()
                    cursor.execute("INSERT INTO trades (symbol, entry_time, entry_price, position_type, pattern) VALUES (?, ?, ?, ?, ?)",
                                   (symbol, time, entry_price, position_type, pattern))
                    conn.commit()
                    conn.close()
            
            mt5.shutdown()
            self.update_trades()
            self.update_trade_reports()
        except Exception as e:
            error_msg = f"Error in starting trading: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
                def run_job(self):
        try:
            if not self.should_stop:
                # چک کردن اخبار
                events = fetch_economic_events(self)
                self.update_news(events)
                current_time = datetime.now()
                in_news_time = False
                for event in events:
                    event_time = datetime.strptime(event[0], '%Y-%m-%d %H:%M:%S')
                    time_diff = abs((current_time - event_time).total_seconds()) / 60
                    if time_diff <= 30:
                        in_news_time = True
                        break
                
                if in_news_time:
                    self.log_activity("In important news time, trading paused")
                    self.root.after(3600000, self.run_job)
                    return
                
                # جمع‌آوری مقالات آموزشی
                fetch_investopedia_articles(self, topic="price action")
                fetch_babypips_education(self)
                
                # جمع‌آوری اخبار و تحلیل‌ها
                fetch_investing_news(self)
                fetch_fxstreet_analysis(self)
                
                # جمع‌آوری ویدیوها
                new_videos = crawl_youtube(self)
                
                # جمع‌آوری داده‌های بازار
                new_market_data = crawl_market_data(gui=self)
                
                # تحلیل بازار
                market_trend = self.analyze_market()
                self.log_activity(f"Market Analysis: {market_trend}")
                
                # کندل‌شناسی
                candles = self.analyze_candles()
                self.log_activity(f"Candle Analysis completed: {len(candles)} significant candles found")
                
                # الگوشناسی
                patterns = self.analyze_patterns()
                self.log_activity(f"Pattern Analysis completed: {len(patterns)} patterns found")
                
                # بک‌تست استراتژی‌ها برای یادگیری
                backtest_strategy(patterns, self)
                
                # آماده‌سازی برای معامله
                self.prepare_for_trading(patterns)
                self.log_activity("Preparation for trading completed")
                
                # شروع معاملات
                self.start_trading()
                
                if self.is_running:
                    self.root.after(3600000, self.run_job)
        except Exception as e:
            error_msg = f"Error in running job: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)

    def analyze_market(self):
        try:
            conn, cursor = get_db_connection()
            cursor.execute("SELECT * FROM market_data_5min WHERE symbol='XAUUSD' ORDER BY date DESC LIMIT 100")
            data = cursor.fetchall()
            df = pd.DataFrame(data, columns=['date', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
            conn.close()
            
            highs = df['high'].values
            lows = df['low'].values
            trend = "Range"
            if all(highs[i] > highs[i+1] for i in range(len(highs)-5)) and all(lows[i] > lows[i+1] for i in range(len(lows)-5)):
                trend = "Bullish"
            elif all(highs[i] < highs[i+1] for i in range(len(highs)-5)) and all(lows[i] < lows[i+1] for i in range(len(lows)-5)):
                trend = "Bearish"
            return trend
        except Exception as e:
            error_msg = f"Error in analyzing market: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
            return "Range"

    def analyze_candles(self):
        try:
            conn, cursor = get_db_connection()
            cursor.execute("SELECT * FROM market_data_5min WHERE symbol='XAUUSD' ORDER BY date DESC LIMIT 1000")
            data = cursor.fetchall()
            df = pd.DataFrame(data, columns=['date', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
            conn.close()
            
            candles = []
            for i in range(len(df)):
                open_price = df['open'][i]
                close_price = df['close'][i]
                high_price = df['high'][i]
                low_price = df['low'][i]
                
                if abs(close_price - open_price) > 2 * (high_price - close_price) and close_price > open_price:
                    candles.append((df['date'][i], "Trend Bar", "Bullish"))
                elif abs(close_price - open_price) < 0.1 * (high_price - low_price):
                    candles.append((df['date'][i], "Doji Bar", "Neutral"))
                elif (high_price - close_price) > 2 * (close_price - low_price) and close_price < open_price:
                    candles.append((df['date'][i], "Reversal Bar", "Bearish"))
            
            return candles
        except Exception as e:
            error_msg = f"Error in analyzing candles: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
            return []

    def analyze_patterns(self):
        try:
            conn, cursor = get_db_connection()
            cursor.execute("SELECT * FROM market_data_5min WHERE symbol='XAUUSD' ORDER BY date DESC LIMIT 1000")
            data = cursor.fetchall()
            df = pd.DataFrame(data, columns=['date', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
            
            cursor.execute("SELECT * FROM price_action_tips")
            tips = cursor.fetchall()
            
            patterns = []
            for i in range(len(df) - 5):
                if df['high'][i] > df['high'][i+1] and df['high'][i+1] > df['high'][i+2] and df['low'][i] < df['low'][i+1] and df['low'][i+1] < df['low'][i+2]:
                    patterns.append((df['date'][i], "XAUUSD", "Parabolic Wedge", "Potential reversal pattern detected"))
                
                if i > 2 and df['close'][i] > df['close'][i+1] and df['close'][i+1] > df['close'][i+2] and df['close'][i+2] > df['close'][i+3]:
                    if df['close'][i] < df['close'][i-1] and df['close'][i-1] < df['close'][i-2]:
                        patterns.append((df['date'][i], "XAUUSD", "Bull Flag", "Bullish continuation pattern"))
                
                if i > 4 and abs(df['high'][i] - df['high'][i+2]) < 0.01 * df['high'][i] and df['low'][i+1] < df['low'][i] and df['low'][i+1] < df['low'][i+2]:
                    patterns.append((df['date'][i], "XAUUSD", "Double Top", "Bearish reversal pattern"))
                
                if i > 2 and df['close'][i] > df['open'][i] and df['close'][i-1] < df['open'][i-1] and df['close'][i-2] > df['open'][i-2]:
                    patterns.append((df['date'][i], "XAUUSD", "High 1", "Bullish entry after pullback"))
                
                if i > 4 and df['close'][i] > df['open'][i] and df['close'][i-1] < df['open'][i-1] and df['close'][i-2] > df['open'][i-2] and df['close'][i-3] < df['open'][i-3] and df['close'][i-4] > df['open'][i-4]:
                    patterns.append((df['date'][i], "XAUUSD", "High 2", "Strong bullish entry after double pullback"))
                
                if i > 1 and (df['high'][i] - df['close'][i]) > 2 * (df['close'][i] - df['low'][i]) and df['close'][i] < df['open'][i]:
                    patterns.append((df['date'][i], "XAUUSD", "Bearish Reversal Bar", "Potential bearish reversal"))
                
                if i > 1 and abs(df['close'][i] - df['open'][i]) > 2 * (df['high'][i] - df['close'][i]) and df['close'][i] > df['open'][i]:
                    patterns.append((df['date'][i], "XAUUSD", "Trend Bar", "Strong bullish trend bar"))
            
            for tip in tips:
                pattern = tip[2]
                if "bull" in pattern.lower() and df['close'][i] > df['open'][i]:
                    patterns.append((df['date'][i], "XAUUSD", pattern, tip[3]))
            
            cursor.execute("INSERT INTO analysis (date, symbol, pattern, description) VALUES (?, ?, ?, ?)", patterns)
            conn.commit()
            conn.close()
            return patterns
        except Exception as e:
            error_msg = f"Error in analyzing patterns: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)
            return []

    def prepare_for_trading(self, patterns):
        try:
            conn, cursor = get_db_connection()
            cursor.execute("SELECT * FROM market_data_5min WHERE symbol='XAUUSD' ORDER BY date DESC LIMIT 1000")
            df = pd.DataFrame(cursor.fetchall(), columns=['date', 'symbol', 'open', 'high', 'low', 'close', 'volume'])
            conn.close()
            support = min(df['low'].values[-50:])
            resistance = max(df['high'].values[-50:])
            self.log_activity(f"Key Levels: Support: {support}, Resistance: {resistance}")
            
            signals = []
            for i in range(len(df)):
                for pattern in patterns:
                    if pattern[0] != df['date'][i]:
                        continue
                    pattern_name = pattern[2]
                    if "bull" in pattern_name.lower() or "high 1" in pattern_name.lower() or "high 2" in pattern_name.lower():
                        position_type = "buy"
                        stop_loss, take_profit = calculate_risk_reward(df, i, position_type, self)
                        signals.append((df['date'][i], pattern[1], position_type, df['close'][i], stop_loss, take_profit, pattern_name))
                    elif "bear" in pattern_name.lower() or "double top" in pattern_name.lower():
                        position_type = "sell"
                        stop_loss, take_profit = calculate_risk_reward(df, i, position_type, self)
                        signals.append((df['date'][i], pattern[1], position_type, df['close'][i], stop_loss, take_profit, pattern_name))
            
            signals_df = pd.DataFrame(signals, columns=['time', 'symbol', 'position_type', 'entry_price', 'stop_loss', 'take_profit', 'pattern'])
            signals_df.to_csv(os.path.join(MT5_FILES_PATH, 'signals_for_mt5.csv'), index=False)
            signals_df.to_csv(os.path.join(ARCHIVE_PATH, 'signals_for_mt5.csv'), index=False)
            self.log_activity("Signals saved for MetaTrader 5")
            self.update_stats(0, len(cursor.execute("SELECT * FROM pending_downloads").fetchall()), 
                             len(cursor.execute("SELECT * FROM market_data_5min").fetchall()), len(patterns), len(signals))
            self.update_trades()
        except Exception as e:
            error_msg = f"Error in preparing for trading: {str(e)}"
            self.log_activity(error_msg)
            conn, cursor = get_db_connection()
            cursor.execute("INSERT INTO errors (datetime, error_message) VALUES (?, ?)", 
                           (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), error_msg))
            conn.commit()
            conn.close()
            self.show_errors()
            self.notify_error(error_msg)

# تابع برای اجرای خزنده با رابط کاربری
def run_crawler():
    root = tk.Tk()
    gui = CrawlerGUI(root)
    root.mainloop()

# بارگذاری مدل Whisper
whisper_model = whisper.load_model("base")

# اجرای خزنده با رابط کاربری
if __name__ == "__main__":
    run_crawler()
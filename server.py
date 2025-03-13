"""
Enter [python server.py] in the terminal
"""

import threading
import re
import gradio as gr
import ollama
from flask import Flask, jsonify, request
from flask_cors import CORS  
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from chromedriver_autoinstaller import install
import time
import json
import os

# Initialize Flask app
app = Flask(__name__)
CORS(app)

# --- Web Scraping Configuration ---
CATEGORIES = {
    "motherboard": "https://pcx.com.ph/collections/motherboards",
    "processor": "https://pcx.com.ph/collections/processors",
    "graphics card": "https://pcx.com.ph/collections/graphics-cards",
    "ram": "https://pcx.com.ph/collections/memory-modules"
}

# Global variable for storing products
PRODUCTS = []

def parse_price(price_text):
    """Extracts the numerical price from text."""
    price_text = re.sub(r"[^\d.]", "", price_text)
    try:
        return float(price_text) if price_text else 0.0
    except ValueError:
        return 0.0

def get_local_image(category):
    """Return the local image path based on the product category."""
    image_filename = category.replace(" ", "_").lower() + ".png"
    return os.path.join("product_img", image_filename)

def scrape_products():
    """Scrape PC products from the given websites."""
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")

    chromedriver_path = install()

    service = Service(chromedriver_path)
    global driver
    driver = webdriver.Chrome(service=service, options=options)

    products = []
    product_id = 1

    for category, url in CATEGORIES.items():
        driver.get(url)
        
        try:
            WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CLASS_NAME, "t4s-product-title")))
        except:
            print(f"Timeout waiting for {category} products to load!")
            continue
        
        product_elements = driver.find_elements(By.CLASS_NAME, "t4s-product-title")

        for product in product_elements[:6]:
            try:
                name_element = product.find_element(By.TAG_NAME, "a")
                name = name_element.text.strip()
                brand = name.split()[0]
                link = name_element.get_attribute("href")

                price_element = product.find_element(By.XPATH, "following-sibling::div[contains(@class, 't4s-product-price')]")
                price = parse_price(price_element.text.strip())

                image_link = get_local_image(category)

                products.append({
                    "id": product_id,
                    "name": name,
                    "brand": brand.lower(),
                    "category": category.lower(),
                    "price": price,
                    "link": link,
                    "image": image_link
                })
                product_id += 1
            except Exception as e:
                print("Error extracting product:", e)

    driver.quit()
    return products

def update_product_data():
    """Periodically update the scraped product list."""
    global PRODUCTS
    while True:
        print("Scraping new product data...")
        PRODUCTS = scrape_products()
        print(f"Updated product list with {len(PRODUCTS)} items.")
        time.sleep(3600)  # Refresh every hour

# Start background thread for updating products
threading.Thread(target=update_product_data, daemon=True).start()

@app.route('/get_products', methods=['GET'])
def get_products():
    products = scrape_products()
    return jsonify(PRODUCTS)

@app.route('/get_product/<int:product_id>', methods=['GET'])
def get_product(product_id):
    products = scrape_products()
    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    return jsonify(product) if product else (jsonify({"error": "Product not found"}), 404)

# Load products from JSON file
PRODUCTS = []
with open("products.json", "r") as file:
    PRODUCTS = json.load(file)
    print(f"Loaded {len(PRODUCTS)} products from JSON.")

SYSTEM_PROMPT = """You are a concise and helpful PC parts specialist in the Philippines.
You have real-time data on available PC components and their prices.
If no exact match is found, suggest close alternatives.
Stay brief and relevant."""

chat_history = []

def find_relevant_products(query, category=None):
    """Finds products based on category and query."""
    query = query.lower()
    filtered_products = PRODUCTS

    if category:
        filtered_products = [p for p in filtered_products if p["category"].lower() == category.lower()]

    matches = sorted(
        [p for p in filtered_products if query in p["name"].lower() or query in p["category"].lower()],
        key=lambda p: p["price"]
    )

    return [{"product": p, "reason": "Matches your search criteria"} for p in matches[:3]] if matches else []

@app.route("/chat", methods=["POST"])
def chat():
    data = request.json
    user_message = data.get("message", "").lower()

    if not user_message:
        return jsonify({"error": "No message provided"}), 400

    category = next((cat for cat in CATEGORIES if cat in user_message), None)

    # Search for relevant products
    relevant_products = find_relevant_products(user_message, category=category)

    if relevant_products:
        product_info = "<br>".join([
            f"- <b>{p['product']['name']}</b> ({p['product']['brand']}) - PHP {p['product']['price']}<br>"
            f"  <a href='{p['product'].get('link', '#')}'>View</a><br>"
            f"  <i>{p['reason']}</i>"
            for p in relevant_products
        ])
        return jsonify({"reply": f"Here are some options:<br><br>{product_info}"})

    # If the user is asking about a specific product, check if we can answer that
    for product in PRODUCTS:
        if product["name"].lower() in user_message or product["category"].lower() in user_message:
            return jsonify({"reply": f"{product['name']} ({product['brand']}) - PHP {product['price']}<br>"
                                      f"<a href='{product.get('link', '#')}'>View product</a><br>"
                                      f"<i>{product.get('description', 'No description available.')}</i>"})

    # AI fallback for everything else
    bot_reply = ollama.generate(user_message)
    return jsonify({"reply": bot_reply.replace("\n", "<br>")})

if __name__ == "__main__":
    app.run(debug=True)



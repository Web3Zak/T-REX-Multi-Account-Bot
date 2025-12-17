#!/usr/bin/env python3
"""
==================== ADS MODE ====================
1) Проверка логина
2) Если не залогинен:
   - twitter → кнопка X → Authorize
   - google  → кнопка Google → выбор первого аккаунта
3) Check-in + Assets Check-in
4) Закрытие ADS профиля

==================== CHROME MODE =================
1) Проверка логина
2) Если не залогинен:
   - twitter → импорт cookies → X → Authorize
   - google:
        • если email+password указаны → авто
        • если нет → ручной ввод
3) Check-in + Assets Check-in

Поддержка proxy из accounts.json:
"proxy": "http://user:pass@ip:port" или "http://ip:port"

"""

import subprocess
import time
import json
import logging
import shutil
import requests
from pathlib import Path
from typing import Optional, Dict, List

from playwright.sync_api import sync_playwright, Page, TimeoutError

# =========================================================
# CONFIG
# =========================================================
URL_LOGIN = "https://www.trex.xyz/auth/portal-login"
URL_QUEST = "https://www.trex.xyz/portal/quest"

PROFILE_AVATAR_SELECTOR = 'img[alt="profile"]'

TWITTER_BUTTON_SELECTOR = 'button:has-text("x")'
TWITTER_AUTHORIZE_XPATH = 'xpath=/html/body/div[1]/div/div/div[2]/main/div/div/div[2]/div/div/div[1]/div[3]/button'

GOOGLE_BUTTON_SELECTOR = 'button:has-text("google")'
GOOGLE_ACCOUNT_XPATH = 'xpath=/html/body/div[2]/div[1]/div[1]/div[2]/c-wiz/main/div[2]/div/div/div[1]/form/span/section/div/div/div/div/ul/li[1]/div'
GOOGLE_EMAIL_FIELD = 'input#identifierId'
GOOGLE_PASSWORD_FIELD = 'xpath=//*[@id="password"]/div[1]/div/div[1]/input'
GOOGLE_NEXT_XPATH = 'xpath=/html/body/div[2]/div[1]/div[1]/div[2]/c-wiz/main/div[3]/div/div[1]/div/div/button'
GOOGLE_EXTRA_BUTTON_XPATH = 'xpath=/html/body/div[2]/div[1]/div[1]/div[2]/c-wiz/main/div[3]/div/div/div[2]/div/div/button'

CHECKIN_BUTTON_SELECTOR = 'button:has-text("Check in")'
ASSETS_BUTTON_XPATH = 'xpath=/html/body/div[1]/div[2]/div/div/div/div[2]/div/div/div[1]/div[3]/div/div[2]/div[2]/button[2]'

ADSPOWER_API = "http://127.0.0.1:50325"
CDP_STARTUP_TIMEOUT = 20

# =========================================================
# PATHS & LOGGING
# =========================================================
BASE_DIR = Path(__file__).parent.resolve()
PROFILE_DIR = BASE_DIR / "profiles"
LOG_DIR = BASE_DIR / "logs"
PROFILE_DIR.mkdir(exist_ok=True)
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "trex.log", encoding="utf-8")
    ]
)
logger = logging.getLogger("trex")

# =========================================================
# COMMON
# =========================================================
def is_logged_in(page: Page) -> bool:
    try:
        page.wait_for_selector(PROFILE_AVATAR_SELECTOR, timeout=8000)
        return True
    except TimeoutError:
        return False


def handle_checkin(page: Page, name: str):
    page.goto(URL_QUEST, wait_until="domcontentloaded")
    time.sleep(2)

    try:
        btn = page.locator(CHECKIN_BUTTON_SELECTOR)
        if btn.is_enabled():
            btn.click()
            logger.info("[%s] Check-in выполнен", name)
    except Exception:
        pass

    try:
        asset = page.locator(ASSETS_BUTTON_XPATH)
        if asset.is_enabled():
            asset.click()
            time.sleep(2)

            try:
                page.wait_for_selector('text="Verification failed."', timeout=4000)
                logger.warning("Нужно пополнить баланс ETH")
            except TimeoutError:
                logger.info("Assets check-in выполнен успешно")
        else:
            logger.info("Доп. элемент неактивен.")
    except Exception:
        pass
# =========================================================
# ADSPOWER
# =========================================================
def ads_start(profile_id: str) -> str:
    r = requests.get(f"{ADSPOWER_API}/api/v1/browser/start", params={"user_id": profile_id})
    r.raise_for_status()
    return r.json()["data"]["ws"]["puppeteer"]


def ads_stop(profile_id: str):
    requests.get(f"{ADSPOWER_API}/api/v1/browser/stop", params={"user_id": profile_id})


def ads_login(page: Page, acc: Dict) -> bool:
    page.goto(URL_LOGIN, wait_until="domcontentloaded")

    if is_logged_in(page):
        return True

    if acc["login_method"] == "twitter":
        page.click(TWITTER_BUTTON_SELECTOR)
        try:
            page.wait_for_selector(TWITTER_AUTHORIZE_XPATH, timeout=6000).click()
        except TimeoutError:
            logger.warning("[%s] Войдите в Twitter вручную", acc["name"])

    elif acc["login_method"] == "google":
        page.click(GOOGLE_BUTTON_SELECTOR)
        try:
            page.wait_for_selector(GOOGLE_ACCOUNT_XPATH, timeout=6000).click()
        except TimeoutError:
            logger.warning("[%s] Войдите в Google вручную", acc["name"])

    for _ in range(60):
        if is_logged_in(page):
            return True
        time.sleep(1)

    return False

# =========================================================
# CHROME
# =========================================================
def detect_chrome_executable() -> Optional[str]:
    paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
    ]
    for p in paths:
        if Path(p).exists():
            return p
    return shutil.which("chrome")


def load_twitter_cookies(context, path: str):
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    cookies = []
    for c in raw:
        domain = c.get("domain", ".twitter.com")

        # принудительно заменяем x.com → twitter.com
        if domain.endswith("x.com"):
            domain = ".twitter.com"

        cookies.append({
            "name": c.get("name"),
            "value": c.get("value"),
            "domain": domain,
            "path": c.get("path", "/"),
            "expires": c.get("expirationDate") or c.get("expires"),
            "secure": True,
            "httpOnly": c.get("httpOnly", False),
            "sameSite": "Lax"
        })

    context.add_cookies(cookies)


def chrome_login(page: Page, context, acc: Dict) -> bool:
    page.goto(URL_LOGIN, wait_until="domcontentloaded")

    if is_logged_in(page):
        return True

    if acc["login_method"] == "twitter":
        load_twitter_cookies(context, acc["cookies"])
        with page.expect_popup() as p:
            page.click(TWITTER_BUTTON_SELECTOR)
        popup = p.value
        try:
            popup.wait_for_selector(TWITTER_AUTHORIZE_XPATH, timeout=6000).click()
        except TimeoutError:
            logger.warning("[%s] Twitter Authorize не найден", acc["name"])

    elif acc["login_method"] == "google":
        with page.expect_popup() as p:
            page.click(GOOGLE_BUTTON_SELECTOR)
        popup = p.value

        email = acc.get("google_email")
        password = acc.get("google_password")

        if email and password:
            popup.fill(GOOGLE_EMAIL_FIELD, email)
            popup.click(GOOGLE_NEXT_XPATH)
            popup.fill(GOOGLE_PASSWORD_FIELD, password)
            popup.click(GOOGLE_NEXT_XPATH)
            try:
                popup.click(GOOGLE_EXTRA_BUTTON_XPATH)
            except Exception:
                pass
        else:
            logger.info("[%s] Введите Google данные вручную", acc["name"])

    for _ in range(60):
        if is_logged_in(page):
            return True
        time.sleep(1)

    return False

# =========================================================
# RUN ACCOUNT
# =========================================================
def run_account(acc: Dict):
    name = acc["name"]
    logger.info("=== RUN %s ===", name)

    with sync_playwright() as pw:

        # ---------------- ADS ----------------
        if acc["browser_mode"] == "ads":
            ws = ads_start(acc["adspower_profile_id"])
            browser = pw.chromium.connect_over_cdp(ws)
            page = browser.contexts[0].new_page()

            if ads_login(page, acc):
                handle_checkin(page, name)

            browser.close()
            ads_stop(acc["adspower_profile_id"])

        # ---------------- CHROME ----------------
        else:
            chrome = detect_chrome_executable()
            if not chrome:
                logger.error("[%s] Chrome не найден", name)
                return

            profile = PROFILE_DIR / name
            profile.mkdir(exist_ok=True)

            args = [
                chrome,
                f"--remote-debugging-port={acc['remote_debugging_port']}",
                f"--user-data-dir={profile}",
                "--no-first-run",
                "--no-default-browser-check",
            ]

            if acc.get("proxy"):
                args.append(f"--proxy-server={acc['proxy']}")

            proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            time.sleep(3)
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{acc['remote_debugging_port']}")
            context = browser.contexts[0]
            page = context.new_page()

            if chrome_login(page, context, acc):
                handle_checkin(page, name)

            browser.close()
            proc.terminate()

# =========================================================
# MAIN
# =========================================================
def main():
    with open("accounts.json", encoding="utf-8") as f:
        accounts: List[Dict] = json.load(f)

    print("\nАккаунты:")
    for i, a in enumerate(accounts, 1):
        print(f"{i}. {a['name']} ({a['browser_mode']} / {a['login_method']})")
    print("0. Все\n")

    choice = int(input("Выбор: ").strip())
    run_list = accounts if choice == 0 else [accounts[choice - 1]]

    for acc in run_list:
        run_account(acc)
        time.sleep(3)

if __name__ == "__main__":
    main()

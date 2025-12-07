#!/usr/bin/env python3
"""
trex_multi_account_timer_text.py
Логин через Twitter + Check in на T-REX + вывод текста таймера без конвертации в секунды.
Поддержка нескольких аккаунтов с прокси и выбором конкретного аккаунта или всех.
"""

import json
import logging
import time
from typing import List, Dict
from playwright.sync_api import sync_playwright, TimeoutError, Page, ElementHandle

# -----------------------
# Настройки
# -----------------------
URL_LOGIN = "https://www.trex.xyz/auth/portal-login"
URL_QUEST = "https://www.trex.xyz/portal/quest"
LOGIN_BUTTON_SELECTOR = 'button:has-text("x")'
CHECKIN_BUTTON_SELECTOR = 'button:has-text("Check in")'
TIMER_XPATH = '/html/body/div[1]/div[2]/div/div/div/div[2]/div/div/div[1]/div[1]/div[1]/div'

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("trex_bot")

# -----------------------
# Функции для логина
# -----------------------
def load_cookies(path: str) -> List[Dict]:
    """Загрузка cookies из JSON-файла."""
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    cookies = []
    for c in raw:
        cookies.append({
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain") or ".twitter.com",
            "path": c.get("path", "/"),
            "expires": c.get("expirationDate") or c.get("expires"),
            "secure": c.get("secure", True),
            "httpOnly": c.get("httpOnly", False),
        })
    return cookies

def click_authorize_button_safe(twitter_page: Page):
    """Нажатие кнопки Authorize с обработкой закрытия popup."""
    try:
        btn = twitter_page.wait_for_selector('button:has-text("Authorize")', timeout=5000)
        if btn:
            logger.info("Нажимаем кнопку Authorize...")
            try:
                btn.click()
            except:
                twitter_page.evaluate('(el) => el.click()', btn)
            for _ in range(10):
                if twitter_page.is_closed():
                    logger.info("Popup закрыт после Authorize")
                    break
                time.sleep(1)
            return True
    except TimeoutError:
        logger.warning("Кнопка Authorize не найдена.")
        return False

def check_login_success(page: Page) -> bool:
    """Проверка успешного входа по тексту 'Your Points'."""
    try:
        page.wait_for_selector('text=Your Points', timeout=5000)
        logger.info("Текст 'Your Points' найден — логин подтверждён.")
        return True
    except TimeoutError:
        logger.error("Текст 'Your Points' не найден — логин не подтверждён.")
        return False

def login_via_twitter(page: Page, context, cookies_path: str) -> bool:
    """Логин через Twitter с импортом cookies и авторизацией OAuth."""
    logger.info("Импортируем cookies Twitter...")
    try:
        cookies = load_cookies(cookies_path)
        context.add_cookies(cookies)
    except FileNotFoundError:
        logger.error(f"Файл cookies {cookies_path} не найден!")
        return False

    page.reload()
    logger.info("Страница T-REX обновлена.")

    try:
        with page.expect_popup() as pop_info:
            page.click(LOGIN_BUTTON_SELECTOR, timeout=10000)
        twitter_page = pop_info.value
    except TimeoutError:
        logger.warning("Popup не открылся — используем текущую вкладку")
        twitter_page = page

    twitter_page.context.add_cookies(cookies)
    twitter_page.reload()
    time.sleep(1)

    click_authorize_button_safe(twitter_page)
    page.wait_for_load_state("networkidle")
    page.goto(URL_LOGIN, timeout=30000)

    return check_login_success(page)

# -----------------------
# Функции для Check in и таймера
# -----------------------
def find_checkin_button(page: Page) -> ElementHandle | None:
    try:
        return page.wait_for_selector(CHECKIN_BUTTON_SELECTOR, timeout=5000)
    except:
        return None

def is_button_enabled(button: ElementHandle) -> bool:
    try:
        if button.is_enabled():
            return True
        aria = button.get_attribute("aria-disabled")
        classes = button.get_attribute("class") or ""
        disabled_attr = button.get_attribute("disabled")
        if aria and aria.lower() in ("true", "1"):
            return False
        if "disabled" in classes.lower():
            return False
        if disabled_attr is not None:
            return False
        return True
    except:
        return False

def read_timer_text(page: Page) -> str | None:
    """Считывает и возвращает текст таймера без преобразования в секунды."""
    try:
        el = page.query_selector(f'xpath={TIMER_XPATH}')
        if el:
            text = el.inner_text().strip()
            return text
        else:
            return None
    except Exception as e:
        logger.error(f"Ошибка при чтении таймера: {e}")
        return None

def handle_checkin(page: Page):
    page.goto(URL_QUEST)
    page.wait_for_load_state("networkidle")

    btn = find_checkin_button(page)
    if not btn:
        logger.warning("Кнопка Check in не найдена.")
        return

    if is_button_enabled(btn):
        logger.info("Кнопка активна, кликаем...")
        try:
            btn.click()
            logger.info("Check in выполнен!")
        except:
            logger.error("Не удалось кликнуть Check in.")
    else:
        logger.info("Кнопка неактивна, выводим таймер...")
        timer_text = read_timer_text(page)
        if timer_text:
            logger.info(f"Таймер: {timer_text}")
        else:
            logger.warning("Таймер не найден или пуст.")

# -----------------------
# Работа с несколькими аккаунтами
# -----------------------
def main():
    with open("accounts.json", "r", encoding="utf-8") as f:
        accounts = json.load(f)

    print("Список аккаунтов:")
    for i, acc in enumerate(accounts, start=1):
        print(f"{i}. {acc['name']}")
    print("0. Все аккаунты")

    choice = input("Выберите аккаунт (номер) или 0 для всех: ").strip()
    try:
        choice_num = int(choice)
    except ValueError:
        print("Неверный ввод")
        return

    if choice_num == 0:
        selected_accounts = accounts
    elif 1 <= choice_num <= len(accounts):
        selected_accounts = [accounts[choice_num - 1]]
    else:
        print("Неверный номер аккаунта")
        return

    with sync_playwright() as pw:
        for acc in selected_accounts:
            logger.info(f"=== Запуск для аккаунта {acc['name']} ===")
            proxy_conf = {"server": acc["proxy"]} if acc.get("proxy") else None

            browser = pw.chromium.launch(headless=False)
            context = browser.new_context(proxy=proxy_conf) if proxy_conf else browser.new_context()
            page = context.new_page()

            page.goto(URL_LOGIN)
            logger.info("Страница входа открыта.")

            ok = login_via_twitter(page, context, acc['cookies'])
            if ok:
                logger.info(f"=== УСПЕШНАЯ АВТОРИЗАЦИЯ {acc['name']} ===")
                handle_checkin(page)
            else:
                logger.error(f"=== ЛОГИН НЕ ВЫПОЛНЕН {acc['name']} ===")

            time.sleep(3)
            browser.close()

if __name__ == "__main__":
    main()

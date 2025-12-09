#!/usr/bin/env python3
"""
main_chrome_profiles.py

Финальная версия:
- ВСЕГДА создаёт профиль в ./profiles/<AccountName>
- login_method: "twitter" или "google"
- Google: ручной (если нет google_email) или автоматический (если email+password заданы)
- Поддержка proxy, cookies (для Twitter)
- Check-in + доп. действие + проверка "Verification failed."
- Логирование в logs/trex_bot.log
"""

import subprocess
import time
import os
import json
import logging
import shutil
from pathlib import Path
from typing import Optional, List, Dict

from playwright.sync_api import sync_playwright, TimeoutError, Page

# -----------------------
# Селекторы и URL
# -----------------------
URL_LOGIN = "https://www.trex.xyz/auth/portal-login"
URL_QUEST = "https://www.trex.xyz/portal/quest"

TWITTER_BUTTON_SELECTOR = 'button:has-text("x")'
GOOGLE_BUTTON_SELECTOR = 'button:has-text("google")'
PROFILE_AVATAR_SELECTOR = 'img[alt="profile"]'

# Google popup selectors
GOOGLE_EMAIL_FIELD = 'input#identifierId'
GOOGLE_PASSWORD_FIELD = 'xpath=//*[@id="password"]/div[1]/div/div[1]/input'
# XPath кнопки "Далее" после email / после пароля (по твоему указанию)
GOOGLE_NEXT_XPATH = 'xpath=/html/body/div[2]/div[1]/div[1]/div[2]/c-wiz/main/div[3]/div/div[1]/div/div/button'
# XPath выбора Google аккаунта (если список)
GOOGLE_ACCOUNT_XPATH = 'xpath=//*[@id="yDmH0d"]/c-wiz/main/div[2]/div/div/div[1]/form/span/section/div/div/div/div/ul/li[1]/div'
# После выбора аккаунта — дополнительная кнопка (если есть)
GOOGLE_EXTRA_BUTTON_XPATH = 'xpath=/html/body/div[2]/div[1]/div[1]/div[2]/c-wiz/main/div[3]/div/div/div[2]/div/div/button'

# Quest page
CHECKIN_BUTTON_SELECTOR = 'button:has-text("Check in")'
TIMER_XPATH = '/html/body/div[1]/div[2]/div/div/div/div[2]/div/div/div[1]/div[1]/div[1]/div'
NEW_ELEMENT_XPATH = '/html/body/div[1]/div[2]/div/div/div/div[2]/div/div/div[1]/div[3]/div/div[2]/div[2]/button[2]'

CDP_STARTUP_TIMEOUT = 20  # seconds

# -----------------------
# Папки и логирование
# -----------------------
SCRIPT_DIR = Path(__file__).parent.resolve()
PROFILE_BASE_DIR = SCRIPT_DIR / "profiles"
PROFILE_BASE_DIR.mkdir(parents=True, exist_ok=True)

LOG_DIR = SCRIPT_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "trex_bot.log", "a", encoding="utf-8")
    ]
)
logger = logging.getLogger("trex_bot")


# -----------------------
# Chrome helpers
# -----------------------
def detect_chrome_executable() -> Optional[str]:
    # Попытаться найти Chrome в популярных местах или в PATH
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    ]
    for c in candidates:
        if Path(c).exists():
            return str(Path(c))
    # попытка через which
    p = shutil.which("google-chrome") or shutil.which("chrome") or shutil.which("chromium") or shutil.which("chromium-browser")
    if p:
        return p
    return None


def start_chrome(chrome_path: str, user_data_dir: str, port: int, proxy: Optional[str]) -> subprocess.Popen:
    args = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-popup-blocking",
        "--disable-background-networking",
    ]
    if proxy:
        args.append(f"--proxy-server={proxy}")

    logger.info("Запуск Chrome: %s", " ".join(args))
    return subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait_for_cdp(port: int, timeout: int = CDP_STARTUP_TIMEOUT) -> bool:
    import urllib.request
    url = f"http://localhost:{port}/json/version"
    start = time.time()
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if resp.status == 200:
                    logger.info("CDP доступен на порту %s", port)
                    return True
        except Exception:
            time.sleep(0.4)
    logger.error("CDP НЕ доступен на порту %s за %s сек", port, timeout)
    return False


# -----------------------
# Cookies helper
# -----------------------
def load_cookies(path: str) -> List[Dict]:
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    out = []
    for c in raw:
        out.append({
            "name": c.get("name"),
            "value": c.get("value"),
            "domain": c.get("domain") or c.get("host") or ".twitter.com",
            "path": c.get("path", "/"),
            "expires": c.get("expirationDate") or c.get("expires"),
            "httpOnly": c.get("httpOnly", False),
            "secure": c.get("secure", True),
        })
    return out


# -----------------------
# T-REX helpers
# -----------------------
def is_logged_in(page: Page) -> bool:
    """Проверяем по аватару, залогинен ли уже профиль."""
    try:
        page.wait_for_selector(PROFILE_AVATAR_SELECTOR, timeout=10000)
        logger.info("Аватар найден — аккаунт уже авторизован.")
        return True
    except TimeoutError:
        logger.info("Аватар не найден — требуется логин.")
        return False


# -----------------------
# Twitter login
# -----------------------
def click_authorize_button_twitter(popup_page: Page):
    try:
        btn = popup_page.wait_for_selector('button:has-text("Authorize")', timeout=5000)
        # безопасный клик
        try:
            btn.click()
        except Exception:
            popup_page.evaluate("(el) => el.click()", btn)
        logger.info("Authorize нажата в Twitter popup.")
    except TimeoutError:
        logger.debug("Authorize кнопка не найдена в Twitter popup.")


def login_via_twitter(page: Page, context, cookies_path: Optional[str]) -> bool:
    logger.info("Запускаем Twitter login flow.")
    if cookies_path:
        try:
            cookies = load_cookies(cookies_path)
            context.add_cookies(cookies)
            logger.info("Twitter cookies добавлены в контекст.")
        except Exception as e:
            logger.error("Ошибка загрузки cookies: %s", e)
            return False

    try:
        page.reload(wait_until="networkidle")
    except Exception:
        time.sleep(1)

    try:
        with page.expect_popup() as pop:
            page.click(TWITTER_BUTTON_SELECTOR, timeout=8000)
        popup = pop.value
        logger.info("Twitter popup открыт.")
    except TimeoutError:
        logger.warning("Twitter popup не открылся — пробуем в текущей вкладке.")
        popup = page

    # best-effort: добавить cookies в popup контекст
    try:
        if cookies_path:
            popup.context.add_cookies(load_cookies(cookies_path))
    except Exception:
        pass

    click_authorize_button_twitter(popup)

    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass

    return is_logged_in(page)


# -----------------------
# Google login (ручной или автоматический)
# -----------------------
def login_via_google(page: Page, context, acc: Dict) -> bool:
    """
    acc может содержать:
      - google_email
      - google_password
    Если google_email пустой -> ручной режим (пользователь вводит сам во всплывающем окне)
    Если заданы email+password -> автоматический ввод
    """
    google_email = acc.get("google_email", "").strip()
    google_password = acc.get("google_password", "").strip()

    logger.info("Запускаем Google login flow.")

    try:
        with page.expect_popup() as pop:
            page.click(GOOGLE_BUTTON_SELECTOR, timeout=8000)
        popup = pop.value
        logger.info("Google popup открыт.")
    except TimeoutError:
        logger.error("Не удалось открыть Google popup.")
        return False

    # Если нет email -> ручной режим
    if not google_email:
        logger.info("Ручной режим Google: ожидаем, пока пользователь введёт данные во всплывающем окне...")
        # Ждём появления поля email или появления аватара на основной странице
        # Если поле появится — пользователь должен ввести данные вручную.
        try:
            popup.wait_for_selector(GOOGLE_EMAIL_FIELD, timeout=10000)
            logger.info("Поле email появилось, ждём ручного ввода (макс 120 сек).")
        except TimeoutError:
            logger.info("Поле email не появилось — возможно сразу показан список аккаунтов или автоматический редирект.")

        # Дать пользователю до 120 секунд на вручную завершить авторизацию
        for _ in range(120):
            if is_logged_in(page):
                logger.info("Пользователь завершил ручной вход в Google.")
                return True
            time.sleep(1)

        logger.error("Ручной вход не был завершён в отведённое время.")
        return False

    # Автоматический режим: ввод email -> Далее -> ввод пароля -> Далее
    logger.info("Автоматический режим Google: ввод email/password из accounts.json (будьте осторожны с безопасностью).")

    # Ввод email
    try:
        popup.wait_for_selector(GOOGLE_EMAIL_FIELD, timeout=10000)
        popup.fill(GOOGLE_EMAIL_FIELD, google_email)
        logger.info("Email введён.")
    except TimeoutError:
        logger.error("Поле email не найдено в Google popup.")
        return False

    # Нажать кнопку Далее (по твоему XPath)
    try:
        btn_next = popup.wait_for_selector(GOOGLE_NEXT_XPATH, timeout=8000)
        try:
            btn_next.click()
        except Exception:
            popup.evaluate("(el) => el.click()", btn_next)
        logger.info("Нажата кнопка 'Далее' после email.")
    except TimeoutError:
        logger.error("Кнопка 'Далее' после email не найдена.")
        return False

    time.sleep(1.0)

    # Ввод пароля
    try:
        popup.wait_for_selector(GOOGLE_PASSWORD_FIELD, timeout=10000)
        popup.fill(GOOGLE_PASSWORD_FIELD, google_password)
        logger.info("Пароль введён.")
    except TimeoutError:
        logger.error("Поле пароля не найдено в Google popup.")
        return False

    # Нажать кнопку Далее после пароля (тот же XPATH)
    try:
        btn_next_pass = popup.wait_for_selector(GOOGLE_NEXT_XPATH, timeout=8000)
        try:
            btn_next_pass.click()
        except Exception:
            popup.evaluate("(el) => el.click()", btn_next_pass)
        logger.info("Нажата кнопка 'Далее' после пароля.")
    except TimeoutError:
        logger.error("Кнопка 'Далее' после пароля не найдена.")
        return False

    # После выбора аккаунта — нажать дополнительную кнопку, если есть
    try:
        extra = popup.wait_for_selector(GOOGLE_EXTRA_BUTTON_XPATH, timeout=3000)
        try:
            extra.click()
            logger.info("Нажата дополнительная кнопка подтверждения в Google popup.")
        except Exception:
            popup.evaluate("(el) => el.click()", extra)
            logger.info("Нажата дополнительная кнопка (evaluate).")
    except TimeoutError:
        logger.debug("Дополнительная кнопка в Google popup не появилась.")

    # Ждём редирект / обновление основной страницы
    for _ in range(20):
        if is_logged_in(page):
            logger.info("Google login успешно завершён.")
            return True
        time.sleep(1)

    logger.error("Google login не завершён (автоматический режим).")
    return False


# -----------------------
# Check-in и доп. элемент
# -----------------------
def handle_checkin(page: Page):
    logger.info("Переход на страницу /portal/quest ...")
    try:
        page.goto(URL_QUEST)
    except Exception:
        logger.warning("Не удалось сразу загрузить /portal/quest; пробуем reload.")
        try:
            page.reload()
        except Exception:
            pass

    try:
        page.wait_for_load_state("networkidle", timeout=8000)
    except Exception:
        pass

    # 1) Check-in
    btn_checkin = None
    try:
        btn_checkin = page.wait_for_selector(CHECKIN_BUTTON_SELECTOR, timeout=6000)
    except TimeoutError:
        logger.warning("Check-in кнопка не найдена.")

    if btn_checkin and btn_checkin.is_enabled():
        try:
            btn_checkin.click()
            logger.info("Check-in нажат.")
            time.sleep(1)
        except Exception:
            logger.exception("Ошибка при клике Check-in.")
    else:
        try:
            timer_el = page.query_selector(f"xpath={TIMER_XPATH}")
            if timer_el:
                logger.info("Check-in таймер: %s", timer_el.inner_text().strip())
        except Exception:
            logger.debug("Не удалось прочитать таймер Check-in.")

    # 2) Доп. элемент (Assets check-in)
    try:
        new_btn = page.wait_for_selector(f'xpath={NEW_ELEMENT_XPATH}', timeout=6000)
    except TimeoutError:
        logger.warning("Доп. элемент (assets check-in) не найден.")
        return

    if new_btn and new_btn.is_enabled():
        try:
            new_btn.click()
            logger.info("Нажат доп. элемент (assets check-in).")
            time.sleep(2)
        except Exception:
            logger.exception("Ошибка при клике доп. элемента.")
            return

        # Проверка "Verification failed."
        try:
            page.wait_for_selector('text="Verification failed."', timeout=4000)
            logger.warning("Нужно пополнить баланс ETH")
        except TimeoutError:
            logger.info("Assets check-in выполнен успешно")
    else:
        logger.info("Доп. элемент неактивен.")


# -----------------------
# Run account
# -----------------------
def run_account(acc: Dict):
    name = acc.get("name", "account")
    login_method = acc.get("login_method", "twitter").lower()
    port = int(acc.get("remote_debugging_port", 0) or 0)
    proxy = acc.get("proxy", "") or None
    cookies = acc.get("cookies", "") or None

    logger.info("=== Обработка аккаунта: %s (mode=%s) ===", name, login_method)

    if port == 0:
        logger.error("[%s] remote_debugging_port не указан!", name)
        return

    # Создаём отдельную папку профиля в ./profiles/<name>
    user_data_dir = PROFILE_BASE_DIR / name
    user_data_dir.mkdir(parents=True, exist_ok=True)

    # Находим chrome
    chrome_path = acc.get("chrome_path") or detect_chrome_executable()
    if not chrome_path:
        logger.error("[%s] Chrome не найден. Укажите chrome_path в accounts.json или установите Chrome.", name)
        return

    # Запуск Chrome
    proc = None
    try:
        proc = start_chrome(str(chrome_path), str(user_data_dir), port, proxy)
    except Exception as e:
        logger.exception("[%s] Не удалось запустить Chrome: %s", name, e)
        return

    # Ждём CDP
    if not wait_for_cdp(port):
        logger.error("[%s] CDP не доступен на порту %s", name, port)
        try:
            proc.kill()
        except Exception:
            pass
        return

    # Подключаемся через Playwright CDP
    try:
        with sync_playwright() as pw:
            cdp_url = f"http://localhost:{port}"
            logger.info("[%s] Подключаемся к CDP %s", name, cdp_url)
            browser = pw.chromium.connect_over_cdp(cdp_url)

            context = browser.contexts[0] if browser.contexts else browser.new_context()
            page = context.new_page()

            # Открываем страницу логина
            try:
                page.goto(URL_LOGIN)
            except Exception:
                logger.warning("[%s] Не удалось загрузить страницу логина, пытаемся reload.", name)
                try:
                    page.reload()
                except Exception:
                    pass

            # Проверка: возможно уже залогинен
            if is_logged_in(page):
                logger.info("[%s] Профиль уже залогинен — пропускаем логин.", name)
                ok = True
            else:
                if login_method == "google":
                    ok = login_via_google(page, context, acc)
                else:
                    ok = login_via_twitter(page, context, cookies)

            if ok:
                logger.info("[%s] Авторизация успешна, выполняем Check-in.", name)
                handle_checkin(page)
            else:
                logger.error("[%s] Авторизация не выполнена.", name)

            try:
                browser.close()
            except Exception:
                pass

    except Exception as e:
        logger.exception("[%s] Ошибка при работе с CDP/Playwright: %s", name, e)

    # Закрываем процесс Chrome
    try:
        if proc:
            proc.terminate()
            time.sleep(1)
            if proc.poll() is None:
                proc.kill()
            logger.info("[%s] Chrome-процесс завершён.", name)
    except Exception:
        pass


# -----------------------
# MAIN
# -----------------------
def main():
    cfg = SCRIPT_DIR / "accounts.json"
    if not cfg.exists():
        logger.error("accounts.json не найден в директории скрипта.")
        return

    try:
        with open(cfg, "r", encoding="utf-8") as f:
            accounts = json.load(f)
    except Exception as e:
        logger.exception("Не удалось прочитать accounts.json: %s", e)
        return

    print("Аккаунты:")
    for i, acc in enumerate(accounts, start=1):
        print(f"{i}. {acc.get('name','(no name)')} (mode={acc.get('login_method','twitter')})")
    print("0. Все аккаунты")

    choice = input("Выберите номер аккаунта или 0 для всех: ").strip()
    try:
        idx = int(choice)
    except Exception:
        print("Неверный ввод")
        return

    to_run = []
    if idx == 0:
        to_run = accounts
    elif 1 <= idx <= len(accounts):
        to_run = [accounts[idx - 1]]
    else:
        print("Неверный номер")
        return

    for acc in to_run:
        run_account(acc)
        time.sleep(2)


if __name__ == "__main__":
    main()

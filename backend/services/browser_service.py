"""
浏览器服务 — 使用 Playwright 提供网页访问能力。

Agent 通过此服务访问外部网页，用于：
- 供应商核查 (企业信用查询)
- 药品/耗材比价 (阳光采购平台)
- 发票验真 (税务局查验平台)
- 政策查询 (医保政策文件)

单例共享浏览器实例，每次调用新建 page 然后 close。
"""

import base64
import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class BrowserService:
    """Playwright 浏览器服务 (懒初始化, 单例共享)。"""

    def __init__(self):
        self._browser = None
        self._playwright = None
        self._available: bool | None = None  # 缓存检测结果

    def is_available(self) -> bool:
        """检测 Playwright 浏览器二进制是否可用。"""
        if self._available is not None:
            return self._available
        try:
            import shutil
            # playwright 安装后 chromium 在 ~/.cache/ms-playwright/ 或类似路径
            # 最可靠的检测方式是尝试 import + 检查 executable
            from playwright._impl._driver import compute_driver_executable
            driver = compute_driver_executable()
            self._available = bool(driver and shutil.which(driver) or __import__('os').path.isfile(driver))
        except Exception:
            try:
                # fallback: 检测 playwright 包是否已安装
                import playwright
                self._available = True
            except ImportError:
                self._available = False
        return self._available

    async def ensure_browser(self):
        """懒初始化 Playwright Chromium 实例。"""
        if self._browser and self._browser.is_connected():
            return

        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-gpu',
                ],
            )
            logger.info("[BrowserService] Chromium browser launched")
        except Exception as e:
            logger.error(f"[BrowserService] Failed to launch browser: {e}")
            raise

    def _validate_url(self, url: str) -> str:
        """验证并规范化 URL。"""
        if not url:
            raise ValueError("URL cannot be empty")

        # 如果没有协议前缀，自动加 https://
        if not re.match(r'^https?://', url, re.IGNORECASE):
            url = f'https://{url}'

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid URL: {url}")

        return url

    async def open_page(self, url: str, timeout_ms: int = 30000) -> dict:
        """
        打开网页，返回基本信息。

        Returns:
            {"url": str, "title": str, "status": int}
        """
        url = self._validate_url(url)
        await self.ensure_browser()

        page = await self._browser.new_page()
        try:
            response = await page.goto(url, timeout=timeout_ms, wait_until='domcontentloaded')
            title = await page.title()
            status = response.status if response else 0
            final_url = page.url

            return {
                'url': final_url,
                'title': title,
                'status': status,
            }
        except Exception as e:
            error_type = type(e).__name__
            return {
                'url': url,
                'title': '',
                'status': 0,
                'error': f'{error_type}: {str(e)[:200]}',
            }
        finally:
            await page.close()

    async def screenshot(self, url: str, timeout_ms: int = 30000) -> dict:
        """
        对网页截图，返回 base64 PNG。

        Returns:
            {"url": str, "title": str, "screenshot_base64": str}
        """
        url = self._validate_url(url)
        await self.ensure_browser()

        page = await self._browser.new_page()
        try:
            await page.goto(url, timeout=timeout_ms, wait_until='domcontentloaded')
            title = await page.title()
            screenshot_bytes = await page.screenshot(type='png', full_page=False)
            screenshot_b64 = base64.b64encode(screenshot_bytes).decode('ascii')

            return {
                'url': page.url,
                'title': title,
                'screenshot_base64': screenshot_b64,
            }
        except Exception as e:
            error_type = type(e).__name__
            return {
                'url': url,
                'title': '',
                'screenshot_base64': '',
                'error': f'{error_type}: {str(e)[:200]}',
            }
        finally:
            await page.close()

    async def extract_text(self, url: str, max_chars: int = 5000, timeout_ms: int = 30000) -> dict:
        """
        提取网页文本内容 (最多 max_chars 字符)。

        Returns:
            {"url": str, "title": str, "text": str}
        """
        url = self._validate_url(url)
        await self.ensure_browser()

        page = await self._browser.new_page()
        try:
            await page.goto(url, timeout=timeout_ms, wait_until='domcontentloaded')
            title = await page.title()

            # 提取 body 文本
            text = await page.inner_text('body')
            if len(text) > max_chars:
                text = text[:max_chars] + '...[truncated]'

            return {
                'url': page.url,
                'title': title,
                'text': text,
            }
        except Exception as e:
            error_type = type(e).__name__
            return {
                'url': url,
                'title': '',
                'text': '',
                'error': f'{error_type}: {str(e)[:200]}',
            }
        finally:
            await page.close()

    async def close(self):
        """关闭浏览器实例。"""
        if self._browser:
            try:
                await self._browser.close()
            except Exception:
                pass
            self._browser = None

        if self._playwright:
            try:
                await self._playwright.stop()
            except Exception:
                pass
            self._playwright = None

        logger.info("[BrowserService] Browser closed")

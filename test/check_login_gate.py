"""登录制前端验证：无 token 打开页面 → 登录框应自动弹出；未登录发消息应被拦。"""
import os

from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(channel="chrome", headless=True)  # 复用系统 Chrome，免下载 chromium
    ctx = browser.new_context()  # 干净上下文，localStorage 无 token
    page = ctx.new_page()
    page.goto("http://localhost:8000", wait_until="networkidle")
    page.wait_for_timeout(1500)  # 留给启动逻辑执行（app.js 1116 行：无 token openModal）

    mask_shown = page.locator("#mask.show").count() > 0
    print("[1] 无 token 打开页面，登录框自动弹出:", "OK" if mask_shown else "FAIL")

    # 未登录发消息应被拦截（toast 提示请先登录，不发 SSE）
    # 先点遮罩空白处关框（口径：能关框但功能全锁），再点发送验证拦截
    page.fill("#input", "你好")
    page.mouse.click(10, 10)  # 遮罩边缘 → closeModal
    page.wait_for_timeout(500)
    mask_closed = page.locator("#mask.show").count() == 0
    print("[2] 点遮罩空白可关框:", "OK" if mask_closed else "FAIL")
    page.click("#sendBtn")
    page.wait_for_timeout(800)
    toast = page.locator(".toast:visible, .toast.show").all_text_contents()
    print("[3] 关框后发消息被拦，toast:", toast if toast else "(无 toast，FAIL)")
    mask_still = page.locator("#mask.show").count() > 0
    print("[4] 拦截后登录框重新弹出:", "OK" if mask_still else "FAIL")

    os.makedirs("test/output", exist_ok=True)
    page.screenshot(path="test/output/login_gate_check.png", full_page=True)
    print("[5] 截图已存 test/output/login_gate_check.png")
    browser.close()

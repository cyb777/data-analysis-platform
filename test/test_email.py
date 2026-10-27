"""功能测试：send_email_direct 直发冒烟（绕过 LLM，验证 SMTP 链路 + 留痕）

注意：本测试会【真实发一封邮件】并落 notification_record 留痕。
默认发到占位地址 boss@hotel.demo，可用环境变量 TEST_EMAIL 覆盖（要真发就设它）。

运行：
  D:/Anaconda3_env/envs/lang_cg/python.exe -X utf8 test/test_email.py
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env", override=False)

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"[{'OK' if ok else 'FAIL'}] {name}" + (f" -> {detail}" if detail else ""))


def main():
    from app.ai.tool.email_material_tool import send_email_direct

    to = os.getenv("TEST_EMAIL", "boss@hotel.demo")
    print(f"\n向 {to} 发送直发冒烟邮件")

    ok = send_email_direct(
        to=to,
        subject="[数据平台] 直发链路冒烟",
        content="这是一封 send_email_direct 直发冒烟邮件，收到即链路正常。",
        notification_type="report",
        trigger_source="manual",
    )
    check("邮件真实发送成功", ok is True, f"return={ok}")

    print("\n" + "=" * 60)
    print(f"通过 {len(PASS)} 项，失败 {len(FAIL)} 项")
    print("=" * 60)
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()

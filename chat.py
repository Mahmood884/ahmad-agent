#!/usr/bin/env python3
"""
Ahmad Agent Custom Chat Interface.
يربط مدخلات المستخدم بـ Hermes، وينفذ الأدوات عبر ExecutionGateway بأمان.
"""
import sys
import uuid
from pathlib import Path

from ahmad.core.runtime import AhmadRuntime
from ahmad.providers.hermes import HermesProvider
from ahmad.providers.registry import ProviderRegistry
from ahmad.memory.store import MemoryStore
from ahmad.core.types import Mode, Scope
from ahmad.config.profile import SYSTEM_PROMPT, AGENT_NAME

def main():
    # تهيئة الـ Runtime
    store = MemoryStore(Path("data/events.jsonl"))
    providers = ProviderRegistry()
    providers.register(HermesProvider(timeout=90))
    runtime = AhmadRuntime(memory=store, providers=providers)

    print(f"🤖 {AGENT_NAME} Agent Chat Interface (v0.2.0)")
    print("الأدوات المتاحة: read_file, list_dir, system_info, web_search, write_file")
    print("اكتب 'exit' أو 'quit' للخروج.\n")

    session_id = str(uuid.uuid4())[:8]
    request_counter = 0

    while True:
        try:
            user_input = input("👤 You: ").strip()
            if not user_input:
                continue
            if user_input.lower() in ['exit', 'quit', ':q']:
                print("👋 إنهاء الجلسة.")
                break

            request_counter += 1
            request_id = f"chat-{session_id}-{request_counter}"
            
            # دمج الـ System Prompt مع طلب المستخدم
            full_prompt = f"{SYSTEM_PROMPT}\n\nUser Request: {user_input}\n\nAvailable tools: read_file, list_dir, system_info, web_search, write_file. Use them if needed."

            print(f"🧠 {AGENT_NAME} يفكر...", end="\r")
            
            # إرسال الطلب للـ Provider
            outcome = runtime.handle_provider_request(
                "hermes", 
                full_prompt, 
                mode=Mode.GENERAL, 
                scope=Scope.PERSONAL,
                request_id=request_id
            )

            # طباعة رد النصي
            print(f"\n💬 {AGENT_NAME}: {outcome.response.text.strip()}")

            # تنفيذ الأدوات المقترحة وعرض النتائج
            if outcome.tool_results:
                print("\n⚙️ تنفيذ الأدوات:")
                for res in outcome.tool_results:
                    status = "✅" if res.success else "❌"
                    # تقصير المخرجات الطويلة للحفاظ على نظافة الشاشة
                    output_preview = res.output[:150] + ("..." if len(res.output) > 150 else "")
                    print(f"   {status} {res.tool}: {output_preview}")
            
            print("-" * 50)

        except KeyboardInterrupt:
            print("\n\n👋 إنهاء الجلسة.")
            break
        except Exception as e:
            print(f"\n⚠️ خطأ غير متوقع: {type(e).__name__}: {e}")

if __name__ == "__main__":
    main()

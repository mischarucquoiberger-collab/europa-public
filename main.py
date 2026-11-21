"""Chat with the model in the terminal, or make one traced call and show what PRISM received.

    python3 main.py                 # interactive chat (one session_id for the whole chat)
    python3 main.py --once "text"   # one real call, then print exactly what was sent to PRISM
    python3 main.py --once          # same, with a built-in message full of fake personal data
"""
import json
import sys

import prism
from llm import Conversation, LLMError

SYSTEM_PROMPT = "You are a concise, helpful assistant. Answer in one or two sentences."

DEMO_MESSAGE = (
    "Reply with one short sentence confirming you got this. My details (all fake): "
    "email jane.doe@example.com, phone +1 (415) 555-0132, "
    "key sk-test-9f8e7d6c5b4a39281706f5e4, order number 123456789012."
)


def show_last_sent() -> None:
    prism.flush()
    record = prism.last_sent
    if not record:
        print("\nNothing was sent to PRISM.")
        return
    print("\n=== Exactly what was sent to PRISM for this call ===")
    print("POST", record["url"])
    print("Headers: Content-Type: application/json, X-PRISMtrace-Key: (hidden)")
    print("Body:")
    print(json.dumps(json.loads(record["body"]), ensure_ascii=False, indent=2))
    print("PRISM response status:", record["status"])


def main() -> int:
    args = sys.argv[1:]
    chat = Conversation(system_prompt=SYSTEM_PROMPT)
    if args and args[0] == "--once":
        text = " ".join(args[1:]) or DEMO_MESSAGE
        try:
            reply = chat.ask(text)
        except LLMError as exc:
            print("Model call failed:", exc)
            return 1
        print("Model reply:", reply)
        show_last_sent()
        return 0

    print(f"session {chat.session_id}  (empty line or Ctrl-D to quit)")
    while True:
        try:
            text = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            break
        try:
            print("bot>", chat.ask(text))
        except LLMError as exc:
            print("Model call failed:", exc)
    prism.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())

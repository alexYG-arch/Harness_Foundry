"""TEST ONLY local protocol emitter. No Codex, sandbox enforcement or service."""
import json
import os
from pathlib import Path
import sys
import time


args = sys.argv[1:]
if args == ["exec", "--help"]:
    print("--ignore-user-config --strict-config --ephemeral --json --cd stdin")
elif args == ["sandbox", "--help"]:
    print("--permission-profile --include-managed-config --cd [COMMAND]")
elif args and args[0] == "sandbox":
    # A capability fixture only, not a sandbox emulator.
    assert args[args.index("--") + 1:] == ["/usr/bin/true"]
elif args and args[0] == "exec":
    prompt = sys.stdin.read()
    marker = Path("fixture-calls.txt")
    with marker.open("a") as stream:
        stream.write("TEST_ONLY_NO_MODEL_REQUEST\n")
    Path("fixture-input.json").write_text(json.dumps({"prompt": prompt, "argv": args,
        "forwarded_secret": "OPENAI_API_KEY" in os.environ or "CODEX_API_KEY" in os.environ}))
    mode = Path("fixture-mode").read_text() if Path("fixture-mode").exists() else "complete"
    for event in ({"type": "thread.started", "thread_id": "TEST-ONLY-CODING-PROCESS"}, {"type": "turn.started"}):
        print(json.dumps(event), flush=True)
    if mode == "timeout":
        time.sleep(10)
    if mode == "malformed":
        print("TEST ONLY invalid event")
    if mode == "truncated":
        print("X" * 10000)
    if mode == "failed":
        print(json.dumps({"type": "turn.failed", "error": {"message": "TEST ONLY"}}))
        sys.exit(1)
    print(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "id": "m1", "text": "TEST ONLY, NOT A BUILD"}}))
    print(json.dumps({"type": "turn.completed", "usage": {"input_tokens": 1, "output_tokens": 1}}))
else:
    sys.exit(2)

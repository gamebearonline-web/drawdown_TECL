import os
import subprocess
from datetime import datetime, timezone

MENTION_ID = os.getenv("MENTION_ID", "BiscuitBlueBear")

title = f"[TEST] Drawdown mention test {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
body = f"@{MENTION_ID}\n\nこれは通知テストです。"

subprocess.run(["gh", "issue", "create", "--title", title, "--body", body, "--label", "drawdown-alert"], check=True)
print("Created test issue.")

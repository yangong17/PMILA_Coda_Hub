import os

# Tests never launch a real browser.
os.environ.setdefault("LINKCHECK_NO_BROWSER", "1")

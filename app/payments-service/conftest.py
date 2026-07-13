import os

# payments-service exits on boot when REQUIRED_SETTING is unset (fault F3).
# Provide it before the app module is imported so tests can load it.
os.environ.setdefault("REQUIRED_SETTING", "test")

import os

# No test may ask Antigravity's update server; with this set the client version is never looked up.
os.environ["ANTIGRAVITY_CLIENT_VERSION"] = "1.2.3"

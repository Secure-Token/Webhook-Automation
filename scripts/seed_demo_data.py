"""Registers the sample receiver as a webhook subscriber and configures its secret.

The demo developer, API key and mock reserve are created automatically when the API starts
(SEED_DEMO=true). This script adds the subscription so the dashboard has something to show.

    python scripts/seed_demo_data.py [--webhook-host receiver]   # use 'receiver' under docker compose
"""
import argparse

import httpx

p = argparse.ArgumentParser()
p.add_argument("--api", default="http://localhost:8000")
p.add_argument("--receiver", default="http://localhost:9000")
p.add_argument("--webhook-host", default="localhost")
p.add_argument("--dev-key", default="st_dev_demo_key")
p.add_argument("--receiver-token", default="receiver_dev_token")
a = p.parse_args()

url = f"http://{a.webhook_host}:9000/receiver/webhooks/secure-tokens"
r = httpx.post(f"{a.api}/api/v1/webhooks/subscriptions", headers={"X-API-Key": a.dev_key}, json={
    "subscriber_name": "Sample receiver", "endpoint_url": url, "event_types": ["*"]})
r.raise_for_status()
sub = r.json()
httpx.put(f"{a.receiver}/receiver/config/secret", headers={"X-Receiver-Token": a.receiver_token},
          json={"subscription_id": sub["id"], "secret": sub["signing_secret"]}).raise_for_status()
print(f"Subscribed {sub['id']} -> {url} (all events). Receiver configured with the signing secret.")

import requests
import os
from dotenv import load_dotenv
import json

load_dotenv(override=True)

API_KEY = os.getenv("HELIUS_API_KEY")
HELIUS_URL = f"https://api.helius.xyz/v0/webhooks?api-key={API_KEY}"


def list_webhooks():
    response = requests.get(HELIUS_URL)
    return response.json()


def delete_webhook(webhook_id):
    delete_url = f"{HELIUS_URL}/{webhook_id}"
    response = requests.delete(delete_url)
    return response.json()


def create_webhook(webhook_url):
    payload = {
        "webhookURL": webhook_url,
        "transactionTypes": ["ANY"],
        "accountAddresses": ["39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"],
        "webhookType": "enhanced",
    }

    response = requests.post(HELIUS_URL, json=payload)
    return response.json()


if __name__ == "__main__":
    # List all webhooks
    print("Current webhooks:")
    webhooks = list_webhooks()
    print(json.dumps(webhooks, indent=2))

    # Delete existing webhooks
    for webhook in webhooks:
        print(f"Deleting webhook {webhook['webhookID']}")
        delete_webhook(webhook["webhookID"])

    # Create new webhook
    URL = "http://54.79.31.7:8005"
    webhook_response = create_webhook(f"{URL}")
    print(f"Webhook created: {webhook_response}")

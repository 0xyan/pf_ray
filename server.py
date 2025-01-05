from fastapi import FastAPI, Request
import logging
from datetime import datetime
import uvicorn
from dotenv import load_dotenv
import requests
import os
import json

# Setup logging to be more verbose
logging.basicConfig(
    level=logging.INFO,  # Changed from WARNING to INFO
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("raydium_migrations.log"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

load_dotenv(override=True)

app = FastAPI()
processed_txs = {}

RAYDIUM_MIGRATION_ACCOUNT = "39azUYFWPz3VHgKCf3VChUwbpURdCHRxjWVowf5jUJjg"


# Log all incoming requests
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(f"→ Incoming request to: {request.url.path}")
    response = await call_next(request)
    return response


@app.post("/webhook")
async def webhook(request: Request):
    try:
        data = await request.json()

        if isinstance(data, list):
            for event in data:
                await process_event(event)
        else:
            await process_event(data)

        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}")
        return {"status": "error", "message": str(e)}


async def get_token_info(mint):
    API_KEY = os.getenv("HELIUS_API_KEY")
    url = f"https://mainnet.helius-rpc.com/?api-key={API_KEY}"

    payload = {
        "jsonrpc": "2.0",
        "id": "helius-test",
        "method": "getAsset",
        "params": {"id": mint},
    }

    try:
        response = requests.post(
            url, headers={"Content-Type": "application/json"}, json=payload
        )
        data = response.json()

        if "result" in data and "content" in data["result"]:
            metadata = data["result"]["content"].get("metadata", {})
            return {
                "name": metadata.get("name", "Unknown"),
                "symbol": metadata.get("symbol", "Unknown"),
            }
        return {"name": "Unknown", "symbol": "Unknown"}
    except Exception as e:
        logger.error(f"Error fetching token info: {e}")
        return {"name": "Unknown", "symbol": "Unknown"}


async def get_token_holders(mint):
    API_KEY = os.getenv("HELIUS_API_KEY")
    url = f"https://mainnet.helius-rpc.com/?api-key={API_KEY}"

    payload = {
        "jsonrpc": "2.0",
        "id": "helius-test",
        "method": "getTokenAccounts",
        "params": {"mint": mint, "showZeroBalance": False},
    }

    try:
        response = requests.post(
            url, headers={"Content-Type": "application/json"}, json=payload
        )
        data = response.json()

        if "result" in data and "token_accounts" in data["result"]:
            # Sort holders by amount
            holders = data["result"]["token_accounts"]
            holders.sort(key=lambda x: x.get("amount", 0), reverse=True)

            # Get top 5 holders
            top_holders = holders[:5]
            return [{"owner": h["owner"], "amount": h["amount"]} for h in top_holders]
        return []
    except Exception as e:
        logger.error(f"Error fetching token holders: {e}")
        return []


async def process_event(event):
    try:
        tx_signature = event.get("signature")
        if tx_signature in processed_txs:
            return

        processed_txs[tx_signature] = datetime.now()

        token_transfers = event.get("tokenTransfers", [])
        if not token_transfers:
            return

        for transfer in token_transfers:
            to_address = transfer.get("toUserAccount")
            amount = float(transfer.get("tokenAmount", 0))

            if to_address != RAYDIUM_MIGRATION_ACCOUNT or int(amount) == 4042:
                continue

            mint = transfer.get("mint")
            token_info = await get_token_info(mint)
            holders = await get_token_holders(mint)

            # Format holders info
            holders_text = "\n".join(
                [
                    f"👉 {h['owner'][:4]}...{h['owner'][-4:]}: {h['amount']:,.0f}"
                    for h in holders
                ]
            )

            transfer_info = (
                f"\n{'='*50}\n"
                f"NEW TOKEN MIGRATION TO RAYDIUM DETECTED!\n"
                f"Token: {token_info['name']} ({token_info['symbol']})\n"
                f"Token Address: {mint}\n"
                f"Transaction: {tx_signature}\n"
                f"\nTop 5 Holders:\n{holders_text}\n"
                f"Timestamp: {datetime.now()}\n"
                f"{'='*50}"
            )

            logger.warning(transfer_info)

            message = (
                f"🚀 <b>New Token Migration to Raydium</b>\n\n"
                f"Token: {token_info['name']} ({token_info['symbol']})\n"
                f"Token: <code>{mint}</code>\n"
                f"\n<b>Top 5 Holders:</b>\n{holders_text}\n\n"
                f"<a href='https://solscan.io/tx/{tx_signature}'>View Transaction</a>"
            )

            send_telegram_message(message)

    except Exception as e:
        logger.error(f"Error in process_event: {str(e)}", exc_info=True)


@app.get("/")
async def health_check():
    logger.info("Health check endpoint hit")
    return {"status": "healthy"}


def send_telegram_message(message):
    token_tg = os.getenv("TELEGRAM_TOKEN")
    id_tg = os.getenv("TELEGRAM_ID")

    url = f"https://api.telegram.org/bot{token_tg}/sendMessage"
    params = {
        "chat_id": id_tg,
        "text": message,
        "parse_mode": "HTML",
    }

    try:
        response = requests.post(url, params=params)
        return response.json()
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")


@app.get("/test")
async def test():
    return {"message": "Test endpoint working"}


if __name__ == "__main__":
    logger.info("Server starting on port 1001...")
    logger.info(
        f"Monitoring migrations to Raydium account: {RAYDIUM_MIGRATION_ACCOUNT}"
    )
    uvicorn.run(app, host="0.0.0.0", port=1001)

from fastapi import FastAPI, Request
import logging
from datetime import datetime, timezone
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


@app.post("/")
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


async def get_first_transaction(mint):
    API_KEY = os.getenv("HELIUS_API_KEY")
    url = f"https://mainnet.helius-rpc.com/?api-key={API_KEY}"

    payload = {
        "jsonrpc": "2.0",
        "id": "helius-test",
        "method": "getSignaturesForAddress",
        "params": [mint],  # Simplified params to match the example
    }

    try:
        response = requests.post(
            url, headers={"Content-Type": "application/json"}, json=payload
        )
        data = response.json()

        if (
            "result" in data
            and isinstance(data["result"], list)
            and len(data["result"]) > 0
        ):

            first_tx = data["result"][-1]  # Get the last (oldest) transaction
            return {
                "signature": first_tx.get("signature"),
                "slot": first_tx.get("slot"),
                "blockTime": first_tx.get("blockTime"),
            }
        return None
    except Exception as e:
        logger.error(f"Error fetching first transaction: {e}")
        return None


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
            first_tx = await get_first_transaction(mint)

            return {
                "name": metadata.get("name", "Unknown"),
                "symbol": metadata.get("symbol", "Unknown"),
                "first_tx": first_tx,
            }
        return {"name": "Unknown", "symbol": "Unknown", "first_tx": None}
    except Exception as e:
        logger.error(f"Error fetching token info: {e}")
        return {"name": "Unknown", "symbol": "Unknown", "first_tx": None}


def format_time_difference(start_time, end_time):
    if not start_time:
        return "Unknown"

    diff = end_time - start_time
    days = diff.days
    hours = diff.seconds // 3600
    minutes = (diff.seconds % 3600) // 60

    if days > 0:
        return f"{days}d {hours}h {minutes}m"
    elif hours > 0:
        return f"{hours}h {minutes}m"
    else:
        return f"{minutes}m"


async def get_token_holders(mint):
    API_KEY = os.getenv("HELIUS_API_KEY")
    url = f"https://mainnet.helius-rpc.com/?api-key={API_KEY}"

    payload = {
        "jsonrpc": "2.0",
        "id": "helius-test",
        "method": "getTokenAccounts",
        "params": {"mint": mint, "options": {"showZeroBalance": False}},
    }

    try:
        response = requests.post(
            url, headers={"Content-Type": "application/json"}, json=payload
        )
        data = response.json()

        if "result" in data and "token_accounts" in data["result"]:
            holders = data["result"]["token_accounts"]
            total_holders = len(holders)

            # Sort and get top 5
            holders.sort(key=lambda x: x.get("amount", 0), reverse=True)
            top_holders = holders[:5]

            return {
                "total_holders": total_holders,
                "top_holders": [
                    {"owner": h["owner"], "amount": h["amount"]} for h in top_holders
                ],
            }
        return {"total_holders": 0, "top_holders": []}
    except Exception as e:
        logger.error(f"Error fetching token holders: {e}")
        return {"total_holders": 0, "top_holders": []}


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
            holders_info = await get_token_holders(mint)

            # Calculate time to bond using blockTime from first_tx
            current_time = datetime.now(timezone.utc)
            first_tx_time = None
            if token_info["first_tx"] and token_info["first_tx"]["blockTime"]:
                first_tx_time = datetime.fromtimestamp(
                    token_info["first_tx"]["blockTime"], tz=timezone.utc
                )
            time_to_bond = format_time_difference(first_tx_time, current_time)

            TOTAL_SUPPLY = 1_000_000_000_000_000
            LP_AMOUNT = 206_900_000_000_000

            holders_text = []
            for idx, holder in enumerate(holders_info["top_holders"], 1):
                amount = float(holder["amount"])
                percentage = (amount / TOTAL_SUPPLY) * 100
                address = holder["owner"]

                if abs(amount - LP_AMOUNT) < 1000000:
                    prefix = "🔄"
                else:
                    prefix = f"{idx}."

                holder_line = (
                    f"{prefix} <a href='https://solscan.io/account/{address}'>"
                    f"{address[:4]}...{address[-4:]}</a>: {percentage:.2f}%"
                )
                holders_text.append(holder_line)

            holders_formatted = "\n".join(holders_text)

            # Create PumpFun URL
            pumpfun_url = f"https://pump.fun/coin/{mint}"

            message = (
                f"PF → Raydium ${token_info['symbol']}\n"
                f"<a href='{pumpfun_url}'>{token_info['name']}</a>\n\n"
                f"CA: <a href='https://solscan.io/token/{mint}'>{mint}</a>\n"
                f"To bond: {time_to_bond}\n"
                f"Holders: {holders_info['total_holders']:,}\n\n"
                f"<b>Top 5 holders:</b>\n{holders_formatted}\n"
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
    logger.info("Server starting on port 8005...")
    logger.info(
        f"Monitoring migrations to Raydium account: {RAYDIUM_MIGRATION_ACCOUNT}"
    )
    uvicorn.run(app, host="0.0.0.0", port=8005)

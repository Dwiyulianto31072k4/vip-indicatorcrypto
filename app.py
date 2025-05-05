import streamlit as st
import asyncio
import threading
import time
import os
import re
from datetime import datetime
import logging
from telethon import TelegramClient, events
import aiohttp

# Streamlit page configuration
st.set_page_config(
    page_title="Telegram Channel Forwarder",
    page_icon="📱",
    layout="wide"
)

# Logging configuration
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("telegram_forwarder.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Credentials and fixed configuration
API_ID = 28690093
API_HASH = "aa512841e37c5ccb5a8ac494395bb373"
PHONE_NUMBER = "+6285161054271"
SOURCE_CHANNEL_ID = -1002051092635
TARGET_CHANNEL_ID = -1002535586416

# Files to store verification code
VERIFICATION_CODE_FILE = "verification_code.txt"
LOG_FILE = "bot_logs.txt"

# Session state initialization
if 'running' not in st.session_state:
    st.session_state['running'] = False
if 'total_forwarded' not in st.session_state:
    st.session_state['total_forwarded'] = 0
if 'log_messages' not in st.session_state:
    st.session_state['log_messages'] = []

# Function to save log to file
def write_log(message, is_error=False):
    try:
        with open(LOG_FILE, "a") as f:
            timestamp = datetime.now().strftime("%H:%M:%S")
            f.write(f"{timestamp} - {'ERROR' if is_error else 'INFO'} - {message}\n")
    except Exception as e:
        logger.error(f"Failed to write log to file: {str(e)}")

# Function to read logs from file
def read_logs():
    logs = []
    try:
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, "r") as f:
                for line in f.readlines():
                    parts = line.strip().split(" - ", 2)
                    if len(parts) == 3:
                        timestamp, level, message = parts
                        logs.append({
                            'time': timestamp,
                            'message': message,
                            'error': level == 'ERROR'
                        })
    except Exception as e:
        logger.error(f"Failed to read logs from file: {str(e)}")
    return logs

# Function to get verification code
def code_callback():
    logger.info("Waiting for verification code...")
    # Remove verification code file if exists
    if os.path.exists(VERIFICATION_CODE_FILE):
        os.remove(VERIFICATION_CODE_FILE)
    
    # Write message to log
    write_log("Bot needs verification code. Please enter the verification code in Telegram.")
    
    # Wait until verification code is entered
    while not os.path.exists(VERIFICATION_CODE_FILE):
        time.sleep(1)
    
    # Read verification code
    with open(VERIFICATION_CODE_FILE, "r") as f:
        code = f.read().strip()
    
    # Remove file after reading
    os.remove(VERIFICATION_CODE_FILE)
    
    write_log(f"Verification code received: {code}")
    return code

# Function to calculate percentage change
def calculate_percentage_change(entry_price, target_price):
    try:
        entry = float(entry_price)
        target = float(target_price)
        
        # Validation to prevent division by zero or too small values
        if entry < 0.0001:
            logger.warning(f"Entry price too small: {entry}, using default")
            return 0.0
            
        percentage = ((target - entry) / entry) * 100
        
        # Limit maximum percentage to reasonable values
        if abs(percentage) > 1000:
            logger.warning(f"Percentage too large: {percentage}, limited to ±1000%")
            percentage = 1000.0 if percentage > 0 else -1000.0
            
        return percentage
    except (ValueError, ZeroDivisionError):
        logger.error(f"Error calculating percentage: {entry_price}, {target_price}")
        return 0.0

# Function to get current cryptocurrency price
async def get_current_price(coin_symbol):
    try:
        # Remove USDT suffix if present
        base_symbol = coin_symbol.replace('USDT', '')
        
        # Try Binance API first
        binance_url = f"https://api.binance.com/api/v3/ticker/price?symbol={coin_symbol}"
        async with aiohttp.ClientSession() as session:
            async with session.get(binance_url) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'price' in data:
                        return float(data['price'])
                
        # Fallback to CoinGecko
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={base_symbol.lower()}&vs_currencies=usd"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if base_symbol.lower() in data:
                        return data[base_symbol.lower()]['usd']
                
        return None
    except Exception as e:
        logger.error(f"Error getting price: {str(e)}")
        return None

# Function to create percentage change table
def create_percentage_table(coin_name, entry_price, targets, stop_losses):
    try:
        # Table header
        table = "📝 Price Change Percentage Calculation\n\n"
        table += "Level         Price       % Change from Entry\n"
        table += "------------------------------------------------\n"
        
        # Add targets
        for i, target in enumerate(targets, 1):
            percentage = calculate_percentage_change(entry_price, target)
            table += f"Target {i}      {target}      +{percentage:.2f}%\n"
        
        # Add stop losses
        for i, sl in enumerate(stop_losses, 1):
            percentage = calculate_percentage_change(entry_price, sl)
            # Use actual percentage value (may be negative)
            sign = "+" if percentage >= 0 else ""
            table += f"Stop Loss {i}    {sl}      {sign}{percentage:.2f}%\n"
        
        return table
    except Exception as e:
        logger.error(f"Error creating percentage table: {str(e)}")
        return "Error creating percentage table."

# IMPROVED: Function to detect message type with better pattern matching
def detect_message_type(text):
    # Check for Daily Recap
    if re.search(r'Daily\s+Results|每日結算統計|Results', text, re.IGNORECASE):
        return "DAILY_RECAP"
    
    # Check for Target Hit - IMPROVED to catch more patterns including checkmarks
    if (re.search(r'Hitted\s+target|Reached\s+target', text, re.IGNORECASE) or 
        re.search(r'Target\s+\d+.*?[✅🟢]', text, re.IGNORECASE) or
        re.search(r'Target\s+\d+\s*[:]\s*\d+.*?[✅🟢]', text, re.IGNORECASE)):
        return "TARGET_HIT"
    
    # Check for Stop Loss Hit - IMPROVED to catch more patterns
    if (re.search(r'Hitted\s+stop\s+loss|Stop\s+loss\s+triggered', text, re.IGNORECASE) or
        re.search(r'Stop\s+loss\s+\d+.*?[🛑🔴]', text, re.IGNORECASE) or
        re.search(r'Stop\s+loss\s+\d+\s*[:]\s*\d+.*?[🛑🔴]', text, re.IGNORECASE)):
        return "STOP_LOSS_HIT"
    
    # Check if it's a very short message with just coin name and target/price
    # This is a specific case for short messages like in your example
    if len(text.strip().split('\n')) <= 2 and ('USDT' in text or 'BTC' in text):
        # If very short message contains a checkmark, it's likely a target hit
        if '✅' in text or '🟢' in text:
            return "TARGET_HIT"
        # If very short message contains a stop symbol, it's likely a stop loss
        elif '🛑' in text or '🔴' in text:
            return "STOP_LOSS_HIT"
    
    # If no specific type is detected, assume it's a new signal
    return "NEW_SIGNAL"

# Function to extract data from message
def extract_trading_data(message_text):
    try:
        lines = message_text.split('\n')
        
        # Variables to store extracted data
        coin_name = None
        entry_price = None
        targets = []
        stop_losses = []
        
        # Pattern to extract coin name (usually in first line)
        for line in lines[:3]:  # Check first 3 lines
            line = line.strip()
            if not line:
                continue
                
            # Try various patterns for coin name
            coin_patterns = [
                r'^([A-Za-z0-9]+)[^A-Za-z0-9]',  # Coin at start of line
                r'([A-Za-z0-9]+USDT)',  # Format like BTCUSDT
                r'([A-Za-z0-9]+) NEW'   # Format like "COIN NEW"
            ]
            
            for pattern in coin_patterns:
                coin_match = re.search(pattern, line)
                if coin_match:
                    coin_name = coin_match.group(1)
                    break
            
            if coin_name:
                break
        
        # Iterate per line to extract data
        for line in lines:
            line = line.strip()
            
            # Extract entry price
            entry_match = re.search(r'Entry:?\s*([0-9.]+)', line)
            if entry_match:
                entry_price = entry_match.group(1)
            
            # Extract target prices
            target_match = re.search(r'Target\s+(\d+):?\s*([0-9.]+)', line)
            if target_match:
                target_num = int(target_match.group(1))
                target_price = target_match.group(2)
                
                # Make sure list is long enough
                while len(targets) < target_num:
                    targets.append(None)
                
                # Save target at correct position (index starts at 0)
                targets[target_num-1] = target_price
            
            # Extract stop loss
            sl_match = re.search(r'Stop\s+loss\s+(\d+):?\s*([0-9.]+)', line, re.IGNORECASE)
            if sl_match:
                sl_num = int(sl_match.group(1))
                sl_price = sl_match.group(2)
                
                # Make sure list is long enough
                while len(stop_losses) < sl_num:
                    stop_losses.append(None)
                
                # Save stop loss at correct position
                stop_losses[sl_num-1] = sl_price
        
        # Remove None values from lists
        targets = [t for t in targets if t is not None]
        stop_losses = [sl for sl in stop_losses if sl is not None]
        
        return {
            'coin_name': coin_name,
            'entry_price': entry_price,
            'targets': targets,
            'stop_losses': stop_losses
        }
    except Exception as e:
        logger.error(f"Error extracting trading data: {str(e)}")
        return {
            'coin_name': None,
            'entry_price': None,
            'targets': [],
            'stop_losses': []
        }

# Function to extract data from target hit/stop loss message
def extract_hit_data(message_text):
    data = {'coin': None, 'level': None, 'price': None}
    
    # Find coin name
    coin_match = re.search(r'([A-Za-z0-9]+)(USDT|BTC|ETH|BNB)', message_text)
    if coin_match:
        data['coin'] = coin_match.group(0)
    
    # Find target level and price
    target_match = None
    if "target" in message_text.lower():
        target_match = re.search(r'Target\s+(\d+)[:\s]+([0-9.]+)', message_text, re.IGNORECASE)
    
    # If specific format from example images
    if not target_match and '✅' in message_text:
        target_match = re.search(r'Target\s+(\d+):\s*([0-9.]+)\s*[✅]', message_text, re.IGNORECASE)
    
    if target_match:
        data['level'] = f"Target {target_match.group(1)}"
        data['price'] = target_match.group(2)
    
    # Find stop loss level and price
    sl_match = None
    if "stop loss" in message_text.lower():
        sl_match = re.search(r'Stop\s+loss\s+(\d+)[:\s]+([0-9.]+)', message_text, re.IGNORECASE)
    
    # If specific format with red mark
    if not sl_match and ('🛑' in message_text or '🔴' in message_text):
        sl_match = re.search(r'Stop\s+loss\s+(\d+):\s*([0-9.]+)\s*[🛑🔴]', message_text, re.IGNORECASE)
    
    if sl_match:
        data['level'] = f"Stop Loss {sl_match.group(1)}"
        data['price'] = sl_match.group(2)
    
    return data

# Function to extract data from daily recap
def extract_daily_recap_data(text):
    data = {
        'date': None,
        'hitted_targets': [],
        'running': [],
        'stop_losses': [],
        'total_signals': 0,
        'hitted_take_profits': 0,
        'hitted_stop_losses': 0
    }
    
    # Extract date
    date_match = re.search(r'(\d{2}/\d{2}-\d{2}/\d{2})', text)
    if date_match:
        data['date'] = date_match.group(1)
    
    # Extract targets hit
    for i in range(1, 5):  # Target 1-4
        target_match = re.search(rf'Hitted\s+target\s+{i}:\s*(.*?)(?:\n|$)', text)
        if target_match:
            coins = [coin.strip() for coin in target_match.group(1).split(',')]
            data['hitted_targets'].append({'level': i, 'coins': coins})
    
    # Extract running signals
    running_match = re.search(r'Running:\s*(.*?)(?:\n|$)', text)
    if running_match:
        data['running'] = [coin.strip() for coin in running_match.group(1).split(',')]
    
    # Extract stop loss
    sl_match = re.search(r'Hitted\s+stop\s+loss:\s*(.*?)(?:\n|$)', text)
    if sl_match:
        data['stop_losses'] = [coin.strip() for coin in sl_match.group(1).split(',')]
    
    # Extract statistics
    total_match = re.search(r'Total\s+Signals:\s*(\d+)', text)
    if total_match:
        data['total_signals'] = int(total_match.group(1))
    
    tp_match = re.search(r'Hitted\s+Take-Profits:\s*(\d+)', text)
    if tp_match:
        data['hitted_take_profits'] = int(tp_match.group(1))
    
    sl_count_match = re.search(r'Hitted\s+Stop-Losses:\s*(\d+)', text)
    if sl_count_match:
        data['hitted_stop_losses'] = int(sl_count_match.group(1))
    
    return data

# Function to create win rate table
def create_win_rate_table(recap_data):
    total_signals = recap_data['total_signals']
    take_profits = recap_data['hitted_take_profits']
    stop_losses = recap_data['hitted_stop_losses']
    
    if total_signals == 0:
        win_rate = 0
    else:
        win_rate = (take_profits / total_signals) * 100
    
    table = "📊 Trading Performance Analysis 📊\n\n"
    table += "Metric                  Value       Percentage\n"
    table += "--------------------------------------------\n"
    table += f"Win Rate               {take_profits}/{total_signals}     {win_rate:.2f}%\n"
    
    if take_profits + stop_losses > 0:
        profit_ratio = (take_profits / (take_profits + stop_losses)) * 100
        table += f"Profit/Loss Ratio      {take_profits}/{stop_losses}     {profit_ratio:.2f}%\n"
    
    table += f"Running Signals        {len(recap_data['running'])}         {(len(recap_data['running'])/total_signals*100):.2f}%\n"
    
    return table

# Function to run Telethon client
async def run_client():
    try:
        # Create client
        client = TelegramClient('telegram_forwarder_session', API_ID, API_HASH)
        
        # Event handler for new messages
        @client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def handler(event):
            try:
                message = event.message
                
                # If no text, just send media
                if not message.text:
                    if message.media:
                        await client.send_file(
                            TARGET_CHANNEL_ID, 
                            message.media,
                            caption=f"🚀 VIP SIGNAL 🚀\n\nhttps://t.me/+4xrX56bvDhRkODA1"
                        )
                    return
                
                # Log incoming message for debugging
                logger.info(f"Received message: {message.text[:100]}...")
                
                # Detect message type
                message_type = detect_message_type(message.text)
                logger.info(f"Detected message type: {message_type}")
                
                if message_type == "DAILY_RECAP":
                    # Process daily recap
                    recap_data = extract_daily_recap_data(message.text)
                    
                    # Create text with win rate
                    custom_text = f"📅 DAILY RECAP: {recap_data['date'] if recap_data['date'] else 'Today'} 📅\n\n"
                    custom_text += message.text + "\n\n"
                    custom_text += create_win_rate_table(recap_data)
                    custom_text += "\n\nhttps://t.me/+4xrX56bvDhRkODA1"
                    
                    # Send message
                    await client.send_message(TARGET_CHANNEL_ID, custom_text)
                    
                elif message_type == "TARGET_HIT":
                    # Special format for target hit
                    hit_data = extract_hit_data(message.text)
                    
                    if hit_data['coin'] and hit_data['level'] and hit_data['price']:
                        # Use "SIGNAL UPDATE" format for target hit
                        custom_text = f"✅ SIGNAL UPDATE: {hit_data['coin']} ✅\n\n"
                        custom_text += f"🎯 {hit_data['level']} ({hit_data['price']}) HIT!\n\n"
                    else:
                        # If extraction fails, send original message with standard header
                        custom_text = f"✅ SIGNAL UPDATE ✅\n\n"
                        custom_text += message.text + "\n\n"
                    
                    custom_text += "https://t.me/+4xrX56bvDhRkODA1"
                    
                    await client.send_message(TARGET_CHANNEL_ID, custom_text)
                    
                elif message_type == "STOP_LOSS_HIT":
                    # Special format for stop loss hit
                    hit_data = extract_hit_data(message.text)
                    
                    if hit_data['coin'] and hit_data['level'] and hit_data['price']:
                        # Use "SIGNAL UPDATE" format for stop loss hit
                        custom_text = f"🔴 SIGNAL UPDATE: {hit_data['coin']} 🔴\n\n"
                        custom_text += f"⚠️ {hit_data['level']} ({hit_data['price']}) TRIGGERED!\n\n"
                    else:
                        # If extraction fails, send original message with standard header
                        custom_text = f"🔴 SIGNAL UPDATE 🔴\n\n"
                        custom_text += message.text + "\n\n"
                    
                    custom_text += "https://t.me/+4xrX56bvDhRkODA1"
                    
                    await client.send_message(TARGET_CHANNEL_ID, custom_text)
                    
                else:  # NEW_SIGNAL
                    # Extract trading data
                    trading_data = extract_trading_data(message.text)
                    coin_name = trading_data['coin_name']
                    entry_price = trading_data['entry_price']
                    targets = trading_data['targets']
                    stop_losses = trading_data['stop_losses']
                    
                    # If no entry price but have coin name, try to get current price
                    if coin_name and not entry_price and (targets or stop_losses):
                        current_price = await get_current_price(coin_name)
                        if current_price:
                            entry_price = str(current_price)
                            logger.info(f"Using current price for {coin_name}: {entry_price}")
                    
                    # Create custom message
                    if coin_name and entry_price and (targets or stop_losses):
                        # Header
                        custom_text = f"🚀 VIP SIGNAL: {coin_name} 🚀\n\n"
                        
                        # Add original message
                        custom_text += message.text + "\n\n"
                        
                        # Add percentage table if data is sufficient
                        if targets or stop_losses:
                            custom_text += create_percentage_table(coin_name, entry_price, targets, stop_losses)
                        
                        # Footer
                        custom_text += "\n\nhttps://t.me/+4xrX56bvDhRkODA1"
                    else:
                        # Default format if data is incomplete
                        custom_text = f"🚀 VIP SIGNAL 🚀\n\n{message.text}\n\nhttps://t.me/+4xrX56bvDhRkODA1"
                    
                    # Send message to target channel
                    await client.send_message(TARGET_CHANNEL_ID, custom_text)
                
                # Log message info
                message_preview = message.text[:50] + "..." if message.text and len(message.text) > 50 else "Media or message without text"
                log_msg = f"Message successfully forwarded: {message_preview}"
                logger.info(log_msg)
                write_log(log_msg)
                    
            except Exception as e:
                error_msg = f"Error sending message: {str(e)}"
                logger.error(error_msg)
                write_log(error_msg, True)
        
        # Run client
        write_log("Starting Telegram client...")
        await client.start(PHONE_NUMBER, code_callback=code_callback)
        
        log_msg = f"Bot successfully activated. Monitoring channel: {SOURCE_CHANNEL_ID}"
        logger.info(log_msg)
        write_log(log_msg)
        
        # Run until disconnected
        await client.run_until_disconnected()
        
    except Exception as e:
        error_msg = f"Error running client: {str(e)}"
        logger.error(error_msg)
        write_log(error_msg, True)

# Function to run client in separate thread
def start_client_thread():
    try:
        write_log("Starting client in separate thread...")
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_client())
    except Exception as e:
        error_msg = f"Error in thread: {str(e)}"
        logger.error(error_msg)
        write_log(error_msg, True)

# Function to save verification code
def save_verification_code():
    if st.session_state.code_input:
        try:
            with open(VERIFICATION_CODE_FILE, "w") as f:
                f.write(st.session_state.code_input)
            st.success("Verification code sent!")
        except Exception as e:
            st.error(f"Failed to save verification code: {str(e)}")

# Streamlit UI
st.title("Telegram Channel Forwarder")
st.markdown("Application to forward messages from source channel to your target channel.")

# Column for verification code
if st.session_state['running']:
    st.text_input("Enter Verification Code from Telegram (if requested):", 
                  key="code_input", 
                  on_change=save_verification_code)

# Display status and statistics
st.subheader("Status & Statistics")
col1, col2 = st.columns(2)
with col1:
    status = "🟢 **Running**" if st.session_state['running'] else "🔴 **Stopped**"
    st.markdown(f"**Bot Status:** {status}")
with col2:
    # Update total forwarded from log
    forwarded_count = 0
    for log in read_logs():
        if "Message successfully forwarded" in log['message']:
            forwarded_count += 1
    st.session_state['total_forwarded'] = forwarded_count
    st.markdown(f"**Total Messages Sent:** {st.session_state['total_forwarded']}")

# Start/stop buttons
col1, col2 = st.columns(2)
with col1:
    if not st.session_state['running']:
        if st.button("Start Forwarding", use_container_width=True):
            # Create log file if it doesn't exist
            if not os.path.exists(LOG_FILE):
                with open(LOG_FILE, "w") as f:
                    f.write("")
            
            # Run client in separate thread
            thread = threading.Thread(target=start_client_thread, daemon=True)
            thread.start()
            
            st.session_state['running'] = True
            write_log("Bot starting...")
            st.rerun()
with col2:
    if st.session_state['running']:
        if st.button("Stop Forwarding", use_container_width=True):
            # Stop client - no direct way to stop thread
            # Just mark as not running
            st.session_state['running'] = False
            write_log("Bot stopped!")
            st.rerun()

# Display activity log
st.subheader("Activity Log")
log_container = st.container()
with log_container:
    # Read logs from file
    logs = read_logs()
    # Display last 10 logs
    if logs:
        for log in reversed(logs[-10:]):
            timestamp = log.get('time', '')
            message = log.get('message', '')
            is_error = log.get('error', False)
            
            if is_error:
                st.error(f"{timestamp} - {message}")
            else:
                st.info(f"{timestamp} - {message}")

# Add usage instructions
with st.expander("How to Use"):
    st.markdown("""
    ### How to Use This Application:
    
    1. **Running the Bot**:
       - Click "Start Forwarding" to begin
       - First time, you may be asked to enter a verification code
       - Click "Stop Forwarding" to stop the bot
    
    2. **Verification Code**:
       - When first run, Telegram will send a verification code to your phone number
       - Enter that code in the "Verification Code" field that appears
    
    3. **View Logs**:
       - Check the "Activity Log" section to monitor message forwarding process
       - Logs are also saved in the `telegram_forwarder.log` file
    
    4. **Message Formats**:
       - New trading signals: "VIP SIGNAL" with price percentage change calculation
       - Target hit updates: "SIGNAL UPDATE" with simple format
       - Stop loss triggered updates: "SIGNAL UPDATE" with simple format
       - Daily recaps: Added win rate calculation and statistics
    
    5. **Troubleshooting**:
       - If error occurs, restart the application
       - Make sure your account has access to both channels
    """)

# Auto-refresh page every 5 seconds
time.sleep(5)
st.rerun()

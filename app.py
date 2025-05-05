import streamlit as st
import asyncio
import threading
import time
import os
import re
import shutil
from datetime import datetime
import logging
from telethon import TelegramClient, events
from telethon.errors import FloodWaitError, SessionPasswordNeededError
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
TARGET_CHANNEL_ID = -4634673046

# Files to store verification code
VERIFICATION_CODE_FILE = "verification_code.txt"
LOG_FILE = "bot_logs.txt"

# Set restart interval (in seconds)
RESTART_INTERVAL = 12 * 60 * 60  # 12 hours

# Thread-safe Bot State class
class BotState:
    def __init__(self):
        self._running = False
        self._restart_required = False
        self._total_forwarded = 0
        self._lock = threading.Lock()
    
    @property
    def running(self):
        with self._lock:
            return self._running
    
    @running.setter
    def running(self, value):
        with self._lock:
            self._running = value
    
    @property
    def restart_required(self):
        with self._lock:
            return self._restart_required
    
    @restart_required.setter
    def restart_required(self, value):
        with self._lock:
            self._restart_required = value
    
    @property
    def total_forwarded(self):
        with self._lock:
            return self._total_forwarded
    
    @total_forwarded.setter
    def total_forwarded(self, value):
        with self._lock:
            self._total_forwarded = value
    
    def increment_forwarded(self):
        with self._lock:
            self._total_forwarded += 1

# Create global instance
bot_state = BotState()

# Initialize session state
def initialize_session_state():
    if 'running' not in st.session_state:
        st.session_state['running'] = False
    if 'total_forwarded' not in st.session_state:
        st.session_state['total_forwarded'] = 0
    if 'log_messages' not in st.session_state:
        st.session_state['log_messages'] = []
    if 'restart_required' not in st.session_state:
        st.session_state['restart_required'] = False
    
    # Sync bot_state with session_state if needed
    bot_state.running = st.session_state['running']
    bot_state.restart_required = st.session_state['restart_required']
    bot_state.total_forwarded = st.session_state['total_forwarded']

# Call this at the start
initialize_session_state()

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

# Function for scheduled restart
async def scheduled_restart(restart_interval=RESTART_INTERVAL):
    """Function to schedule automatic restart"""
    try:
        # Wait for restart interval
        await asyncio.sleep(restart_interval)
        
        # Log scheduled restart
        logger.info(f"Performing scheduled restart after {restart_interval//3600} hours of operation")
        write_log(f"Scheduled restart after {restart_interval//3600} hours of operation")
        
        # Set flag for restart
        bot_state.restart_required = True
    except Exception as e:
        logger.error(f"Error in scheduled restart: {str(e)}")

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

# Updated function to extract data from target hit/stop loss message with multiple targets
def extract_hit_data(message_text):
    data = {
        'coin': None,
        'levels': [],  # Changed from single level to list of levels
        'prices': []   # Changed from single price to list of prices
    }
    
    # Find coin name
    coin_match = re.search(r'([A-Za-z0-9]+)(USDT|BTC|ETH|BNB)', message_text)
    if coin_match:
        data['coin'] = coin_match.group(0)
    
    # Find all targets in the message
    # Use findall instead of search to find all matches
    all_targets = re.findall(r'Target\s+(\d+)[:\s]+([0-9.]+)\s*[✅🟢]', message_text, re.IGNORECASE)
    
    for target_num, price in all_targets:
        data['levels'].append(f"Target {target_num}")
        data['prices'].append(price)
    
    # Find all stop losses in the message
    all_stops = re.findall(r'Stop\s+loss\s+(\d+)[:\s]+([0-9.]+)\s*[🛑🔴]', message_text, re.IGNORECASE)
    
    for stop_num, price in all_stops:
        data['levels'].append(f"Stop Loss {stop_num}")
        data['prices'].append(price)
    
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

# Improved function to run Telethon client with better error handling
async def run_client():
    try:
        # Handle session file
        session_name = 'telegram_forwarder_session'
        session_file = f'{session_name}.session'
        
        # Check if session file exists and might be corrupted
        if os.path.exists(session_file):
            try:
                # Create backup before potentially deleting
                backup_path = f"{session_file}.bak.{int(time.time())}"
                shutil.copy2(session_file, backup_path)
                logger.info(f"Created session backup at {backup_path}")
            except Exception as e:
                logger.error(f"Failed to backup session: {str(e)}")
        
        # Create message queue for rate limiting
        message_queue = asyncio.Queue()
        
        # Create client with better settings
        client = TelegramClient(
            session_name, 
            API_ID, 
            API_HASH,
            connection_retries=10,
            retry_delay=5,
            auto_reconnect=True
        )
        
        # Message sender task to handle rate limits
        async def message_sender():
            while True:
                try:
                    task = await message_queue.get()
                    target = task.get('target')
                    message = task.get('message')
                    media = task.get('media')
                    
                    try:
                        if media:
                            await client.send_file(target, media, caption=message)
                        else:
                            await client.send_message(target, message)
                        
                        # Log successful send
                        message_preview = message[:50] + "..." if message and len(message) > 50 else "Media or message without text"
                        log_msg = f"Message successfully forwarded: {message_preview}"
                        logger.info(log_msg)
                        write_log(log_msg)
                        
                        # Increment forwarded count
                        bot_state.increment_forwarded()
                        
                    except FloodWaitError as e:
                        # Handle rate limiting
                        wait_time = e.seconds
                        logger.warning(f"Rate limit hit. Waiting for {wait_time} seconds")
                        write_log(f"Rate limit hit. Waiting for {wait_time} seconds")
                        await asyncio.sleep(wait_time)
                        # Re-queue the message
                        await message_queue.put(task)
                    except Exception as e:
                        logger.error(f"Error sending message: {str(e)}")
                        write_log(f"Error sending message: {str(e)}", True)
                    
                    # Add delay between messages to prevent rate limiting
                    await asyncio.sleep(1)
                    message_queue.task_done()
                except Exception as e:
                    logger.error(f"Error in message sender: {str(e)}")
                    await asyncio.sleep(5)  # Wait and continue on error
        
        # Event handler for new messages
        @client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def handler(event):
            try:
                message = event.message
                
                # If no text, just send media
                if not message.text:
                    if message.media:
                        await message_queue.put({
                            'target': TARGET_CHANNEL_ID,
                            'message': f"🚀 VIP SIGNAL 🚀",
                            'media': message.media
                        })
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
                    
                    # Send message via queue
                    await message_queue.put({
                        'target': TARGET_CHANNEL_ID,
                        'message': custom_text,
                        'media': message.media
                    })
                    
                elif message_type == "TARGET_HIT":
                    # Special format for target hit - UPDATED for multiple targets
                    hit_data = extract_hit_data(message.text)
                    
                    if hit_data['coin'] and hit_data['levels'] and hit_data['prices']:
                        # Use "SIGNAL UPDATE" format for target hit
                        custom_text = f"✅ SIGNAL UPDATE: {hit_data['coin']} ✅\n\n"
                        
                        # Add all targets that were hit
                        for i in range(len(hit_data['levels'])):
                            custom_text += f"🎯 {hit_data['levels'][i]} ({hit_data['prices'][i]}) HIT!\n"
                    else:
                        # If extraction fails, send original message with standard header
                        custom_text = f"✅ SIGNAL UPDATE ✅\n\n"
                        custom_text += message.text
                    
                    # Send via queue
                    await message_queue.put({
                        'target': TARGET_CHANNEL_ID,
                        'message': custom_text,
                        'media': message.media
                    })
                    
                elif message_type == "STOP_LOSS_HIT":
                    # Special format for stop loss hit - UPDATED for multiple stop losses
                    hit_data = extract_hit_data(message.text)
                    
                    if hit_data['coin'] and hit_data['levels'] and hit_data['prices']:
                        # Use "SIGNAL UPDATE" format for stop loss hit
                        custom_text = f"🔴 SIGNAL UPDATE: {hit_data['coin']} 🔴\n\n"
                        
                        # Add all stop losses that were triggered
                        for i in range(len(hit_data['levels'])):
                            custom_text += f"⚠️ {hit_data['levels'][i]} ({hit_data['prices'][i]}) TRIGGERED!\n"
                    else:
                        # If extraction fails, send original message with standard header
                        custom_text = f"🔴 SIGNAL UPDATE 🔴\n\n"
                        custom_text += message.text
                    
                    # Send via queue
                    await message_queue.put({
                        'target': TARGET_CHANNEL_ID,
                        'message': custom_text,
                        'media': message.media
                    })
                    
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
                    else:
                        # Default format if data is incomplete
                        custom_text = f"🚀 VIP SIGNAL 🚀\n\n{message.text}"
                    
                    # Send via queue
                    await message_queue.put({
                        'target': TARGET_CHANNEL_ID,
                        'message': custom_text,
                        'media': message.media
                    })
                    
            except Exception as e:
                error_msg = f"Error processing message: {str(e)}"
                logger.error(error_msg)
                write_log(error_msg, True)
        
        # Add periodic health check
        async def health_check():
            while True:
                try:
                    await asyncio.sleep(300)  # Check every 5 minutes
                    if not client.is_connected():
                        logger.warning("Client disconnected, attempting to reconnect...")
                        write_log("Client disconnected, attempting to reconnect...")
                        try:
                            await client.connect()
                            write_log("Reconnection successful")
                        except Exception as e:
                            logger.error(f"Failed to reconnect: {str(e)}")
                            write_log(f"Reconnection failed: {str(e)}", True)
                            # If reconnection fails, raise exception to trigger restart
                            raise
                            
                    # Check for restart flag
                    if bot_state.restart_required:
                        write_log("Scheduled restart triggered by health check")
                        return  # Exit health check, which will trigger client restart
                        
                except Exception as e:
                    logger.error(f"Error in health check: {str(e)}")
                    # Sleep before retrying health check
                    await asyncio.sleep(60)
        
        # Start message sender task
        sender_task = asyncio.create_task(message_sender())
        
        # Start health check task
        health_task = asyncio.create_task(health_check())
        
        # Start scheduled restart task
        restart_task = asyncio.create_task(scheduled_restart())
        
        # Run client
        write_log("Starting Telegram client...")
        try:
            await client.start(PHONE_NUMBER, code_callback=code_callback)
        except SessionPasswordNeededError:
            # Handle 2FA if needed
            write_log("Two-factor authentication required. Please enter your password in the verification code field.")
            # Wait for password
            while not os.path.exists(VERIFICATION_CODE_FILE):
                await asyncio.sleep(1)
            
            # Read password
            with open(VERIFICATION_CODE_FILE, "r") as f:
                password = f.read().strip()
            
            # Remove file after reading
            os.remove(VERIFICATION_CODE_FILE)
            
            # Sign in with password
            await client.sign_in(password=password)
        
        log_msg = f"Bot successfully activated. Monitoring channel: {SOURCE_CHANNEL_ID}"
        logger.info(log_msg)
        write_log(log_msg)
        
        # Run until disconnected or restart required
        while bot_state.running and not bot_state.restart_required:
            try:
                # Use wait_for to limit the wait time and check for restart flag
                await asyncio.wait_for(client.disconnected, timeout=60)
                # If we get here, the client has disconnected
                break
            except asyncio.TimeoutError:
                # Just continue the loop
                pass
                
        # If we exit the loop because restart is required
        if bot_state.restart_required:
            write_log("Client exiting for scheduled restart")
            return
            
        # If we exit the loop because client disconnected
        if not client.is_connected():
            error_msg = "Client disconnected unexpectedly"
            logger.error(error_msg)
            write_log(error_msg, True)
            raise Exception("Client disconnected unexpectedly")
        
    except Exception as e:
        error_msg = f"Error running client: {str(e)}"
        logger.error(error_msg)
        write_log(error_msg, True)
        
        # If specific errors, delete session file to force clean reconnection
        if "Constructor ID" in str(e) or "database is locked" in str(e) or "misusing the session" in str(e):
            try:
                session_file = 'telegram_forwarder_session.session'
                if os.path.exists(session_file):
                    os.remove(session_file)
                    write_log("Removed corrupted session file", True)
            except Exception as se:
                write_log(f"Failed to remove session file: {str(se)}", True)
        
        # Set flag for restart - use bot_state not session_state
        bot_state.restart_required = True
        
        # Re-raise exception to allow restart mechanism to work
        raise

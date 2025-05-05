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

# Konfigurasi halaman Streamlit
st.set_page_config(
    page_title="Telegram Channel Forwarder",
    page_icon="📱",
    layout="wide"
)

# Konfigurasi logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("telegram_forwarder.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Kredeensial dan konfigurasi tetap
API_ID = 28690093
API_HASH = "aa512841e37c5ccb5a8ac494395bb373"
PHONE_NUMBER = "+6285161054271"
SOURCE_CHANNEL_ID = -1002626068320
TARGET_CHANNEL_ID = -4628225750

# File untuk menyimpan kode verifikasi
VERIFICATION_CODE_FILE = "verification_code.txt"
LOG_FILE = "bot_logs.txt"

# Inisialisasi session state
if 'running' not in st.session_state:
    st.session_state['running'] = False
if 'total_forwarded' not in st.session_state:
    st.session_state['total_forwarded'] = 0
if 'log_messages' not in st.session_state:
    st.session_state['log_messages'] = []

# Fungsi untuk menyimpan log ke file
def write_log(message, is_error=False):
    try:
        with open(LOG_FILE, "a") as f:
            timestamp = datetime.now().strftime("%H:%M:%S")
            f.write(f"{timestamp} - {'ERROR' if is_error else 'INFO'} - {message}\n")
    except Exception as e:
        logger.error(f"Gagal menulis log ke file: {str(e)}")

# Fungsi untuk membaca log dari file
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
        logger.error(f"Gagal membaca log dari file: {str(e)}")
    return logs

# Fungsi untuk mendapatkan kode verifikasi
def code_callback():
    logger.info("Menunggu kode verifikasi...")
    # Hapus file kode verifikasi jika ada
    if os.path.exists(VERIFICATION_CODE_FILE):
        os.remove(VERIFICATION_CODE_FILE)
    
    # Tulis pesan ke log
    write_log("Bot membutuhkan kode verifikasi. Silakan masukkan kode verifikasi di Telegram.")
    
    # Tunggu hingga kode verifikasi dimasukkan
    while not os.path.exists(VERIFICATION_CODE_FILE):
        time.sleep(1)
    
    # Baca kode verifikasi
    with open(VERIFICATION_CODE_FILE, "r") as f:
        code = f.read().strip()
    
    # Hapus file setelah dibaca
    os.remove(VERIFICATION_CODE_FILE)
    
    write_log(f"Kode verifikasi diterima: {code}")
    return code

# Fungsi untuk menghitung persentase perubahan
def calculate_percentage_change(entry_price, target_price):
    try:
        entry = float(entry_price)
        target = float(target_price)
        
        # Validasi untuk mencegah pembagian dengan nol atau nilai yang terlalu kecil
        if entry < 0.0001:
            logger.warning(f"Entry price terlalu kecil: {entry}, menggunakan default")
            return 0.0
            
        percentage = ((target - entry) / entry) * 100
        
        # Batasi persentase maksimum ke nilai yang masuk akal
        if abs(percentage) > 1000:
            logger.warning(f"Persentase terlalu besar: {percentage}, dibatasi ke ±1000%")
            percentage = 1000.0 if percentage > 0 else -1000.0
            
        return percentage
    except (ValueError, ZeroDivisionError):
        logger.error(f"Error saat menghitung persentase: {entry_price}, {target_price}")
        return 0.0

# Fungsi untuk mendapatkan harga cryptocurrency terkini
async def get_current_price(coin_symbol):
    try:
        # Hapus suffix USDT jika ada
        base_symbol = coin_symbol.replace('USDT', '')
        
        # Coba API Binance dulu
        binance_url = f"https://api.binance.com/api/v3/ticker/price?symbol={coin_symbol}"
        async with aiohttp.ClientSession() as session:
            async with session.get(binance_url) as response:
                if response.status == 200:
                    data = await response.json()
                    if 'price' in data:
                        return float(data['price'])
                
        # Fallback ke CoinGecko
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={base_symbol.lower()}&vs_currencies=usd"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if base_symbol.lower() in data:
                        return data[base_symbol.lower()]['usd']
                
        return None
    except Exception as e:
        logger.error(f"Error mendapatkan harga: {str(e)}")
        return None

# Fungsi untuk membuat tabel persentase perubahan
def create_percentage_table(coin_name, entry_price, targets, stop_losses):
    try:
        # Header tabel
        table = "📝 Perhitungan Persentase Perubahan Harga\n\n"
        table += "Level         Harga       % Perubahan dari Entry\n"
        table += "------------------------------------------------\n"
        
        # Tambahkan target
        for i, target in enumerate(targets, 1):
            percentage = calculate_percentage_change(entry_price, target)
            table += f"Target {i}      {target}      +{percentage:.2f}%\n"
        
        # Tambahkan stop loss
        for i, sl in enumerate(stop_losses, 1):
            percentage = calculate_percentage_change(entry_price, sl)
            # Gunakan nilai asli persentase (mungkin negatif)
            sign = "+" if percentage >= 0 else ""
            table += f"Stop Loss {i}    {sl}      {sign}{percentage:.2f}%\n"
        
        return table
    except Exception as e:
        logger.error(f"Error saat membuat tabel persentase: {str(e)}")
        return "Error saat membuat tabel persentase."

# Fungsi untuk mendeteksi jenis pesan
def detect_message_type(text):
    if re.search(r'Daily\s+Results|每日結算統計|Results', text, re.IGNORECASE):
        return "DAILY_RECAP"
    elif re.search(r'Hitted\s+target|Reached\s+target|Target\s+[\d+]\s*[✅🟢]', text, re.IGNORECASE):
        return "TARGET_HIT"
    elif re.search(r'Hitted\s+stop\s+loss|Stop\s+loss\s+triggered|Stop\s+loss\s+[\d+]\s*[🛑🔴]', text, re.IGNORECASE):
        return "STOP_LOSS_HIT"
    else:
        return "NEW_SIGNAL"

# Fungsi untuk mengekstrak data dari pesan
def extract_trading_data(message_text):
    try:
        lines = message_text.split('\n')
        
        # Variabel untuk menyimpan data yang diekstrak
        coin_name = None
        entry_price = None
        targets = []
        stop_losses = []
        
        # Pattern untuk mengekstrak coin name (biasanya di baris awal)
        for line in lines[:3]:  # Cek di 3 baris pertama
            line = line.strip()
            if not line:
                continue
                
            # Coba berbagai pola untuk coin name
            coin_patterns = [
                r'^([A-Za-z0-9]+)[^A-Za-z0-9]',  # Coin di awal baris
                r'([A-Za-z0-9]+USDT)',  # Format seperti BTCUSDT
                r'([A-Za-z0-9]+) NEW'   # Format seperti "COIN NEW"
            ]
            
            for pattern in coin_patterns:
                coin_match = re.search(pattern, line)
                if coin_match:
                    coin_name = coin_match.group(1)
                    break
            
            if coin_name:
                break
        
        # Iterasi per baris untuk ekstrak data
        for line in lines:
            line = line.strip()
            
            # Ekstrak entry price
            entry_match = re.search(r'Entry:?\s*([0-9.]+)', line)
            if entry_match:
                entry_price = entry_match.group(1)
            
            # Ekstrak target prices
            target_match = re.search(r'Target\s+(\d+):?\s*([0-9.]+)', line)
            if target_match:
                target_num = int(target_match.group(1))
                target_price = target_match.group(2)
                
                # Pastikan list cukup panjang
                while len(targets) < target_num:
                    targets.append(None)
                
                # Simpan target di posisi yang benar (indeks dimulai dari 0)
                targets[target_num-1] = target_price
            
            # Ekstrak stop loss
            sl_match = re.search(r'Stop\s+loss\s+(\d+):?\s*([0-9.]+)', line, re.IGNORECASE)
            if sl_match:
                sl_num = int(sl_match.group(1))
                sl_price = sl_match.group(2)
                
                # Pastikan list cukup panjang
                while len(stop_losses) < sl_num:
                    stop_losses.append(None)
                
                # Simpan stop loss di posisi yang benar
                stop_losses[sl_num-1] = sl_price
        
        # Hapus nilai None dari lists
        targets = [t for t in targets if t is not None]
        stop_losses = [sl for sl in stop_losses if sl is not None]
        
        return {
            'coin_name': coin_name,
            'entry_price': entry_price,
            'targets': targets,
            'stop_losses': stop_losses
        }
    except Exception as e:
        logger.error(f"Error saat ekstrak data trading: {str(e)}")
        return {
            'coin_name': None,
            'entry_price': None,
            'targets': [],
            'stop_losses': []
        }

# Fungsi untuk mengekstrak data dari target hit/stop loss message
def extract_hit_data(message_text):
    data = {'coin': None, 'level': None, 'price': None}
    
    # Cari nama coin
    coin_match = re.search(r'([A-Za-z0-9]+)(USDT|BTC|ETH|BNB)', message_text)
    if coin_match:
        data['coin'] = coin_match.group(0)
    
    # Cari level dan harga target
    if "target" in message_text.lower():
        target_match = re.search(r'Target\s+(\d+)[:\s]+([0-9.]+)', message_text, re.IGNORECASE)
        if target_match:
            data['level'] = f"Target {target_match.group(1)}"
            data['price'] = target_match.group(2)
    
    # Cari level dan harga stop loss
    elif "stop loss" in message_text.lower():
        sl_match = re.search(r'Stop\s+loss\s+(\d+)[:\s]+([0-9.]+)', message_text, re.IGNORECASE)
        if sl_match:
            data['level'] = f"Stop Loss {sl_match.group(1)}"
            data['price'] = sl_match.group(2)
    
    return data

# Fungsi untuk mengekstrak data dari daily recap
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
    
    # Ekstrak tanggal
    date_match = re.search(r'(\d{2}/\d{2}-\d{2}/\d{2})', text)
    if date_match:
        data['date'] = date_match.group(1)
    
    # Ekstrak target yang tercapai
    for i in range(1, 5):  # Target 1-4
        target_match = re.search(rf'Hitted\s+target\s+{i}:\s*(.*?)(?:\n|$)', text)
        if target_match:
            coins = [coin.strip() for coin in target_match.group(1).split(',')]
            data['hitted_targets'].append({'level': i, 'coins': coins})
    
    # Ekstrak running signals
    running_match = re.search(r'Running:\s*(.*?)(?:\n|$)', text)
    if running_match:
        data['running'] = [coin.strip() for coin in running_match.group(1).split(',')]
    
    # Ekstrak stop loss
    sl_match = re.search(r'Hitted\s+stop\s+loss:\s*(.*?)(?:\n|$)', text)
    if sl_match:
        data['stop_losses'] = [coin.strip() for coin in sl_match.group(1).split(',')]
    
    # Ekstrak statistik
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

# Fungsi untuk membuat tabel win rate
def create_win_rate_table(recap_data):
    total_signals = recap_data['total_signals']
    take_profits = recap_data['hitted_take_profits']
    stop_losses = recap_data['hitted_stop_losses']
    
    if total_signals == 0:
        win_rate = 0
    else:
        win_rate = (take_profits / total_signals) * 100
    
    table = "📊 Analisis Performa Trading 📊\n\n"
    table += "Metrik                  Nilai       Persentase\n"
    table += "--------------------------------------------\n"
    table += f"Win Rate               {take_profits}/{total_signals}     {win_rate:.2f}%\n"
    
    if take_profits + stop_losses > 0:
        profit_ratio = (take_profits / (take_profits + stop_losses)) * 100
        table += f"Profit/Loss Ratio      {take_profits}/{stop_losses}     {profit_ratio:.2f}%\n"
    
    table += f"Sinyal Running         {len(recap_data['running'])}         {(len(recap_data['running'])/total_signals*100):.2f}%\n"
    
    return table

# Fungsi untuk menjalankan client Telethon
async def run_client():
    try:
        # Buat client
        client = TelegramClient('telegram_forwarder_session', API_ID, API_HASH)
        
        # Event handler untuk pesan baru
        @client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def handler(event):
            try:
                message = event.message
                
                # Jika tidak ada pesan, hanya kirim media
                if not message.text:
                    if message.media:
                        await client.send_file(
                            TARGET_CHANNEL_ID, 
                            message.media,
                            caption=f"🚀 VIP SIGNAL 🚀\n\n💹 @liananalyst"
                        )
                    return
                
                # Deteksi jenis pesan
                message_type = detect_message_type(message.text)
                
                if message_type == "DAILY_RECAP":
                    # Proses daily recap
                    recap_data = extract_daily_recap_data(message.text)
                    
                    # Buat teks dengan win rate
                    custom_text = f"📅 DAILY RECAP: {recap_data['date'] if recap_data['date'] else 'Hari Ini'} 📅\n\n"
                    custom_text += message.text + "\n\n"
                    custom_text += create_win_rate_table(recap_data)
                    custom_text += "\n\n💹 @liananalyst"
                    
                    # Kirim pesan
                    await client.send_message(TARGET_CHANNEL_ID, custom_text)
                    
                elif message_type == "TARGET_HIT":
                    # Format khusus untuk target tercapai
                    hit_data = extract_hit_data(message.text)
                    
                    if hit_data['coin'] and hit_data['level'] and hit_data['price']:
                        custom_text = f"✅ TARGET TERCAPAI: {hit_data['coin']} ✅\n\n"
                        custom_text += f"🎯 {hit_data['level']} ({hit_data['price']}) TERCAPAI!\n\n"
                    else:
                        # Jika ekstraksi gagal, kirim pesan asli dengan header standar
                        custom_text = f"✅ TARGET TERCAPAI ✅\n\n"
                        custom_text += message.text + "\n\n"
                    
                    custom_text += "💹 @liananalyst"
                    
                    await client.send_message(TARGET_CHANNEL_ID, custom_text)
                    
                elif message_type == "STOP_LOSS_HIT":
                    # Format khusus untuk stop loss terkena
                    hit_data = extract_hit_data(message.text)
                    
                    if hit_data['coin'] and hit_data['level'] and hit_data['price']:
                        custom_text = f"🔴 STOP LOSS TERKENA: {hit_data['coin']} 🔴\n\n"
                        custom_text += f"⚠️ {hit_data['level']} ({hit_data['price']}) TERKENA!\n\n"
                    else:
                        # Jika ekstraksi gagal, kirim pesan asli dengan header standar
                        custom_text = f"🔴 STOP LOSS TERKENA 🔴\n\n"
                        custom_text += message.text + "\n\n"
                    
                    custom_text += "💹 @liananalyst"
                    
                    await client.send_message(TARGET_CHANNEL_ID, custom_text)
                    
                else:  # NEW_SIGNAL
                    # Ekstrak data trading
                    trading_data = extract_trading_data(message.text)
                    coin_name = trading_data['coin_name']
                    entry_price = trading_data['entry_price']
                    targets = trading_data['targets']
                    stop_losses = trading_data['stop_losses']
                    
                    # Jika tidak ada entry price tapi ada coin name, coba dapatkan harga terkini
                    if coin_name and not entry_price and (targets or stop_losses):
                        current_price = await get_current_price(coin_name)
                        if current_price:
                            entry_price = str(current_price)
                            logger.info(f"Menggunakan harga terkini untuk {coin_name}: {entry_price}")
                    
                    # Buat pesan kustom
                    if coin_name and entry_price and (targets or stop_losses):
                        # Header pesan
                        custom_text = f"🚀 VIP SIGNAL: {coin_name} 🚀\n\n"
                        
                        # Tambahkan pesan asli
                        custom_text += message.text + "\n\n"
                        
                        # Tambahkan tabel persentase jika data cukup
                        if targets or stop_losses:
                            custom_text += create_percentage_table(coin_name, entry_price, targets, stop_losses)
                        
                        # Footer
                        custom_text += "\n\n💹 @liananalyst"
                    else:
                        # Format default jika data tidak lengkap
                        custom_text = f"🚀 VIP SIGNAL 🚀\n\n{message.text}\n\n💹 @liananalyst"
                    
                    # Kirim pesan ke channel tujuan
                    await client.send_message(TARGET_CHANNEL_ID, custom_text)
                
                # Log info pesan
                message_preview = message.text[:50] + "..." if message.text and len(message.text) > 50 else "Media atau pesan tanpa teks"
                log_msg = f"Pesan berhasil dikirim ulang: {message_preview}"
                logger.info(log_msg)
                write_log(log_msg)
                    
            except Exception as e:
                error_msg = f"Error saat mengirim pesan: {str(e)}"
                logger.error(error_msg)
                write_log(error_msg, True)
        
        # Jalankan client
        write_log("Memulai client Telegram...")
        await client.start(PHONE_NUMBER, code_callback=code_callback)
        
        log_msg = f"Bot berhasil diaktifkan. Memantau channel: {SOURCE_CHANNEL_ID}"
        logger.info(log_msg)
        write_log(log_msg)
        
        # Jalankan hingga dihentikan
        await client.run_until_disconnected()
        
    except Exception as e:
        error_msg = f"Error saat menjalankan client: {str(e)}"
        logger.error(error_msg)
        write_log(error_msg, True)

# Fungsi untuk menjalankan client dalam thread terpisah
def start_client_thread():
    try:
        write_log("Memulai client dalam thread terpisah...")
        asyncio.set_event_loop(asyncio.new_event_loop())
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_client())
    except Exception as e:
        error_msg = f"Error dalam thread: {str(e)}"
        logger.error(error_msg)
        write_log(error_msg, True)

# Fungsi untuk menyimpan kode verifikasi
def save_verification_code():
    if st.session_state.code_input:
        try:
            with open(VERIFICATION_CODE_FILE, "w") as f:
                f.write(st.session_state.code_input)
            st.success("Kode verifikasi dikirim!")
        except Exception as e:
            st.error(f"Gagal menyimpan kode verifikasi: {str(e)}")

# UI Streamlit
st.title("Telegram Channel Forwarder")
st.markdown("Aplikasi untuk meneruskan pesan dari channel sumber ke channel tujuan Anda.")

# Kolom untuk kode verifikasi
if st.session_state['running']:
    st.text_input("Masukkan Kode Verifikasi dari Telegram (jika diminta):", 
                  key="code_input", 
                  on_change=save_verification_code)

# Tampilkan status dan statistik
st.subheader("Status & Statistik")
col1, col2 = st.columns(2)
with col1:
    status = "🟢 **Running**" if st.session_state['running'] else "🔴 **Stopped**"
    st.markdown(f"**Bot Status:** {status}")
with col2:
    # Update total forwarded dari log
    forwarded_count = 0
    for log in read_logs():
        if "Pesan berhasil dikirim ulang" in log['message']:
            forwarded_count += 1
    st.session_state['total_forwarded'] = forwarded_count
    st.markdown(f"**Total Pesan Dikirim:** {st.session_state['total_forwarded']}")

# Tombol start/stop
col1, col2 = st.columns(2)
with col1:
    if not st.session_state['running']:
        if st.button("Start Forwarding", use_container_width=True):
            # Buat file log jika belum ada
            if not os.path.exists(LOG_FILE):
                with open(LOG_FILE, "w") as f:
                    f.write("")
            
            # Jalankan client di thread terpisah
            thread = threading.Thread(target=start_client_thread, daemon=True)
            thread.start()
            
            st.session_state['running'] = True
            write_log("Bot starting...")
            st.rerun()
with col2:
    if st.session_state['running']:
        if st.button("Stop Forwarding", use_container_width=True):
            # Hentikan client - tidak ada cara langsung untuk menghentikan thread
            # Hanya tandai sebagai tidak berjalan
            st.session_state['running'] = False
            write_log("Bot stopped!")
            st.rerun()

# Tampilkan log aktivitas
st.subheader("Log Aktivitas")
log_container = st.container()
with log_container:
    # Baca log dari file
    logs = read_logs()
    # Tampilkan 10 log terakhir
    if logs:
        for log in reversed(logs[-10:]):
            timestamp = log.get('time', '')
            message = log.get('message', '')
            is_error = log.get('error', False)
            
            if is_error:
                st.error(f"{timestamp} - {message}")
            else:
                st.info(f"{timestamp} - {message}")

# Tambahkan cara penggunaan
with st.expander("Cara Penggunaan"):
    st.markdown("""
    ### Cara Menggunakan Aplikasi Ini:
    
    1. **Menjalankan Bot**:
       - Klik "Start Forwarding" untuk memulai
       - Pertama kali, Anda mungkin diminta memasukkan kode verifikasi
       - Klik "Stop Forwarding" untuk menghentikan bot
    
    2. **Kode Verifikasi**:
       - Saat pertama kali dijalankan, Telegram akan mengirimkan kode verifikasi ke nomor telepon Anda
       - Masukkan kode tersebut pada kolom "Kode Verifikasi" yang muncul
    
    3. **Melihat Log**:
       - Lihat bagian "Log Aktivitas" untuk memantau proses pengiriman pesan
       - Log juga disimpan di file `telegram_forwarder.log`
    
    4. **Format Pesan**:
       - Pesan trading baru: Ditambahkan perhitungan persentase perubahan
       - Target tercapai: Format dengan sorotan aset
       - Stop loss: Format dengan sorotan aset
       - Daily recap: Ditambahkan perhitungan win rate dan statistik
    
    5. **Troubleshooting**:
       - Jika error, restart aplikasi
       - Pastikan akun Anda memiliki akses ke kedua channel
    """)

# Auto-refresh halaman setiap 5 detik
time.sleep(5)
st.rerun()

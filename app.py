import streamlit as st
import asyncio
import threading
from telethon import TelegramClient, events
from telethon.tl.functions.messages import ForwardMessagesRequest
import logging
import time
import os
from datetime import datetime

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
SOURCE_CHANNEL_ID = -1002051092635
TARGET_CHANNEL_ID = -4628225750

# Inisialisasi session state - VITAL
if 'running' not in st.session_state:
    st.session_state['running'] = False
if 'client' not in st.session_state:
    st.session_state['client'] = None
if 'log_messages' not in st.session_state:
    st.session_state['log_messages'] = []
if 'total_forwarded' not in st.session_state:
    st.session_state['total_forwarded'] = 0

# Variabel global untuk kode verifikasi
code_to_check = None

# Fungsi untuk menjalankan client Telethon
async def run_client():
    global code_to_check
    try:
        # Buat client
        client = TelegramClient('telegram_forwarder_session', API_ID, API_HASH)
        
        # Fungsi untuk mendapatkan kode verifikasi
        def code_callback():
            # Tunggu sampai kode dimasukkan
            while code_to_check is None:
                time.sleep(1)
            
            # Ambil kode dan reset
            code = code_to_check
            code_to_check = None
            return code
        
        @client.on(events.NewMessage(chats=SOURCE_CHANNEL_ID))
        async def handler(event):
            try:
                # Forward pesan ke channel tujuan
                await client(ForwardMessagesRequest(
                    from_peer=SOURCE_CHANNEL_ID,
                    id=[event.message.id],
                    to_peer=TARGET_CHANNEL_ID,
                    with_my_score=True,
                ))
                
                # Update counter dan log
                st.session_state['total_forwarded'] += 1
                
                # Log info pesan
                message_preview = event.message.text[:50] + "..." if event.message.text and len(event.message.text) > 50 else "Media atau pesan tanpa teks"
                log_msg = f"Pesan berhasil diforward: {message_preview}"
                logger.info(log_msg)
                
                # Update log di UI
                st.session_state['log_messages'].append({
                    'time': datetime.now().strftime("%H:%M:%S"),
                    'message': log_msg,
                    'error': False
                })
                
            except Exception as e:
                error_msg = f"Error saat forward pesan: {str(e)}"
                logger.error(error_msg)
                st.session_state['log_messages'].append({
                    'time': datetime.now().strftime("%H:%M:%S"),
                    'message': error_msg,
                    'error': True
                })
        
        # Jalankan client
        await client.start(PHONE_NUMBER, code_callback=code_callback)
        logger.info(f"Bot telah aktif! Memantau channel ID: {SOURCE_CHANNEL_ID}")
        st.session_state['log_messages'].append({
            'time': datetime.now().strftime("%H:%M:%S"),
            'message': f"Bot berhasil diaktifkan. Memantau channel: {SOURCE_CHANNEL_ID}",
            'error': False
        })
        
        # Simpan client di session state
        st.session_state['client'] = client
        
        # Jalankan hingga dihentikan
        await client.run_until_disconnected()
        
    except Exception as e:
        error_msg = f"Error saat menjalankan client: {str(e)}"
        logger.error(error_msg)
        st.session_state['log_messages'].append({
            'time': datetime.now().strftime("%H:%M:%S"),
            'message': error_msg,
            'error': True
        })
        st.session_state['running'] = False

# Fungsi untuk menjalankan client dalam thread terpisah
def start_client_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(run_client())
    except Exception as e:
        logger.error(f"Error dalam client thread: {str(e)}")
    finally:
        loop.close()

# Fungsi untuk menghentikan client
async def stop_client():
    if st.session_state['client']:
        await st.session_state['client'].disconnect()
        st.session_state['client'] = None

def stop_client_thread():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(stop_client())
    finally:
        loop.close()

# Fungsi untuk meng-handle input kode verifikasi
def handle_code_input():
    global code_to_check
    if st.session_state.code_input:
        code_to_check = st.session_state.code_input
        st.success("Kode verifikasi dimasukkan!")

# UI Streamlit
st.title("Telegram Channel Forwarder")
st.markdown("Aplikasi untuk meneruskan pesan dari channel sumber ke channel tujuan Anda.")

# Tampilkan area untuk memasukkan kode verifikasi
if st.session_state['running']:
    st.text_input("Masukkan Kode Verifikasi dari Telegram (jika diminta):", key="code_input", on_change=handle_code_input)

# Tampilkan status dan statistik
st.subheader("Status & Statistik")
col1, col2 = st.columns(2)
with col1:
    status = "🟢 **Running**" if st.session_state['running'] else "🔴 **Stopped**"
    st.markdown(f"**Bot Status:** {status}")
with col2:
    st.markdown(f"**Total Pesan Diteruskan:** {st.session_state['total_forwarded']}")

# Tombol start/stop
col1, col2 = st.columns(2)
with col1:
    if not st.session_state['running']:
        if st.button("Start Forwarding", use_container_width=True):
            # Jalankan client di thread terpisah
            thread = threading.Thread(target=start_client_thread)
            thread.daemon = True
            thread.start()
            
            st.session_state['running'] = True
            st.session_state['log_messages'].append({
                'time': datetime.now().strftime("%H:%M:%S"),
                'message': "Bot starting...",
                'error': False
            })
with col2:
    if st.session_state['running']:
        if st.button("Stop Forwarding", use_container_width=True):
            # Hentikan client
            stop_client_thread()
            st.session_state['running'] = False
            st.session_state['log_messages'].append({
                'time': datetime.now().strftime("%H:%M:%S"),
                'message': "Bot stopped!",
                'error': False
            })

# Tampilkan log aktivitas
st.subheader("Log Aktivitas")
log_container = st.container()
with log_container:
    # Tabel log dengan scrolling
    if st.session_state['log_messages']:
        for log in reversed(st.session_state['log_messages'][-10:]):
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
       - Lihat bagian "Log Aktivitas" untuk memantau proses forwarding
       - Log juga disimpan di file `telegram_forwarder.log`
    
    4. **Troubleshooting**:
       - Jika error, restart aplikasi
       - Pastikan akun Anda memiliki akses ke kedua channel
    """)

# Auto-refresh halaman setiap 10 detik jika bot sedang berjalan
if st.session_state['running']:
    time.sleep(10)
    st.rerun()

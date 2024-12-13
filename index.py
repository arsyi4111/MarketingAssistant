from flask import Flask, request, jsonify
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder
import os
from dotenv import load_dotenv
import math
import logging

load_dotenv()  # Load environment variables from a .env file

app = Flask(__name__)

# Sample 'data_pengguna' DataFrame (replace with your actual database or data source)
data_pengguna = [
    {'no_hp': '6289506325727', 'nama': 'Muhamad Arsyi', 'bersih': 6600000, 'called': False, 'acc': False},
]

# Logging setup
logging.basicConfig(level=logging.INFO)

# Dictionary to store user state for tracking loan request flow
user_state = {}
loan_amounts = {}

# Function to normalize phone numbers (to remove '0' and add '62' prefix if necessary)
def normalize_phone_number(phone_number):
    # Remove WhatsApp domain if present
    if '@s.whatsapp.net' in phone_number:
        phone_number = phone_number.split('@')[0]
    if not phone_number.isdigit():  # Check if the phone number contains only digits
        raise ValueError(f"Invalid phone number: {phone_number}")
    if phone_number.startswith('0'):
        return '62' + phone_number[1:]
    elif phone_number.startswith('62'):
        return phone_number
    else:
        return '62' + phone_number  # Assume the number is in international format

# Function to calculate the minimum number of months based on salary and amount
def calculate_min_months(amount, salary):
    annual_interest_rate = 0.10  # Example annual interest rate (10%)
    monthly_interest_rate = annual_interest_rate / 12
    
    max_affordable_payment = salary * 0.40
    n = math.log(max_affordable_payment / (max_affordable_payment - (monthly_interest_rate * amount))) / math.log(1 + monthly_interest_rate)
    min_months = math.ceil(n)
    return min_months

# Function to calculate the monthly payment based on amount and months
def calculate_monthly_payment(amount, months):
    annual_interest_rate = 0.10  # Example annual interest rate (10%)
    monthly_interest_rate = annual_interest_rate / 12
    
    numerator = monthly_interest_rate * amount * (1 + monthly_interest_rate)**months
    denominator = (1 + monthly_interest_rate)**months - 1
    monthly_payment = numerator / denominator
    return monthly_payment

# Function to send WhatsApp messages using WHAPI
def send_whapi_request(endpoint, params=None, method='POST'):
    headers = {
        'Authorization': f"Bearer {os.getenv('TOKEN')}"
    }
    url = f"{os.getenv('API_URL')}/{endpoint}"
    try:
        if params:
            if 'media' in params:
                details = params.pop('media').split(';')
                with open(details[0], 'rb') as file:
                    m = MultipartEncoder(fields={**params, 'media': (details[0], file, details[1])})
                    headers['Content-Type'] = m.content_type
                    response = requests.request(method, url, data=m, headers=headers)
            elif method == 'GET':
                response = requests.get(url, params=params, headers=headers)
            else:
                headers['Content-Type'] = 'application/json'
                response = requests.request(method, url, json=params, headers=headers)
        else:
            response = requests.request(method, url, headers=headers)

        if response.status_code != 200:
            logging.error(f"Error: Received status code {response.status_code} from WHAPI")
            return None

        return response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"Error sending request: {e}")
        return None

# Set webhook to start receiving messages
def set_hook():
    if os.getenv('BOT_URL'):
        settings = {
            'webhooks': [
                {
                    'url': os.getenv('BOT_URL'),
                    'events': [
                        {'type': "messages", 'method': "post"}
                    ],
                    'mode': "method"
                }
            ]
        }
        send_whapi_request('settings', settings, 'PATCH')


@app.route('/hook/messages', methods=['POST'])
def handle_new_messages():
    try:
        messages = request.json.get('messages', [])
        for message in messages:
            logging.info(f"Received message: {message}")
            
            if message.get('from_me'):
                continue
            
            chat_id = message.get('chat_id')
            if not chat_id:
                logging.warning("Missing chat_id in the message")
                continue  # Skip this message if chat_id is missing

            text = message.get('text', {}).get('body', '').strip()
            if not text:
                logging.warning("Empty text body in the message")
                continue  # Skip this message if text is empty

            # Normalize chat_id to the '62xxxxxxxxxx' format
            normalized_chat_id = normalize_phone_number(chat_id)

            # Find user based on normalized phone number
            user = next((u for u in data_pengguna if normalize_phone_number(u['no_hp']) == normalized_chat_id), None)
            
            if user:
                name = user['nama']
                salary = user['bersih']
                
                # Get user state (e.g., if the user has already started the loan process)
                state = user_state.get(chat_id, None)
                amount = loan_amounts.get(chat_id, None)
                
                # Send initial greeting if this is the user's first interaction
                if not user['called']:
                    send_whapi_request(
                        'messages/text',
                        {
                            'to': f"{normalized_chat_id}@s.whatsapp.net",
                            'body': f"Hai, {name}! Terima kasih sudah menjadi pelanggan setia Pos Indonesia. Anda terpilih untuk mengajukan pinjaman kredit pensiun. Apakah anda tertarik? (Kirim '1' jika ya; '2' jika tidak)."
                        }
                    )
                    user['called'] = True
                    user_state[chat_id] = 'waiting_for_interest'  # Save state
                    continue  # Stop further processing to avoid duplicate replies
                
                # Process user responses based on state
                if state == 'waiting_for_interest':
                    if text == '1':  # User wants to request a loan
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': f"Terima kasih atas ketertarikan anda! Berapa jumlah pinjaman yang ingin anda ajukan?"})
                        user_state[chat_id] = 'waiting_for_loan_amount'  # Update state
                    elif text == '2':  # User doesn't want a loan
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Terima kasih! Jika Anda berubah pikiran, silakan hubungi kami."})
                        user_state[chat_id] = 'interest_declined'  # Update state
                    else:
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Silakan kirim '1' bila Anda tertarik dengan pinjaman."})
                elif state == 'waiting_for_loan_amount':
                    if text.isdigit() and int(text) > 0:  # Loan amount entered
                        loan_amount = int(text)
                        loan_amounts[chat_id] = loan_amount
                        min_months = calculate_min_months(loan_amount, salary)
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': f"Berdasarkan jumlah yang anda inginkan, waktu pinjaman minimal adalah {min_months} Bulan. Berapa lama anda ingin mengajukan pinjaman (Kirim jumlah bulan dalam bentuk angka (maksimal 60 Bulan))."})
                        user_state[chat_id] = 'waiting_for_loan_duration'  # Update state
                    else:
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Jumlah pinjaman tidak valid. Silakan coba lagi."})
                elif state == 'waiting_for_loan_duration':
                    if text.isdigit() and int(text) > 0:  # Loan duration entered
                        loan_amount = int(loan_amounts.get(chat_id))
                        months = int(text)
                        monthly_payment = calculate_monthly_payment(loan_amount, months)
                        max_affordable_payment = salary * 0.40
                        
                        if monthly_payment <= max_affordable_payment:
                            send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': f"Estimasi pembayaran bulanan anda adalah: Rp {monthly_payment:,.2f}. Apakah anda ingin mengajukan pinjaman dan dikunjungi oleh tim kami untuk proses lebih lanjut? Kirim '1' jika setuju; '2' jika tidak."})
                        else:
                            send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': f"Estimasi pembayaran bulanan anda adalah: Rp {monthly_payment:,.2f}. Sayangnya, nilai ini tidak sesuai dengan perhitungan sistem kami. Apakah Anda ingin mempertimbangkan lagi?"})
                        user_state[chat_id] = 'waiting_for_confirmation'  # Update state
                elif state == 'waiting_for_confirmation':
                    if text == '1':  # Accept loan
                        user['acc'] = True
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Terima kasih atas konfirmasinya! Tim kami akan segera menghubungi anda."})
                        user_state[chat_id] = 'loan_accepted'  # Update state
                    elif text == '2':  # Decline loan
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Baik, apabila anda ingin melakukan rekalkulasi silahkan hubungi kami kembali. Terima kasih!"})
                        user_state[chat_id] = 'loan_declined'  # Update state
                    else:
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Silakan kirim '1' jika Anda setuju dengan pinjaman."})

        return 'Ok', 200
    except Exception as e:
        logging.error(f"Error handling message: {e}")
        return str(e), 500

@app.route('/send_initiation', methods=['GET'])
def send_initiation_message():
    try:
        for user in data_pengguna:
            if not user['called']:
                chat_id = f"{normalize_phone_number(user['no_hp'])}@s.whatsapp.net"

                # Send initial message to user
                send_whapi_request(
                    'messages/text',
                    {
                        'to': chat_id,
                        'body': f"Hai, {user['nama']}! Terima kasih sudah menjadi pelanggan setia Pos Indonesia. Anda terpilih untuk mengajukan pinjaman kredit pensiun. Apakah anda tertarik? (Kirim '1' jika ya; '2' jika tidak)."
                    }
                )
                
                # Update the 'called' status to True to avoid sending the message again
                user['called'] = True

                # Update user state to 'waiting_for_interest'
                user_state[chat_id] = 'waiting_for_interest'
                logging.info(f"User state set to 'waiting_for_interest' for {chat_id}")
                
        return "Initiation messages sent successfully.", 200
    except Exception as e:
        logging.error(f"Error sending initiation messages: {e}")
        return str(e), 500

@app.route('/', methods=['GET'])
def index():
    return 'Bot is running'

if __name__ == '__main__':
    set_hook()
    port = os.getenv('PORT') or (443 if os.getenv('BOT_URL', '').startswith('https:') else 80)
    app.run(port=port, debug=True)

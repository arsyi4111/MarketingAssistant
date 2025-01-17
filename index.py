from flask import Flask, request, jsonify
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder
import os
from dotenv import load_dotenv
import math
import logging
import psycopg2
import pandas as pd

load_dotenv()  # Load environment variables from a .env file

app = Flask(__name__)

# Sample 'data_pengguna' DataFrame (replace with your actual database or data source)
# data_pengguna = [
#     {'no_hp': '6289506325727', 'nama': 'Muhamad Arsyi', 'bersih': 6600000, 'alamat': 'Kp. Cicaheum No.56, Cimenyan, Bandung', 'called': False, 'acc': False},
#     {'no_hp': '628129311209', 'nama': 'Dudya Dermawan', 'bersih': 7000000, 'alamat': 'Jl. Kb. Kembang no.20, Karangmekar, Kota Cimahi', 'called': False, 'acc': False},
#     {'no_hp': '6285693553207', 'nama': 'Dudya Dermawan', 'bersih': 7000000, 'alamat': 'Jl. Kb. Kembang no.20, Karangmekar, Kota Cimahi', 'called': False, 'acc': False}
#     ]
    

# data_karyawan = [
#     {'nama' : 'Muhamad Arsyi', 'nopend' : 14000, 'nama_kantor' : 'Kantor Pusat Jakarta'}
# ]

DATABASE_URL = os.getenv('DATABASE_URL')
conn = psycopg2.connect(DATABASE_URL, sslmode='disable')
cur = conn.cursor()

# Fetch data from the database
cur.execute('SELECT nip, no_hp, nama_pensiunan, gaji, alamat, called, acc,  state, k.nama_kcu , la.nama FROM "user" left join "kantor_pos" on "user".kantor_pos = "kantor_pos".kode_dirian left join list_am la on "kantor_pos".kode_kcu = la.kode_dirian  left join kcu k on "kantor_pos".kode_kcu = k.kode_kcu')
data_pengguna_records = cur.fetchall()
data_pengguna = pd.DataFrame(data_pengguna_records, columns=['nip', 'no_hp', 'nama', 'bersih', 'alamat', 'called', 'acc', 'state', 'nama_kcu', 'nama_am'])

cur.execute('SELECT ')
print(data_pengguna)

# Logging setup
logging.basicConfig(level=logging.INFO)

# Dictionary to store user state for tracking loan request flow
user_state = {}
loan_amounts = {}
duration_months = {}

# State mappings
STATE_DEFAULT = 0
STATE_WAITING_FOR_INTEREST = 1
STATE_INTEREST_DECLINED = 2
STATE_WAITING_FOR_LOAN_AMOUNT = 3
STATE_WAITING_FOR_LOAN_DURATION = 4
STATE_WAITING_FOR_CONFIRMATION = 5
STATE_LOAN_DECLINED = 6
STATE_WAITING_FOR_ADDRESS_FINAL_CONFIRMATION = 7
STATE_LOAN_ACCEPTED = 8
STATE_WAITING_FOR_NEW_ADDRESS = 9

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

# Function to calculate the maximum loan amount based on salary and loan duration
def calculate_max_loan(salary, max_months=60):
    annual_interest_rate = 0.10  # Example annual interest rate (10%)
    monthly_interest_rate = annual_interest_rate / 12
    max_affordable_payment = salary * 0.40  # User can afford up to 40% of their salary

    # Reverse calculate the maximum loan amount based on the monthly payment formula
    numerator = max_affordable_payment * ((1 + monthly_interest_rate) ** max_months - 1)
    denominator = monthly_interest_rate * (1 + monthly_interest_rate) ** max_months
    max_loan = numerator / denominator

    return max_loan

def round_down_even(number, base=100000):
    return math.floor(number / base) * base

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

def update_user_state_in_db(chat_id, state, called=None, loan_amount=None, duration=None, monthly_payment=None):
    try:
        normalized_chat_id = normalize_phone_number(chat_id)
        query = 'UPDATE "user" SET state = %s'
        params = [state]

        if called is not None:
            query += ', called = %s'
            params.append(called)

        if loan_amount is not None:
            query += ', nominal_pinjaman = %s'
            params.append(loan_amount)

        if duration is not None:
            query += ', durasi_pinjaman = %s'
            params.append(duration)

        if monthly_payment is not None:
            query += ', nominal_angsuran = %s'
            params.append(monthly_payment)

        query += ' WHERE no_hp = %s'
        params.append(normalized_chat_id)

        cur.execute(query, params)
        conn.commit()
    except Exception as e:
        logging.error(f"Error updating user state in database: {e}")

@app.route('/hook/messages', methods=['POST'])
def handle_new_messages():
    try:
        # Get the list of messages from the request
        messages = request.json.get('messages', [])
        logging.info(f"Received {len(messages)} messages.")

        for message in messages:
            logging.info(f"Received message: {message}")

            # Skip if the message is from the sender itself
            if message.get('from_me'):
                continue

            # Extract chat_id and ensure it exists
            chat_id = message.get('chat_id')

            if not chat_id:
                logging.warning("Missing chat_id in the message")
                continue  # Skip this message if chat_id is missing

            # Extract and normalize the text body, ensuring the 'text' structure is valid
            text = message.get('text', {})
            if isinstance(text, dict):
                text_body = text.get('body', '').strip().lower()
            else:
                logging.error(f"Unexpected format for 'text'. Received: {text}")
                text_body = ''

            if not text_body:
                logging.warning("Empty text body in the message")
                continue  # Skip this message if text is empty
            
            # Normalize chat_id to the '62xxxxxxxxxx' format
            normalized_chat_id = str(normalize_phone_number(chat_id))

            # Find user based on normalized phone number
            data_pengguna_dict = data_pengguna.to_dict('records')
            print("Data Pengguna: ", data_pengguna_dict)
            print("Normalized Chat ID:", normalized_chat_id)
            print("normalized u nohp:" , normalize_phone_number(data_pengguna_dict[0]['no_hp']))
            user = next((u for u in data_pengguna_dict if normalize_phone_number(u['no_hp']) == normalized_chat_id), None)
            print("User: ", user)

            if user:
                name = user['nama']
                salary = user['bersih']
                nama_am = user['nama_am']
                nama_kcu = user['nama_kcu']
                
                # Restart interaction if user sends "halo"
                if text_body == 'halo':
                    user_state.pop(chat_id, None)
                    loan_amounts.pop(chat_id, None)
                    send_whapi_request(
                        'messages/text',
                        {
                            'to': f"{normalized_chat_id}@s.whatsapp.net",
                            'body': f"Hai, {name}! Terima kasih sudah menjadi pelanggan setia BSI. Anda terpilih untuk mengajukan pinjaman kredit pensiun. Apakah anda tertarik? (Kirim '1' jika ya; '2' jika tidak)."
                        }
                    )
                    user['called'] = True
                    user_state[chat_id] = STATE_WAITING_FOR_INTEREST  # Restart state
                    print(user_state[chat_id])
                    update_user_state_in_db(chat_id, STATE_WAITING_FOR_INTEREST, called=True)
                    continue

                # Get user state (e.g., if the user has already started the loan process)
                state = user_state.get(chat_id, user['state'])
                amount = loan_amounts.get(chat_id, None)
                
                # Reset state if user was not interested or declined a previous offer
                if state in [STATE_INTEREST_DECLINED, STATE_LOAN_DECLINED]:
                    user_state.pop(chat_id, None)
                    loan_amounts.pop(chat_id, None)
                    send_whapi_request(
                        'messages/text',
                        {
                            'to': f"{normalized_chat_id}@s.whatsapp.net",
                            'body': f"Hai, {name}! Terima kasih sudah menjadi pelanggan setia BSI. Anda terpilih untuk mengajukan pinjaman kredit pensiun. Apakah anda tertarik? (Kirim '1' jika ya; '2' jika tidak)."
                        }
                    )
                    user['called'] = True
                    user_state[chat_id] = STATE_WAITING_FOR_INTEREST  # Restart state
                    update_user_state_in_db(chat_id, STATE_WAITING_FOR_INTEREST, called=True)
                    continue

                # Send initial greeting if this is the user's first interaction
                if not user['called']:
                    send_whapi_request(
                        'messages/text',
                        {
                            'to': f"{normalized_chat_id}@s.whatsapp.net",
                            'body': f"Hai, {name}! Terima kasih sudah menjadi pelanggan setia BSI. Anda terpilih untuk mengajukan pinjaman kredit pensiun. Apakah anda tertarik? (Kirim '1' jika ya; '2' jika tidak)."
                        }
                    )
                    user['called'] = True
                    user_state[chat_id] = STATE_WAITING_FOR_INTEREST  # Save state
                    update_user_state_in_db(chat_id, STATE_WAITING_FOR_INTEREST, called=True)
                    continue  # Stop further processing to avoid duplicate replies
                
                # Process user responses based on state
                if state == STATE_WAITING_FOR_INTEREST:
                    if text_body == '1':  # User wants to request a loan
                        # Calculate the maximum loan amount
                        max_loan = calculate_max_loan(salary)
                        max_loan_even = round_down_even(max_loan)
                        
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': f"Terima kasih atas ketertarikan anda! Berapa jumlah pinjaman yang ingin anda ajukan? (Maksimum Rp. {max_loan_even:,.2f})."
                            }
                        )
                        user_state[chat_id] = STATE_WAITING_FOR_LOAN_AMOUNT  # Update state
                        update_user_state_in_db(chat_id, STATE_WAITING_FOR_LOAN_AMOUNT)
                    elif text_body == '2':  # User doesn't want a loan
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Terima kasih! Jika Anda berubah pikiran, silakan hubungi kami."})
                        user_state[chat_id] = STATE_INTEREST_DECLINED  # Update state
                        update_user_state_in_db(chat_id, STATE_INTEREST_DECLINED)
                    else:
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Silakan kirim '1' bila Anda tertarik dengan pinjaman."})
                elif state == STATE_WAITING_FOR_LOAN_AMOUNT:
                    if text_body.isdigit() and int(text_body) > 0:  # Loan amount entered
                        loan_amount = int(text_body)
                        loan_amounts[chat_id] = loan_amount
                        min_months = calculate_min_months(loan_amount, salary)
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': f"Berdasarkan jumlah yang anda inginkan sebesar Rp. {loan_amounts.get(chat_id):,.2f}, waktu pinjaman minimal adalah {min_months} Bulan. Berapa lama anda ingin mengajukan pinjaman. Kirim jumlah bulan dalam bentuk angka (maksimal 60 Bulan)."})
                        user_state[chat_id] = STATE_WAITING_FOR_LOAN_DURATION  # Update state
                        update_user_state_in_db(chat_id, STATE_WAITING_FOR_LOAN_DURATION)
                    else:
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Jumlah pinjaman tidak valid. Silakan coba lagi."})
                elif state == STATE_WAITING_FOR_LOAN_DURATION:
                    if text_body.isdigit() and int(text_body) > 0:  # Loan duration entered
                        loan_amount = int(loan_amounts.get(chat_id))
                        months = int(text_body)
                        duration_months[chat_id] = months
                        monthly_payment = calculate_monthly_payment(loan_amount, months)
                        max_affordable_payment = salary * 0.40
                        
                        if monthly_payment <= max_affordable_payment:
                            send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': f"Berdasarkan jumlah yang anda inginkan Rp. {loan_amount:,.2f} dan durasi {duration_months[chat_id]} Bulan. Estimasi pembayaran bulanan anda adalah: Rp {monthly_payment:,.2f}. Jumlah cicilan total adalah Rp. {(monthly_payment*duration_months[chat_id]):,.2f} Apakah anda ingin mengajukan pinjaman dan dikunjungi oleh tim kami untuk proses lebih lanjut? Kirim '1' jika setuju; '2' jika tidak."})
                        else:
                            send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': f"Berdasarkan jumlah yang anda inginkan Rp. {loan_amount:,.2f} dan durasi {duration_months[chat_id]} Bulan. Estimasi pembayaran bulanan anda adalah: Rp {monthly_payment:,.2f}. Sayangnya, nilai ini tidak sesuai dengan perhitungan sistem kami. Apakah Anda ingin mempertimbangkan lagi?"})
                        user_state[chat_id] = STATE_WAITING_FOR_CONFIRMATION  # Update state
                        update_user_state_in_db(chat_id, STATE_WAITING_FOR_CONFIRMATION)
                elif state == STATE_WAITING_FOR_CONFIRMATION:
                    if text_body == '1':  # Accept loan terms, proceed to final address confirmation
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': (
                                    f"Terima kasih atas konfirmasinya! Tim kami, {nama_am} dari {nama_kcu}, "
                                    f"akan segera mengunjungi anda pada alamat berikut:\n\n{user['alamat']}.\n\n"
                                    f"Apakah anda dapat dikunjungi di alamat tersebut? Kirim '1' jika ya, '2' untuk memperbarui alamat."
                                )
                            }
                        )
                        user_state[chat_id] = STATE_WAITING_FOR_ADDRESS_FINAL_CONFIRMATION  # Update state
                        update_user_state_in_db(chat_id, STATE_WAITING_FOR_ADDRESS_FINAL_CONFIRMATION)
                    elif text_body == '2':  # Decline loan terms
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': "Baik, apabila anda ingin melakukan rekalkulasi silahkan hubungi kami kembali. Terima kasih!"
                            }
                        )
                        user_state[chat_id] = STATE_LOAN_DECLINED  # Update state
                        update_user_state_in_db(chat_id, STATE_LOAN_DECLINED)
                    else:
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': "Silakan kirim '1' jika Anda setuju dengan pinjaman."
                            }
                        )

                elif state == STATE_WAITING_FOR_ADDRESS_FINAL_CONFIRMATION:
                    if text_body == '1':  # Address confirmed
                        loan_amount = loan_amounts.get(chat_id)
                        duration = duration_months.get(chat_id)
                        monthly_payment = calculate_monthly_payment(loan_amount, duration)
                        
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': f"Terima kasih atas konfirmasinya! Proses pengajuan pinjaman Anda telah selesai. Tim kami, {nama_am} dari {nama_kcu} akan mengunjungi anda pada alamat:\n\n{user['alamat']}.\n\n Selamat melanjutkan hari anda!"
                            }
                        )
                        user_state[chat_id] = STATE_LOAN_ACCEPTED  # Update state
                        user['acc'] = True
                        update_user_state_in_db(chat_id, STATE_LOAN_ACCEPTED, loan_amount=loan_amount, duration=duration, monthly_payment=monthly_payment)
                    elif text_body == '2':  # Address not correct
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': "Mohon kirimkan alamat terbaru Anda dalam format lengkap. Contoh: 'Jl. Sudirman No. 10, Jakarta'."
                            }
                        )
                        user_state[chat_id] = STATE_WAITING_FOR_NEW_ADDRESS  # Update state
                        update_user_state_in_db(chat_id, STATE_WAITING_FOR_NEW_ADDRESS)
                    else:
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': "Silakan kirim '1' jika alamat ini benar atau '2' untuk mengubah alamat."
                            }
                        )

                elif state == STATE_WAITING_FOR_NEW_ADDRESS:
                    # Save new address and confirm again
                    user['alamat'] = text_body
                    send_whapi_request(
                        'messages/text',
                        {
                            'to': f"{normalized_chat_id}@s.whatsapp.net",
                            'body': (
                                f"Alamat telah diperbarui menjadi:\n\n{user['alamat']}.\n\n"
                                f"Apakah anda dapat dikunjungi di alamat tersebut? Kirim '1' jika ya, '2' jika tidak."
                            )
                        }
                    )
                    user_state[chat_id] = STATE_WAITING_FOR_ADDRESS_FINAL_CONFIRMATION  # Go back to final address confirmation
                    update_user_state_in_db(chat_id, STATE_WAITING_FOR_ADDRESS_FINAL_CONFIRMATION)

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
                        'body': f"Hai, {user['nama']}! Terima kasih sudah menjadi pelanggan setia BSI. Anda terpilih untuk mengajukan pinjaman kredit pensiun. Apakah anda tertarik? (Kirim '1' jika ya; '2' jika tidak)."
                    }
                )
                
                # Update the 'called' status to True to avoid sending the message again
                user['called'] = True

                # Update user state to 'waiting_for_interest'
                user_state[chat_id] = STATE_WAITING_FOR_INTEREST
                logging.info(f"User state set to 'waiting_for_interest' for {chat_id}")
                update_user_state_in_db(chat_id, STATE_WAITING_FOR_INTEREST, called=True)
                
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

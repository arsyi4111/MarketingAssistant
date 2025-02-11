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
cur.execute('SELECT nip, "user".no_hp, nama_pensiunan, gaji, alamat, called, acc,  state, k.nama_kcu , la.nama, la.no_hp FROM "user" left join "kantor_pos" on "user".kantor_pos = "kantor_pos".kode_dirian left join list_am la on "kantor_pos".kode_kcu = la.kode_dirian  left join kcu k on "kantor_pos".kode_kcu = k.kode_kcu')
data_pengguna_records = cur.fetchall()
data_pengguna = pd.DataFrame(data_pengguna_records, columns=['nip', 'no_hp', 'nama', 'bersih', 'alamat', 'called', 'acc', 'state', 'nama_kcu', 'nama_am', 'kontak_am'])

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
STATE_WAITING_FOR_VISIT_CONFIRMATION = 10

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

def update_user_state_in_db(chat_id, state, called=None, loan_amount=None, duration=None, monthly_payment=None, address=None):
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

        if address is not None:
            query += ', alamat = %s'
            params.append(address)

        query += ' WHERE no_hp = %s'
        params.append(normalized_chat_id)

        cur.execute(query, params)
        conn.commit()

        # Requery the database to update the user variable
        cur.execute('SELECT nip, "user".no_hp, nama_pensiunan, gaji, alamat, called, acc, state, k.nama_kcu, la.nama, la.no_hp FROM "user" LEFT JOIN "kantor_pos" ON "user".kantor_pos = "kantor_pos".kode_dirian LEFT JOIN list_am la ON "kantor_pos".kode_kcu = la.kode_dirian LEFT JOIN kcu k ON "kantor_pos".kode_kcu = k.kode_kcu WHERE "user".no_hp = %s', (normalized_chat_id,))
        user_record = cur.fetchone()
        if user_record:
            user = dict(zip(['nip', 'no_hp', 'nama', 'bersih', 'alamat', 'called', 'acc', 'state', 'nama_kcu', 'nama_am', 'kontak_am'], user_record))
            return user
        return None
    except Exception as e:
        logging.error(f"Error updating user state in database: {e}")
        return None

def refresh_data_pengguna():
    global data_pengguna
    cur.execute('SELECT nip, "user".no_hp, nama_pensiunan, gaji, alamat, called, acc, state, k.nama_kcu, la.nama, la.no_hp FROM "user" left join "kantor_pos" on "user".kantor_pos = "kantor_pos".kode_dirian left join list_am la on "kantor_pos".kode_kcu = la.kode_dirian  left join kcu k on "kantor_pos".kode_kcu = k.kode_kcu')
    data_pengguna_records = cur.fetchall()
    data_pengguna = pd.DataFrame(data_pengguna_records, columns=['nip', 'no_hp', 'nama', 'bersih', 'alamat', 'called', 'acc', 'state', 'nama_kcu', 'nama_am', 'kontak_am'])

# Function to send notification to AM
def notify_am(user, loan_amount, duration, monthly_payment, visit_datetime):
    am_contact = user['kontak_am']
    am_name = user['nama_am']
    user_name = user['nama']
    user_address = user['alamat']
    user_phone = user['no_hp']
    
    message = (
        f"Kepada {am_name}, Kami ingin menginformasikan bahwa pensiunan dengan keterangan dibawah ini:\n"
        f"{user_name}\n"
        f"{user_address}\n"
        f"Nomor Telepon: {user_phone}\n\n"
        f"Tertarik untuk mengajukan pinjaman dengan detail:\n"
        f"Jumlah pinjaman : Rp. {loan_amount:,.2f}\n"
        f"Durasi pinjaman : {duration} Bulan\n"
        f"Besar cicilan : Rp. {monthly_payment:,.2f}\n"
        f"Waktu kunjungan: {visit_datetime}\n\n"
        f"Oleh karenanya, harap untuk segera dilakukan follow-up. Semoga sukses!"
    )
    
    send_whapi_request(
        'messages/text',
        {
            'to': f"{normalize_phone_number(am_contact)}@s.whatsapp.net",
            'body': message
        }
    )

    # Additional notification to AM from list_am
    additional_message = (
        f"Kepada Saudara Triyanta, AE saudara bernama {am_name} telah menerima informasi kunjungan ke calon Nasabah bernama {user_name} dengan informasi pembiayaan adalah:\n\n"
        f"Besar Limit Kredit (Plafond): Rp. {loan_amount:,.2f}\n"
        f"Jangka Waktu: {duration} Bulan\n"
        f"Cicilan: Rp. {monthly_payment:,.2f}\n\n"
        f"Semoga Saudara dapat melakukan pengawalan terhadap prospek nasabah ini.\n\n"
        f"Terimakasih. Happy Selling"
    )
    
    send_whapi_request(
        'messages/text',
        {
            'to': '6289504584688@s.whatsapp.net',
            'body': additional_message
        }
    )

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
            print("normalized u nohp:" , normalize_phone_number(data_pengguna_dict[1]['no_hp']))
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
                    max_loan = calculate_max_loan(salary)
                    max_loan_even = round_down_even(max_loan)
                    send_whapi_request(
                        'messages/text',
                        {
                            'to': f"{normalized_chat_id}@s.whatsapp.net",
                            'body': (
                                f"Salam Sejahtera.\n"
                                f"Bapak/Ibu {name}\n\n"
                                f"Kami mengucapkan terimakasih telah menjadikan Pos Indonesia sebagai pilihan dalam melakukan pembayaran Manfaat Pensiun setiap bulan.\n\n"
                                f"Bekerjasama dengan Bank SMBCI (d/h Bank BTPN) kami menawarkan produk Kredit Pensiun maksimal sebesar Rp. {max_loan_even:,.2f} dengan tenor kredit selama 60 bulan.\n\n"
                                f"Apabila Bapak/Ibu berminat, reply (balas) pesan ini 'Yes' atau 'Y'.\n\n"
                                f"Apabila tidak berminat abaikan pesan ini.\n\n"
                                f"Apabila suatu saat Bapak/Ibu ada kebutuhan, balas dengan 'Halo'."
                            )
                        }
                    )
                    user['called'] = True
                    user_state[chat_id] = STATE_WAITING_FOR_INTEREST  # Restart state
                    print(user_state[chat_id])
                    user = update_user_state_in_db(chat_id, STATE_WAITING_FOR_INTEREST, called=True)
                    refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    continue

                # Get user state (e.g., if the user has already started the loan process)
                state = user_state.get(chat_id, user['state'])
                amount = loan_amounts.get(chat_id, None)
                
                # Reset state if user was not interested or declined a previous offer
                if state in [STATE_INTEREST_DECLINED, STATE_LOAN_DECLINED]:
                    user_state.pop(chat_id, None)
                    loan_amounts.pop(chat_id, None)
                    max_loan = calculate_max_loan(salary)
                    max_loan_even = round_down_even(max_loan)
                    send_whapi_request(
                        'messages/text',
                        {
                            'to': f"{normalized_chat_id}@s.whatsapp.net",
                            'body': (
                                f"Selamat Pagi.\n"
                                f"Bapak/Ibu {name}\n\n"
                                f" Kami mengucapkan terimakasih telah menjadikan Pos Indonesia sebagai pilihan dalam melakukan pembayaran Manfaat Pensiun setiap bulan.\n\n"
                                f"Bekerjasama dengan Bank SMBCI (d/h Bank BTPN) kami menawarkan produk Kredit Pensiun maksimal sebesar Rp. {max_loan_even:,.2f} dengan tenor kredit selama 60 bulan.\n\n"
                                f"Apabila Bapak/Ibu berminat, reply (balas) pesan ini 'Yes' atau 'Y'.\n\n"
                                f"Apabila tidak berminat abaikan pesan ini.\n\n"
                                f"Apabila suatu saat Bapak/Ibu ada kebutuhan, balas dengan 'Halo'."
                            )
                        }
                    )
                    user['called'] = True
                    user_state[chat_id] = STATE_WAITING_FOR_INTEREST  # Restart state
                    user = update_user_state_in_db(chat_id, STATE_WAITING_FOR_INTEREST, called=True)
                    refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    continue

                # Send initial greeting if this is the user's first interaction
                if not user['called']:
                    max_loan = calculate_max_loan(salary)
                    max_loan_even = round_down_even(max_loan)
                    send_whapi_request(
                        'messages/text',
                        {
                            'to': f"{normalized_chat_id}@s.whatsapp.net",
                            'body': (
                                f"Selamat Pagi.\n"
                                f"Bapak/Ibu {name}\n\n"
                                f" Kami mengucapkan terimakasih telah menjadikan Pos Indonesia sebagai pilihan dalam melakukan pembayaran Manfaat Pensiun setiap bulan.\n\n"
                                f"Bekerjasama dengan Bank SMBCI (d/h Bank BTPN) kami menawarkan produk Kredit Pensiun maksimal sebesar Rp. {max_loan_even:,.2f} dengan tenor kredit selama 60 bulan.\n\n"
                                f"Apabila Bapak/Ibu berminat, reply (balas) pesan ini 'Yes' atau 'Y'.\n\n"
                                f"Apabila tidak berminat abaikan pesan ini.\n\n"
                                f"Apabila suatu saat Bapak/Ibu ada kebutuhan, balas dengan 'Halo'."
                            )
                        }
                    )
                    user['called'] = True
                    user_state[chat_id] = STATE_WAITING_FOR_INTEREST  # Save state
                    user = update_user_state_in_db(chat_id, STATE_WAITING_FOR_INTEREST, called=True)
                    refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    continue  # Stop further processing to avoid duplicate replies
                
                # Process user responses based on state
                print("State=",state)
                if state == STATE_WAITING_FOR_INTEREST:
                    if text_body in ['yes', 'y']:  # User wants to request a loan
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
                        user = update_user_state_in_db(chat_id, STATE_WAITING_FOR_LOAN_AMOUNT)
                        refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    elif text_body in ['no', 'n']:  # User doesn't want a loan
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Terima kasih! Jika Anda berubah pikiran, silakan hubungi kami."})
                        user_state[chat_id] = STATE_INTEREST_DECLINED  # Update state
                        user = update_user_state_in_db(chat_id, STATE_INTEREST_DECLINED)
                        refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    else:
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Silakan kirim 'Yes' atau 'Y' bila Anda tertarik dengan pinjaman."})
                elif state == STATE_WAITING_FOR_LOAN_AMOUNT:
                    if text_body.isdigit() and int(text_body) > 0:  # Loan amount entered
                        loan_amount = int(text_body)
                        max_loan = calculate_max_loan(salary)
                        if loan_amount > max_loan:
                            send_whapi_request(
                                'messages/text',
                                {
                                    'to': f"{normalized_chat_id}@s.whatsapp.net",
                                    'body': f"Jumlah pinjaman yang Anda masukkan melebihi batas maksimum Rp. {max_loan:,.2f}. Silakan kirim 'Halo' untuk mencoba lagi."
                                }
                            )
                            user_state.pop(chat_id, None)
                            loan_amounts.pop(chat_id, None)
                        else:
                            loan_amounts[chat_id] = loan_amount
                            min_months = calculate_min_months(loan_amount, salary)
                            send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': f"Berdasarkan jumlah yang anda inginkan sebesar Rp. {loan_amounts.get(chat_id):,.2f}, waktu pinjaman minimal adalah {min_months} Bulan. Berapa lama anda ingin mengajukan pinjaman. Kirim jumlah bulan dalam bentuk angka (maksimal 60 Bulan)."})
                            user_state[chat_id] = STATE_WAITING_FOR_LOAN_DURATION  # Update state
                            user = update_user_state_in_db(chat_id, STATE_WAITING_FOR_LOAN_DURATION)
                            refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    else:
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Jumlah pinjaman tidak valid. Silakan coba lagi."})
                elif state == STATE_WAITING_FOR_LOAN_DURATION:
                    if text_body.isdigit() and int(text_body) > 0:  # Loan duration entered
                        months = int(text_body)
                        if months > 60:
                            send_whapi_request(
                                'messages/text',
                                {
                                    'to': f"{normalized_chat_id}@s.whatsapp.net",
                                    'body': "Durasi pinjaman yang Anda masukkan melebihi batas maksimum 60 bulan. Silakan kirim 'Halo' untuk mencoba lagi."
                                }
                            )
                            user_state.pop(chat_id, None)
                            duration_months.pop(chat_id, None)
                        else:
                            loan_amount = int(loan_amounts.get(chat_id))
                            duration_months[chat_id] = months
                            monthly_payment = calculate_monthly_payment(loan_amount, months)
                            max_affordable_payment = salary * 0.40
                            
                            if monthly_payment <= max_affordable_payment:
                                send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': f"Berdasarkan jumlah yang anda inginkan Rp. {loan_amount:,.2f} dan durasi {duration_months[chat_id]} Bulan. Estimasi pembayaran bulanan anda adalah: Rp {monthly_payment:,.2f}. Jumlah cicilan total adalah Rp. {(monthly_payment*duration_months[chat_id]):,.2f} Apakah anda ingin mengajukan pinjaman dan dikunjungi oleh tim kami untuk proses lebih lanjut? Kirim 'Yes' atau 'Y' jika setuju; 'No' atau 'N' jika tidak."})
                            else:
                                send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': f"Berdasarkan jumlah yang anda inginkan Rp. {loan_amount:,.2f} dan durasi {duration_months[chat_id]} Bulan. Estimasi pembayaran bulanan anda adalah: Rp {monthly_payment:,.2f}. Sayangnya, nilai ini tidak sesuai dengan perhitungan sistem kami. Apakah Anda ingin mempertimbangkan lagi?"})
                            user_state[chat_id] = STATE_WAITING_FOR_CONFIRMATION  # Update state
                            user = update_user_state_in_db(chat_id, STATE_WAITING_FOR_CONFIRMATION)
                            refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    else:
                        send_whapi_request('messages/text', {'to': f"{normalized_chat_id}@s.whatsapp.net", 'body': "Durasi pinjaman tidak valid. Silakan coba lagi."})
                elif state == STATE_WAITING_FOR_CONFIRMATION:
                    if text_body in ['yes', 'y']:  # Accept loan terms, proceed to final address confirmation
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': (
                                    f"Terima kasih atas konfirmasinya! Tim kami, {nama_am} dari Kantor Cabang {nama_kcu}, "
                                    f"akan segera mengunjungi anda pada alamat berikut:\n\n{user['alamat']}.\n\n"
                                    f"Apakah anda dapat dikunjungi di alamat tersebut? Kirim 'Yes' atau 'Y' jika ya, 'No' atau 'N' untuk memperbarui alamat."
                                )
                            }
                        )
                        user_state[chat_id] = STATE_WAITING_FOR_ADDRESS_FINAL_CONFIRMATION  # Update state
                        user = update_user_state_in_db(chat_id, STATE_WAITING_FOR_ADDRESS_FINAL_CONFIRMATION)
                        refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    elif text_body in ['no', 'n']:  # Decline loan terms
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': "Baik, apabila anda ingin melakukan rekalkulasi silahkan hubungi kami kembali. Terima kasih!"
                            }
                        )
                        user_state[chat_id] = STATE_LOAN_DECLINED  # Update state
                        user = update_user_state_in_db(chat_id, STATE_LOAN_DECLINED)
                        refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    else:
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': "Silakan kirim 'Yes' atau 'Y' jika Anda setuju dengan pinjaman."
                            }
                        )

                elif state == STATE_WAITING_FOR_ADDRESS_FINAL_CONFIRMATION:
                    if text_body in ['yes', 'y']:  # Address confirmed
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': "Terima kasih! Kapan Anda ingin dikunjungi? Mohon kirimkan tanggal dan waktu dalam format DD-MM-YYYY HH:MM."
                            }
                        )
                        user_state[chat_id] = STATE_WAITING_FOR_VISIT_CONFIRMATION  # Update state
                        user = update_user_state_in_db(chat_id, STATE_WAITING_FOR_VISIT_CONFIRMATION)
                        refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    elif text_body in ['no', 'n']:  # Address not correct
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': "Mohon kirimkan alamat terbaru Anda dalam format lengkap. Contoh: 'Jl. Sudirman No. 10, Jakarta'."
                            }
                        )
                        user_state[chat_id] = STATE_WAITING_FOR_NEW_ADDRESS  # Update state
                        user = update_user_state_in_db(chat_id, STATE_WAITING_FOR_NEW_ADDRESS)
                        refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    else:
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': "Silakan kirim 'Yes' atau 'Y' jika alamat ini benar atau 'No' atau 'N' untuk mengubah alamat."
                            }
                        )
                elif state == STATE_WAITING_FOR_NEW_ADDRESS:
                    # Save new address and confirm again
                    user['alamat'] = text_body
                    user = update_user_state_in_db(chat_id, STATE_WAITING_FOR_ADDRESS_FINAL_CONFIRMATION, address=text_body)
                    send_whapi_request(
                        'messages/text',
                        {
                            'to': f"{normalized_chat_id}@s.whatsapp.net",
                            'body': (
                                f"Alamat telah diperbarui menjadi:\n\n{user['alamat']}.\n\n"
                                f"Apakah anda dapat dikunjungi di alamat tersebut? Kirim 'Yes' atau 'Y' jika ya, 'No' atau 'N' jika tidak."
                            )
                        }
                    )
                    user_state[chat_id] = STATE_WAITING_FOR_ADDRESS_FINAL_CONFIRMATION  # Go back to final address confirmation
                    refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                elif state == STATE_WAITING_FOR_VISIT_CONFIRMATION:
                    try:
                        visit_datetime = pd.to_datetime(text_body, format='%d-%m-%Y %H:%M')
                        loan_amount = loan_amounts.get(chat_id)
                        duration = duration_months.get(chat_id)
                        monthly_payment = calculate_monthly_payment(loan_amount, duration)
                        
                        # Call notify_am function with visit datetime
                        notify_am(user, loan_amount, duration, monthly_payment, visit_datetime)
                        
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': f"Terima kasih! Tim kami akan mengunjungi Anda pada {visit_datetime}. Selamat melanjutkan hari Anda!"
                            }
                        )
                        user_state[chat_id] = STATE_LOAN_ACCEPTED  # Update state
                        user['acc'] = True
                        user = update_user_state_in_db(chat_id, STATE_LOAN_ACCEPTED, loan_amount=loan_amount, duration=duration, monthly_payment=monthly_payment)
                        refresh_data_pengguna()  # Refresh data_pengguna after updating the database
                    except ValueError:
                        send_whapi_request(
                            'messages/text',
                            {
                                'to': f"{normalized_chat_id}@s.whatsapp.net",
                                'body': "Format tanggal dan waktu tidak valid. Mohon kirimkan dalam format DD-MM-YYYY HH:MM."
                            }
                        )

        return 'Ok', 200
    except Exception as e:
        logging.error(f"Error handling message: {e}")
        return str(e), 500

@app.route('/send_initiation', methods=['GET'])
def send_initiation_message():
    try:
        # Convert data_pengguna DataFrame to a list of dictionaries
        data_pengguna_dict = data_pengguna.to_dict('records')

        for user in data_pengguna_dict:
            if not user['called']:
                chat_id = f"{normalize_phone_number(user['no_hp'])}@s.whatsapp.net"
                max_loan = calculate_max_loan(user['bersih'])
                max_loan_even = round_down_even(max_loan)

                # Send initial message to user
                send_whapi_request(
                    'messages/text',
                    {
                        'to': chat_id,
                        'body': (
                            f"Salam Sejahtera.\n"
                            f"Bapak/Ibu {user['nama']}\n\n"
                            f" Kami mengucapkan terimakasih telah menjadikan Pos Indonesia sebagai pilihan dalam melakukan pembayaran Manfaat Pensiun setiap bulan.\n\n"
                            f"Bekerjasama dengan Bank SMBCI (d/h Bank BTPN) kami menawarkan produk Kredit Pensiun maksimal sebesar Rp. {max_loan_even:,.2f} dengan tenor kredit selama 60 bulan.\n\n"
                            f"Apabila Bapak/Ibu berminat, reply (balas) pesan ini 'Yes' atau 'Y'.\n\n"
                            f"Apabila tidak berminat abaikan pesan ini.\n\n"
                            f"Apabila suatu saat Bapak/Ibu ada kebutuhan, balas dengan 'Halo'."
                        )
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

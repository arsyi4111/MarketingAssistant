from flask import Flask, request, jsonify
import requests
from requests_toolbelt.multipart.encoder import MultipartEncoder
import os
from dotenv import load_dotenv
import math

load_dotenv()  # Load environment variables from a .env file

app = Flask(__name__)

# Sample 'data_pengguna' DataFrame (replace with your actual database or data source)
data_pengguna = [
    {'no_hp': '1234567890', 'nama': 'John Doe', 'bersih': 5000000, 'called': False, 'acc': False},
    {'no_hp': '0987654321', 'nama': 'Jane Smith', 'bersih': 7000000, 'called': False, 'acc': False}
]

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

# Function to send WhatsApp messages using whapi
def send_whapi_request(endpoint, params=None, method='POST'):
    headers = {
        'Authorization': f"Bearer {os.getenv('TOKEN')}"
    }
    url = f"{os.getenv('API_URL')}/{endpoint}"
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
    print('Whapi response:', response.json())
    return response.json()

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
            if message.get('from_me'):
                continue
            chat_id = message.get('chat_id')
            text = message.get('text', {}).get('body', '').strip()

            # Find user based on phone number
            user = next((u for u in data_pengguna if u['no_hp'] == chat_id), None)
            
            if user:
                # Mark as called when a message is received
                user['called'] = True
                name = user['nama']
                salary = user['bersih']
                
                if text == '1':  # User wants to request a loan
                    send_whapi_request('messages/text', {'to': chat_id, 'body': f"Hello, {name}! Based on your salary of Rp {salary:,}, we can help you with a loan. Please type the loan amount."})
                elif text.isdigit() and int(text) > 0:  # Loan amount entered
                    loan_amount = int(text)
                    min_months = calculate_min_months(loan_amount, salary)
                    send_whapi_request('messages/text', {'to': chat_id, 'body': f"The minimum duration for repayment is {min_months} months based on your salary and requested amount. Please type the number of months you want for repayment."})
                elif text.isdigit() and int(text) >= min_months:  # Loan duration entered
                    months = int(text)
                    monthly_payment = calculate_monthly_payment(loan_amount, months)
                    max_affordable_payment = salary * 0.40
                    
                    if monthly_payment <= max_affordable_payment:
                        send_whapi_request('messages/text', {'to': chat_id, 'body': f"Your estimated monthly payment is: Rp {monthly_payment:,.2f}. Is this acceptable? Type 1 to accept, 2 to decline."})
                    else:
                        send_whapi_request('messages/text', {'to': chat_id, 'body': f"Your estimated monthly payment is: Rp {monthly_payment:,.2f}. Unfortunately, this exceeds 40% of your salary, which is Rp {max_affordable_payment:,.2f}. Would you like to reconsider?"})
                elif text == '1':  # Accept loan
                    user['acc'] = True
                    send_whapi_request('messages/text', {'to': chat_id, 'body': "Thank you for accepting the loan! We will proceed with the next steps."})
                elif text == '2':  # Decline loan
                    send_whapi_request('messages/text', {'to': chat_id, 'body': "You have declined the loan. Thank you for your time."})
                else:
                    send_whapi_request('messages/text', {'to': chat_id, 'body': "Please follow the instructions. Type 1 to request a loan."})

        return 'Ok', 200
    except Exception as e:
        print(e)
        return str(e), 500


@app.route('/', methods=['GET'])
def index():
    return 'Bot is running'


if __name__ == '__main__':
    set_hook()
    port = os.getenv('PORT') or (443 if os.getenv('BOT_URL', '').startswith('https:') else 80)
    app.run(port=port, debug=True)

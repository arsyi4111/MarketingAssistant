import math
import pandas as pd

# Sample 'data_pengguna' DataFrame with name, phone number, salary, called, and acc columns
data_pengguna = pd.DataFrame({
    'no_hp': ['1234567890', '0987654321'],  # Example phone numbers
    'nama': ['John Doe', 'Jane Smith'],  # Example names
    'bersih': [5000000, 7000000],  # Example salaries (gaji)
    'called': [False, False],  # Default to False (not called)
    'acc': [False, False]  # Default to False (not accepted)
})

# Dictionary to store users' credit amount, months, and other info
user_data = {}

# A function to calculate the minimum number of months based on salary and amount
def calculate_min_months(amount, salary):
    # Example: The interest rate is fixed at 10% per year (for simplicity)
    annual_interest_rate = 0.10
    monthly_interest_rate = annual_interest_rate / 12
    
    # Monthly payment formula: P = [r * A] / [1 - (1 + r)^-n]
    # To find the minimum months, we rearrange the formula and solve for 'n'
    # We know the max affordable payment = 40% of salary
    max_affordable_payment = salary * 0.40
    n = math.log(max_affordable_payment / (max_affordable_payment - (monthly_interest_rate * amount))) / math.log(1 + monthly_interest_rate)
    
    # Round up to the nearest whole number of months, as we can't have fractional months
    min_months = math.ceil(n)
    return min_months

# A function to calculate the monthly payment based on amount and months
def calculate_monthly_payment(amount, months):
    annual_interest_rate = 0.10
    monthly_interest_rate = annual_interest_rate / 12
    
    # Monthly payment formula
    numerator = monthly_interest_rate * amount * (1 + monthly_interest_rate)**months
    denominator = (1 + monthly_interest_rate)**months - 1
    monthly_payment = numerator / denominator
    return monthly_payment

# Simulate the interaction with Python input
def simulate_bot_interaction():
    # Simulate interaction with the user
    phone_number = input("Enter your phone number: ")
    
    user_data_row = data_pengguna[data_pengguna['no_hp'] == phone_number]
    if not user_data_row.empty:
        # Update called to True when the user interacts with the bot
        data_pengguna.loc[data_pengguna['no_hp'] == phone_number, 'called'] = True

        name = user_data_row.iloc[0]['nama']
        salary = user_data_row.iloc[0]['bersih']  # Get the salary (gaji)
        
        print(f"Hello, {name}! Based on your salary of Rp {salary:,}, we can help you with a loan.")

        # Ask for the amount they want to borrow
        amount = int(input(f"How much would you like to borrow (in Rupiah): "))
        user_data[phone_number] = {'amount': amount}  # Store amount info

        # Calculate the minimum months based on the salary and loan amount
        min_months = calculate_min_months(amount, salary)
        print(f"The minimum duration for repayment is {min_months} months based on your salary and requested amount.")

        # Ask for the number of months the user wants to take
        months = int(input(f"How many months would you like for repayment (minimum {min_months} months): "))
        
        # Store the chosen months in the user data
        user_data[phone_number]['months'] = months

        # Calculate the monthly payment based on the amount and months
        monthly_payment = calculate_monthly_payment(amount, months)
        
        # Check if the monthly installment is affordable (<= 40% of salary)
        max_affordable_payment = salary * 0.40
        if monthly_payment <= max_affordable_payment:
            print(f"Your estimated monthly payment is: Rp {monthly_payment:,.2f}.")
            print("This is within your affordable limit.")
            
            # Ask for confirmation to proceed
            accept = input("Do you accept this loan? (yes/no): ").lower()
            
            if accept == 'yes':
                # Update acc to True if the user accepts the loan
                data_pengguna.loc[data_pengguna['no_hp'] == phone_number, 'acc'] = True
                print("Thank you for accepting the loan! We will proceed with the next steps.")
            else:
                print("You have declined the loan. Thank you for your time.")
        else:
            print(f"Your estimated monthly payment is: Rp {monthly_payment:,.2f}.")
            print(f"Unfortunately, this exceeds 40% of your salary, which is Rp {max_affordable_payment:,.2f}.")
            print("You may want to reconsider the loan amount or duration.")
    else:
        print("Sorry, your phone number is not found in our records. Please contact us for further assistance.")

# Run the simulation
simulate_bot_interaction()

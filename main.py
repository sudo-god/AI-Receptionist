import os
from urllib.request import Request
from dotenv import load_dotenv
import logging
import logging.config
import yaml
from pymongo.mongo_client import MongoClient
from flask import Flask, request, jsonify, render_template
from datetime import datetime
import certifi
import json
import google.generativeai as genai
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build


load_dotenv()
MONGODB_URI = os.environ['MONGODB_URI']
GEMINI_API_KEY = os.environ['GEMINI_API_KEY']

with open("config/logging.yml", "r") as logging_config_file:
    logging.config.dictConfig(yaml.load(logging_config_file, Loader=yaml.FullLoader))
main_logger = logging.getLogger('main')

app = Flask(__name__)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash-exp")


def connect_to_db(uri: str) -> MongoClient:
    # Create a new client and connect to the server
    client = MongoClient(uri,
                        #  tls=True,
                        #  tlsCertificateKeyFile='./config/X509-cert-6143731158356626028.pem',
                         ssl_ca_certs=certifi.where())

    # Send a ping to confirm a successful connection
    try:
        client.admin.command('ping')
        main_logger.info("Pinged your deployment. You successfully connected to MongoDB!")
        return client
    except Exception as e:
        main_logger.info(f"Failed to connect to MongoDB. Check your connection.{e}")
        raise e

# Connect to the database and setup collections
database_client = connect_to_db(MONGODB_URI)
database = database_client['spaceo']

business_data = database['business_data']
calendar = database['calendar']
customer_queries = database["customer_queries"]
custom_responses = database["custom_responses"]


# ============ Task 1. Business Information Integration ============
@app.route('/get_business_info', methods=['GET'])
def get_info():
    customer_prompt = request.args.get('prompt', None)
    intent = request.args.get('intent', None)
    if customer_prompt is None:
        return jsonify({"message": "prompt parameter is required"}), 400

    engineered_prompt = f"""
        You are an assistant that generates MongoDB aggregation pipeline for python pymongo library to be used directly in find() method based on natural language descriptions.
        The MongoDB collection has the following structure:
        - `name`: String
        - `operating_hours`: String
        - `contact_info`: String
        - `services`: Array of objects, each with the following structure `name`: String, `description`: String, and `price`: Double.

        Convert the following natural language query into a MongoDB aggregation pipeline, do not include any additional information, comments, function calls etc, and make sure that you use double quotes, and fetch all the fields:
        "{customer_prompt}"
    """
    main_logger.info(f"Engineered Prompt: {engineered_prompt}")
    
    generated_query = model.generate_content(engineered_prompt).text
    generated_query = generated_query[generated_query.find("["):generated_query.rfind("]")+1]
    main_logger.debug(f"Generated Query: {generated_query}")

    generated_query = json.loads(generated_query)
    raw_results = list(business_data.aggregate(generated_query))
    main_logger.debug(f"Query Results: {raw_results}")
    service_response_template = custom_responses.find_one({"query_type": "service"})["template"]
    operating_hours_response_template = custom_responses.find_one({"query_type": "operating_hours"})["template"]
    contact_information_response_template = custom_responses.find_one({"query_type": "contact_information"})["template"]
    
    custom_format_results = []
    for result in raw_results:
        try:
            result["_id"] = str(result["_id"])
        except Exception:
            pass
        if "service" in intent and service_response_template != "":
            if not isinstance(result["services"], list):
                result["services"] = [result["services"]]
            for service in result["services"]:
                custom_format_results.append(service_response_template.replace("{business_name}", result["name"]).replace("{service_name}", service["name"]).replace("{price}", str(service["price"])).replace("{description}", service["description"]))
        if "operating_hours" in intent and operating_hours_response_template != "":
            custom_format_results.append(operating_hours_response_template.replace("{business_name}", result["name"]).replace("{operating_hours}", result["operating_hours"]))
        if "contact_information" in intent and contact_information_response_template != "":
            custom_format_results.append(contact_information_response_template.replace("{business_name}", result["name"]).replace("{contact_info}", result["contact_info"]))

    final_result = custom_format_results if custom_format_results else raw_results
    main_logger.info(f"Return response: {final_result}")
    log_interaction = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "customer_prompt": customer_prompt,
        "generated_MQL": generated_query,
        "result": result
    }
    customer_queries.insert_one(log_interaction)
    return jsonify(list(final_result)), 200


# ============ Task 2. Appointment Scheduling ============
@app.route('/schedule', methods=['POST'])
def schedule():
    try:
        data = None
        data = request.json.get("data", None)
    except Exception:
        customer_prompt = request.args.get('prompt', None)
    except Exception as e:
        return jsonify({"message": f"No request body found. Error: {e}"}), 400
    aggregate_pipeline = [
        { "$unwind": "$available_slots" },
        { "$match": { "available_slots.is_booked": False } },
        {
            "$group": {
                "_id": "$_id",
                "date": {"$first":"$date"}, 
                "available_slots": {"$push":"$available_slots"}
            }
        }
    ]
    available_slots = list(calendar.aggregate(aggregate_pipeline))
    
    if data is None or not isinstance(data, dict):
        if isinstance(customer_prompt, str):
            engineered_prompt = f"""
                You are an AI receptionist that can answer queries related to appointment scheduling.
                The AI receptionist can handle the following intents:
                - checking_slot_availability
                - is_booking_slot
                - None

                Identify the intent of the following prompt, just specify a list of intents:
                "{customer_prompt}"
            """
            main_logger.info(f"Engineered Prompt: {engineered_prompt}")
            generated_response = model.generate_content(engineered_prompt).text
            main_logger.debug(f"Generated Response: {generated_response}")
            if "checking_slot_availability" in generated_response:
                return jsonify({"message": f"Available slots: {available_slots}"}), 200
            
            engineered_prompt = f"Extract the customer name, attendee_emails, service, start_time in YYYY-MM-DD HH:MM format from {customer_prompt}, into a json object."
            extracted_data = model.generate_content(engineered_prompt).text
            main_logger.debug(f"Extracted data: {extracted_data}")
            data = json.loads(extracted_data[extracted_data.find("{"):extracted_data.rfind("}")+1])
            main_logger.info(f"Extracted appointment information: {data}")
        else:
            return jsonify({"message": "Required field (data) from request body, or parameter (prompt) is missing or has invalid format. Accepted format json for \"data\", and string for \"prompt\"."}), 400
        
    customer_name = data.get("customer_name", None)
    attendee_emails = data.get("attendee_emails", None)
    preferred_service = data.get("service", None)
    requested_start_dt = data.get("start_time", None)

    if any([customer_name is None, 
            attendee_emails is None or not attendee_emails,
            preferred_service is None, 
            requested_start_dt is None]):
        return jsonify({"message": "Required fields (name, email, service, start_time in YYYY-MM-DD HH:MM) are missing"}), 400
    try:
        requested_start_dt = datetime.strptime(requested_start_dt, "%Y-%m-%d %H:%M")
    except Exception as e:
        main_logger.info(f"Error: {e}")
        return jsonify({"message": "start_time format is invalid"}), 400

    date_str = requested_start_dt.strftime("%Y-%m-%d")
    start_time = requested_start_dt.strftime("%H:%M")
    
    main_logger.info(f"Available slots: {available_slots}")
    if calendar.find_one({"date": date_str, "available_slots": {"$elemMatch": {"start_time": start_time, "is_booked": True}}}):
        return jsonify({"message": f"Requested date and time is already booked. Available slots: {available_slots}"}), 409
    elif not calendar.find_one({"date": date_str, "available_slots": {"$elemMatch": {"start_time": start_time}}}):
        return jsonify({"message": f"Requested date and time is not available. Available slots: {available_slots}"}), 404
    
    slot_end_time = None
    for day in available_slots:
        if day["date"] == date_str:
            for slot in day["available_slots"]:
                if slot["start_time"] == start_time:
                    slot_end_time = slot["end_time"]
                    break
            break
    main_logger.info(f"Slot end time: {slot_end_time}")
    calendar.update_one({"date": date_str, "available_slots": {"$elemMatch": {"start_time": start_time, "is_booked": False}}}, 
                        {"$set": {"available_slots.$.is_booked": True, 
                                  "available_slots.$.customer_name": customer_name, 
                                  "available_slots.$.service": preferred_service}})
    success_response = "Successfully booked appointment."
    custom_success_response = custom_responses.find_one({"query_type": "appointment_scheduling"})["template"]
    if custom_success_response:
        success_response = custom_success_response.replace("{customer_name}", customer_name).replace("{service}", preferred_service).replace("{date}", date_str).replace("{start_time}", start_time)
    create_gcal_event(preferred_service, customer_name, attendee_emails, date_str, start_time, slot_end_time)
    return jsonify({"message": success_response}), 200


# ============= Task 3. AI-Powered Customer Interaction =============
@app.route('/chat', methods=['GET'])
def chat():
    customer_prompt = request.args.get('prompt', None)
    if customer_prompt is None:
        return jsonify({"message": "A prompt to the AI receptionist is required"}), 400
    
    engineered_prompt = f"""
        You are an AI receptionist that can answer queries related to business information and appointment scheduling.
        The AI receptionist can handle the following intents:
        - service
        - operating_hours
        - appointment_scheduling
        - contact_information
        - None

        Identify the intent of the following prompt, just specify a list of intents:
        "{customer_prompt}"
    """
    main_logger.info(f"Engineered Prompt: {engineered_prompt}")
    generated_response = model.generate_content(engineered_prompt).text
    main_logger.debug(f"Generated Response: {generated_response}")

    intent = []
    if "service" in generated_response:
        intent.append("service")
    if "operating_hours" in generated_response:
        intent.append("operating_hours")
    if "contact_information" in generated_response:
        intent.append("contact_information")


    main_logger.info(f"Intent: {intent}")
    if intent:
        return app.test_client().get('/get_business_info', query_string={'prompt': customer_prompt, 'intent': ",".join(intent)})
    elif "appointment_scheduling" in generated_response:
        return app.test_client().post('/schedule', query_string={'prompt': customer_prompt})
    else:
        return jsonify({"message": "Intent not recognized"}), 400


# ============= Task 4. Basic Admin Interface =============
@app.route('/admin_interface', methods=['GET', 'POST'])
def admin_interface():
    if request.method == 'POST':
        query_type = request.form.get('query_type')
        template = request.form.get('template')
        custom_responses.update_one({"query_type": query_type}, {"$set": {"template": template}}, upsert=True)
    all_responses = list(custom_responses.find())
    return render_template('admin_interface.html', responses=all_responses)


# ============= Task 5. Advanced Features (Bonus) =============

SCOPES = ['https://www.googleapis.com/auth/calendar']

def authenticate_google_calendar():
    # Load credentials or initiate OAuth flow
    credentials = None
    token_file = 'token.json'
    if os.path.exists(token_file):
        credentials = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request(credentials.token_uri+credentials.refresh_token, method='POST'))
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            credentials = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(token_file, 'w') as token:
            token.write(credentials.to_json())

    service = build('calendar', 'v3', credentials=credentials)
    return service

def create_gcal_event(service_name: str, customer_name: str, attendee_emails: str, date: str, start_time: str, end_time: str):
    service = authenticate_google_calendar()
    attendees = [{"email": email} for email in attendee_emails]
    event = {
        'summary': service_name,
        'description': f"Appointment with {customer_name}",
        'attendees': attendees,
        'start': {
            'dateTime': f"{date}T{start_time}:00",
            'timeZone': 'America/New_York'
        },
        'end': {
            'dateTime': f"{date}T{end_time}:00",
            'timeZone': 'America/New_York'
        }
    }
    event_result = service.events().insert(calendarId='primary', sendNotifications=True, body=event).execute()
    return event_result.get('htmlLink', None)


if __name__ == '__main__':
    app.run(debug=True)


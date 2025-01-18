import asyncio
from dataclasses import dataclass
from datetime import datetime
import json
import os
from typing import List
from dotenv import load_dotenv
from pydantic_ai import Agent, RunContext, ModelRetry
from pydantic_ai.models.gemini import GeminiModel
import logfire
import logging
import logging.config
import yaml
from flask import Flask, request, jsonify, render_template
from pymongo.mongo_client import MongoClient
import certifi

from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build



load_dotenv()
MONGODB_URI = os.environ['MONGODB_URI']

logfire.configure()
with open("config/logging.yml", "r") as logging_config_file:
    logging.config.dictConfig(yaml.load(logging_config_file, Loader=yaml.FullLoader))

main_logger = logging.getLogger('main')

app = Flask(__name__)

model = GeminiModel('gemini-2.0-flash-exp')
loop = asyncio.new_event_loop()


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
@dataclass
class Intent:
    intention: List[str]
    service_response_template = custom_responses.find_one({"query_type": "service"})["template"]
    operating_hours_response_template = custom_responses.find_one({"query_type": "operating_hours"})["template"]
    contact_info_response_template = custom_responses.find_one({"query_type": "contact_information"})["template"]
    appointment_response_template = custom_responses.find_one({"query_type": "appointment_scheduling"})["template"]

business_info_agent = Agent(
    model=model,
    system_prompt=(
        'You are an assistant that generates MongoDB aggregation pipeline for python pymongo library to be used directly in find() method based on natural language descriptions.'
        'The MongoDB collection has the following structure:'
        '- name: String'
        '- operating_hours: String'
        '- contact_info: String'
        '- services: Array of objects, each with the following structure name: String, description: String, and price: Double.'
        'Fetch all the fields, and make sure that you use double quotes for fields.'
        'Convert the natural language query provided to you into a MongoDB aggregation pipeline, then pass it to the `run_query` tool, and log the interaction.'
    ),
    deps_type=Intent,
    retries=5,
)

validator_agent = Agent(
    model=model,
    system_prompt=(
        'You are an assistant that validates the final output of a given prompt.'
        'Valid means that the output is relevant to the prompt'
        'Just indicate True for valid results and False for invalid results.'
    ),
    result_type=bool,
    retries=3,
)


@app.route('/get_business_info', methods=['GET'])
def get_business_info():
    asyncio.set_event_loop(loop)

    original_prompt = request.args.get('prompt', None)
    intent = request.args.get('intent', '').split(',')
    if original_prompt is None:
        return jsonify({"message": "prompt parameter is required"}), 400
    
    try:
        result = business_info_agent.run_sync(original_prompt, deps=Intent(intention=intent))
        return result.data, 200
    except Exception as e:
        main_logger.error(f"Error: {e}")
        try:
            error_body = json.loads(e.body)
            error_message = error_body.get('error', {}).get('message', 'Unknown error')
        except Exception:
            error_message = str(e)
        return jsonify(f"Failed to {intent}. {error_message}"), 500


@business_info_agent.tool
def run_query(ctx: RunContext[Intent], query_str: str):
    ''' Parse the query_str, run the parsed query and return the results in json format.
    '''
    try:
        generated_query = query_str[query_str.find("["):query_str.rfind("]")+1]
        generated_query = json.loads(generated_query)
        main_logger.info(f"Generated Query: {generated_query}")

        raw_MQL_results = list(business_data.aggregate(generated_query))
        main_logger.info(f"Query Raw Results: {raw_MQL_results}")
        # final_output = []
        for result in raw_MQL_results:
            try:
                result["_id"] = str(result["_id"])
            except Exception:
                pass
            # for intent in ctx.deps.intention:
            #     template = custom_responses.find_one({"query_type": intent})["template"]
            #     for service in result["services"]:
            #         new_response = template.replace("{business_name}", result["name"])\
            #                                 .replace("{service_name}", service["name"])\
            #                                 .replace("{service_price}", str(service["price"]))\
            #                                 .replace("{service_description}", service["description"])\
            #                                 .replace("{operating_hours}", result["operating_hours"])\
            #                                 .replace("{contact_info}", result["contact_info"])
            #         final_output.append(new_response)

        # main_logger.info(f"Final Results: {final_output}")
        return raw_MQL_results
    except Exception as e:
        raise ModelRetry(f"Failed to run the query. {e}")


@business_info_agent.tool_plain(retries=3)
def log_interaction(original_prompt: str, generated_query: str, raw_MQL_results: str, final_output: str) -> None:
    ''' Log the interaction between the customer and the AI model.
    '''
    interaction = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "original_prompt": original_prompt,
        "generated_MQL": generated_query,
        "MQL_result": raw_MQL_results,
        "final_output": final_output
    }
    main_logger.info(f"Log Interaction: {interaction}")
    customer_queries.insert_one(interaction)


# ============ Task 2. Appointment Scheduling ============
appointment_intent_agent = Agent(
    model=model,
    system_prompt=(
            'You are an AI receptionist that can answer queries related to appointment scheduling.'
            'The AI receptionist can handle the following intents:'
            '- check_slot_availability'
            '- is_booking_slot'
            '- None'
            'Identify the intent of the prompt, just specify an intent'
    ),
    result_type=str,
    retries=3,
)


@dataclass
class ScheduleData:
    intent: str
    appointment_info: dict | None


slot_info_agent = Agent(
    model=model,
    system_prompt=(
        'You are an assistant that generates MongoDB aggregation pipeline for python pymongo library to be used directly in find() method based on natural language descriptions.'
        'The MongoDB collection has the following structure:'
        '- date: String (YYYY-MM-DD)'
        '- available_slots: List[Object] with the following structure start_time: String, end_time: String, is_booked: Boolean, customer_name: String, service: String'
        'Fetch all the fields, and make sure that you use double quotes for fields.'
        'Convert the natural language query into a MongoDB aggregation pipeline, then call `check_slot` tool, and log the interaction.'
    ),
    deps_type=ScheduleData,
    retries=5,
)

helper_agent = Agent(model=model)

@app.route('/schedule', methods=['POST'])
def schedule():
    asyncio.set_event_loop(loop)

    try:
        data = None
        data = request.json.get("data", None)
    except Exception:
        original_prompt = request.args.get('prompt', None)
    except Exception as e:
        return jsonify({"message": f"No request body found. Error: {e}"}), 400
    
    try:
        intent = appointment_intent_agent.run_sync(original_prompt).data.strip()
        main_logger.info(f"Scheduling intent: {intent}")
        result = slot_info_agent.run_sync(original_prompt, deps=ScheduleData(intent=intent, appointment_info=data))
        return result.data, 200
    except Exception as e:
        main_logger.error(f"Error: {e}")
        try:
            error_body = json.loads(e.body)
            error_message = error_body.get('error', {}).get('message', 'Unknown error')
        except Exception:
            error_message = str(e)
        return jsonify(f"Failed to {intent}. {error_message}"), 500


@slot_info_agent.tool
async def check_slot(ctx: RunContext[ScheduleData], generated_query: str, original_prompt: str):
    ''' Parse and run the generated query and return the results in json format.

    Args:
        ctx (RunContext): The context object containing the dependencies.
        generated_query (str): The generated query string.
        original_prompt (str): The original prompt.
    '''
    try:
        generated_query = generated_query[generated_query.find("["):generated_query.rfind("]")+1]
        generated_query = json.loads(generated_query)
        available_slots = list(calendar.aggregate(generated_query))

        if ctx.deps.intent == "check_slot_availability":
            engineered_prompt = (
                'You are an agent that takes in a JSON object and responds in natural language containing the same information.'
                'Ignore ObjectId and present the information in a human-readable format with proper line breaks where needed.'
                f'Here is the available slots: {available_slots}'
            )
            result = await helper_agent.run(engineered_prompt)
            return result.data

        data = ctx.deps.appointment_info
        if data is None or not isinstance(data, dict):
            engineered_prompt = f"Extract the customer_name, service, start_time in YYYY-MM-DD HH:MM format, and emails from {original_prompt}, into a json object."
            extracted_data = await helper_agent.run(engineered_prompt)
            extracted_data = extracted_data.data
            main_logger.info(f"Extracted data: {extracted_data}")
            data = json.loads(extracted_data[extracted_data.find("{"):extracted_data.rfind("}")+1])
            main_logger.info(f"Extracted appointment information: {data}")

        customer_name = data.get("customer_name", None)
        emails = data.get("emails", None)
        preferred_service = data.get("service", None)
        requested_start_dt = data.get("start_time", None)

        if any([customer_name is None, 
                emails is None or not emails,
                preferred_service is None, 
                requested_start_dt is None]):
            return {"Status_400": "Required fields (name, email, service, start_time in YYYY-MM-DD HH:MM) are missing"}
        try:
            requested_start_dt = datetime.strptime(requested_start_dt, "%Y-%m-%d %H:%M")
        except Exception as e:
            main_logger.info(f"Error: {e}")
            return {"Status_400": "start_time format is invalid"}

        date_str = requested_start_dt.strftime("%Y-%m-%d")
        start_time = requested_start_dt.strftime("%H:%M")
        
        main_logger.info(f"Available slots: {available_slots}")
        if calendar.find_one({"date": date_str, "available_slots": {"$elemMatch": {"start_time": start_time, "is_booked": True}}}):
            return {"Status_409": f"Requested date and time is already booked. Available slots: {available_slots}"}
        elif not calendar.find_one({"date": date_str, "available_slots": {"$elemMatch": {"start_time": start_time}}}):
            return {"Status_404": f"Requested date and time is not available. Available slots: {available_slots}"}
        
        slot_end_time = None
        for day in available_slots:
            if day["date"] == date_str:
                for slot in day["available_slots"]:
                    if slot["start_time"] == start_time:
                        slot_end_time = slot["end_time"]
                        break
                break

        calendar.update_one({"date": date_str, "available_slots": {"$elemMatch": {"start_time": start_time, "is_booked": False}}}, 
                            {"$set": {"available_slots.$.is_booked": True, 
                                      "available_slots.$.customer_name": customer_name, 
                                      "available_slots.$.service": preferred_service}})
        success_response = "Successfully booked appointment."
        custom_success_response = custom_responses.find_one({"query_type": "appointment_scheduling"})["template"]
        if custom_success_response:
            success_response = custom_success_response.replace("{customer_name}", customer_name).replace("{service}", preferred_service).replace("{date}", date_str).replace("{start_time}", start_time)
        create_gcal_event(preferred_service, customer_name, emails, date_str, start_time, slot_end_time)
        return {"Status_200": success_response}
    except Exception as e:
        raise ModelRetry(f"Failed to book slot. {e}")


# ============= Task 3. AI-Powered Customer Interaction =============
chat_agent = Agent(
    model=model,
    system_prompt=(
        'You are an AI receptionist that can answer queries related to business information and appointment scheduling.'
        'The AI receptionist can handle the following intents:'
        '- service'
        '- operating_hours'
        '- appointment_scheduling'
        '- contact_information'
        '- None'
        'Identify the intent of the prompt from one of the intents above, just specify a list of intents.'
    ),
    result_type=List[str]
)

@app.route('/chat', methods=['GET'])
def chat():
    asyncio.set_event_loop(loop)
    original_prompt = request.args.get('prompt', None)
    if original_prompt is None:
        return jsonify({"message": "A prompt to the AI receptionist is required"}), 400
    
    intent = "handle prompt"
    try:
        intent = chat_agent.run_sync(original_prompt).data
        main_logger.info(f"Intent: {intent}")

        if None in intent:
            return jsonify({"message": "Intent not recognized"}), 400
        elif "appointment_scheduling" in intent:
            # return app.test_client().post('/schedule', query_string={'prompt': original_prompt})
            intent = appointment_intent_agent.run_sync(original_prompt).data.strip()
            main_logger.info(f"Scheduling intent: {intent}")
            try:
                result = slot_info_agent.run_sync(original_prompt, deps=ScheduleData(intent=intent, appointment_info=None))
                return result.data, 200
            except Exception as e:
                main_logger.error(f"Error: {e}")
                try:
                    error_body = json.loads(e.body)
                    error_message = error_body.get('error', {}).get('message', 'Unknown error')
                except Exception:
                    error_message = str(e)
                return jsonify(f"Failed to {intent}. {error_message}"), 500
        else:
            result = business_info_agent.run_sync(original_prompt, deps=Intent(intention=intent))
            return jsonify(result.data), 200
    except Exception as e:
        main_logger.error(f"Error: {e}")
        try:
            error_body = json.loads(e.body)
            error_message = error_body.get('error', {}).get('message', 'Unknown error')
        except Exception:
            error_message = str(e)
        return jsonify(f"Failed to {intent}. {error_message}"), 500


@slot_info_agent.result_validator
@business_info_agent.result_validator
async def validate_result(ctx: RunContext[Intent], final_output: str):
    engineered_prompt = (
        f"Prompt: {ctx.prompt.strip()}, "
        f"Final Output: {final_output.strip()}"
    )

    result = await validator_agent.run(engineered_prompt)
    if result.data:
        return final_output
    raise ModelRetry("The result is invalid.")


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
            try:
                credentials.refresh(GoogleRequest())
            except Exception as e:
                credentials = None
        if not credentials:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            credentials = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(token_file, 'w') as token:
            token.write(credentials.to_json())

    service = build('calendar', 'v3', credentials=credentials)
    return service

def create_gcal_event(service_name: str, customer_name: str, emails: str, date: str, start_time: str, end_time: str):
    service = authenticate_google_calendar()
    attendees = [{"email": email} for email in emails]
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


import json
from typing import Optional, Annotated
from langchain_core.tools import tool
import os
from datetime import datetime, timedelta
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from dotenv import load_dotenv
from email.message import EmailMessage
import base64
from pymongo.mongo_client import MongoClient
import certifi
import logging


load_dotenv()

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
MONGODB_URI = os.environ['MONGODB_URI']

main_logger = logging.getLogger('main')


def connect_to_db(uri: str) -> MongoClient:
    # Create a new client and connect to the server
    client = MongoClient(uri,
                         ssl_ca_certs=certifi.where())

    # Send a ping to confirm a successful connection
    try:
        client.admin.command('ping')
        main_logger.info("Pinged your deployment. You successfully connected to MongoDB!")
        return client
    except Exception as e:
        main_logger.info(f"Failed to connect to MongoDB. Check your connection.{e}")
        raise e
    
database_client = connect_to_db(MONGODB_URI)
database = database_client['ai_receptionist']
accounts = database['accounts']


@tool
def crud_client_tool(
                    account_id: Annotated[str, "Account ID"],
                    operation: Annotated[str, "Operation type: create, read, update, or delete"],
                    client_email: Annotated[str, "Current email address of the client"],
                    client_name: Annotated[str, "Name of the client"] = None,
                    client_phone: Annotated[str, "Phone number of the client"] = None,
                    new_client_email: Annotated[str, "New email address of the client"] = None) -> Optional[dict]:
    """Create, read, update or delete a client"""
    main_logger.debug(f"Attempting to {operation} client {client_email}")
    assert operation in ["create", "read", "update", "delete"], "Invalid operation, please use create, read, update or delete"
    if operation == "create":
        existing_client = accounts.find_one({"account_id": account_id, "clients.email": client_email})
        if existing_client:
            return {"response": f"Client {client_email} already exists"}
        
        accounts.update_one(
            {"account_id": account_id},
            {"$push": {"clients": {"name": client_name, "email": client_email, "phone": client_phone}}}
        )
        return {"response": f"Client {client_email} created successfully",}
    elif operation == "read":
        client = accounts.find_one(
            {"account_id": account_id, 
             "clients": {"$elemMatch": {"$or": [
                 {"email": client_email},
                 {"phone": client_phone}
             ]}}},
             {"_id": 0, "clients.$": 1}
            )
        if client and client.get("clients", None):
            client = client['clients'][0]
            return {"response": f"Client found: name: {client['name']}, email: {client['email']}, phone: {client['phone']}", 
                    "client": client}
        return {"response": "Client not found", "client": None}
    elif operation == "update":
        fields_to_update = {}
        if client_name:
            fields_to_update["clients.$.name"] = client_name
        if client_phone:
            fields_to_update["clients.$.phone"] = client_phone
        if new_client_email:
            fields_to_update["clients.$.email"] = new_client_email
        if not fields_to_update:
            return {"response": "No fields to update provided"}

        ## First try to update name and phone using email
        result = accounts.update_one(
                    {"account_id": account_id, "clients.email": client_email},
                    {"$set": fields_to_update}
                )
        if result.modified_count == 0:
            return {"response": f"Client {client_email} not found"}
        return {"response": f"Client {new_client_email if new_client_email else client_email} updated successfully"}
    elif operation == "delete":
        result = accounts.update_one(
            {"account_id": account_id},
            {"$pull": {"clients": {"email": client_email}}}
        )
        if result.modified_count == 0:
            return {"response": f"Client {client_email} not found"}
        return {"response": f"Client {client_email} deleted successfully"}


@tool
def check_slot_availability_tool(account_id: str, booking_type: Annotated[str, "Type of booking: inquiries or jobs"]) -> dict:
    """Check the availability of a meeting slot"""
    pipeline = [
        {"$match": {"account_id": account_id}},
        {
            "$project": {
                "_id": 0,
                booking_type: {
                    "$filter": {
                        "input": f"${booking_type}",
                        "as": "slot",
                        "cond": {"$eq": ["$$slot.is_booked", False]}
                    }
                }
            }
        }
    ]
    available_slots = list(accounts.aggregate(pipeline))
    if available_slots:
        available_slots = [slot["start_time"] for slot in available_slots[0][booking_type]]
    return {"response": f"Available slots: {available_slots}"}


@tool
def check_booked_slots_tool(account_id: str, booking_type: Annotated[str, "Type of booking: inquiries or jobs"]) -> dict:
    """Check the booked slots"""
    pipeline = [
        {"$match": {"account_id": account_id}},
        {
            "$project": {
                "_id": 0,
                booking_type: {
                    "$filter": {
                        "input": f"${booking_type}",
                        "as": "slot",
                        "cond": {"$eq": ["$$slot.is_booked", True]}
                    }
                }
            }
        }
    ]
    booked_slots = list(accounts.aggregate(pipeline))
    if booked_slots:
        booked_slots = [slot["start_time"] for slot in booked_slots[0][booking_type]]
    return {"response": f"Booked slots: {booked_slots}"}


def booking_helper(
                    account_id: str,
                    title: Annotated[str, "Title of the meeting"],
                    client_email: Annotated[str, "Email of the client"],
                    start_time: Annotated[datetime, "Start date and time of the meeting in format YYYY-MM-DD HH:MM"],
                    booking_type: Annotated[str, "Type of booking: jobs or inquiries"],
                    location: Annotated[str, "Location of the meeting"] = 'Virtual') -> dict:
    """Helper function to assist with different types of bookings"""
    assert title and client_email and start_time and location, "Please provide a valid title, client name, start time and location"

    fetched_client = crud_client_tool.invoke({"account_id":account_id, "operation":"read", "client_email":client_email})["client"]
    if fetched_client is None:
        message = f"Client {client_email} not found, please create a client first"
        return {"is_interrupted": True, "response": message}

    update_one_result = accounts.update_one(
        {"account_id": account_id, booking_type: {"$elemMatch": {"start_time": start_time.strftime('%Y-%m-%d %H:%M'), "is_booked": False}}},
        {"$set": {f"{booking_type}.$.is_booked": True, f"{booking_type}.$.client_email": client_email, f"{booking_type}.$.title": title, f"{booking_type}.$.location": location}}
    )
    if update_one_result.modified_count == 1:
        message = f"Booked a slot for {booking_type}:\nTitle: {title}\nClient Name: {client_email}\nStart Time: {start_time.strftime('%Y-%m-%d %H:%M')}\nLocation: {location}"
        main_logger.info(message)
        create_gcal_event(title, fetched_client["name"], client_email, start_time)
        return {"response": message}
    
    booked_slot = accounts.find_one({"account_id": account_id, booking_type: {"$elemMatch": {"start_time": start_time.strftime('%Y-%m-%d %H:%M')}}}, {"_id":0, f"{booking_type}.$":1})
    if booked_slot and booked_slot[booking_type][0]["client_email"] == client_email:
        booked_slot = booked_slot[booking_type][0]
        message = f"You have already booked a slot for {booked_slot['title']} on {booked_slot['start_time']}"
        return {"response": message}
    else:
        available_slots = check_slot_availability_tool.invoke({"account_id":account_id, "booking_type":booking_type})["response"]
        available_slots = available_slots[available_slots.find("["):available_slots.find("]")+1]
        message = f"Sorry, your desired slot is not available, please try a different slot. Please choose from the following available slots: {available_slots}"
        return {"is_interrupted": True, "response": message}


@tool
def book_job_tool(
                account_id: str,
                title: Annotated[str, "Title of the job"],
                client_email: Annotated[str, "Email of the client"],
                start_time: Annotated[datetime, "Start date and time of the meeting in format YYYY-MM-DD HH:MM"],
                location: Annotated[str, "Location of the job"] = 'Virtual') -> dict:
    """ Book a job with a client. A job is a the actual work that needs to be done on site, and needs someone to visit the site.
    """
    return booking_helper(account_id, title, client_email, start_time, "jobs", location)


@tool
def book_inquiry_tool(
                account_id: str,
                title: Annotated[str, "Title of the inquiry"],
                client_email: Annotated[str, "Email of the client"],
                start_time: Annotated[datetime, "Start date and time of the meeting in format YYYY-MM-DD HH:MM"],
                location: Annotated[str, "Location of the inquiry"] = 'Virtual') -> dict:
    """ Book an inquiry with a client. An inquiry is like a first meeting with a client to discuss the details of the job. 
        It is like a discovery call from the client's perspective, where the client will discuss their requirements.
    """
    return booking_helper(account_id, title, client_email, start_time, "inquiries", location)


@tool
def send_email_tool(
                    account_id: str,
                    client_email: Annotated[str, "Email address of the recipient"],
                    subject: Annotated[str, "Subject line of the email"],
                    body: Annotated[str, "Main content of the email"]) -> dict:
    """Send an email to a client"""
    assert client_email and subject and body, "Please provide a valid client email, subject and body"
    main_logger.debug(f"Sending email: From: {SENDER_EMAIL} To: {client_email}\nSubject: {subject}\nBody: {body}")
    credentials = get_google_credentials()
    service = build('gmail', 'v1', credentials=credentials)
    message = EmailMessage()
    message['To'] = client_email
    message['From'] = SENDER_EMAIL
    message['Subject'] = subject
    message.set_content(body)

    encoded_message = base64.urlsafe_b64encode(message.as_bytes()).decode()
    create_message = {"raw": encoded_message}
    send_message = (
        service.users()
        .messages()
        .send(userId="me", body=create_message)
        .execute()
    )
    return {"response": f"Email sent to {client_email} successfully"}


SCOPES = ['https://www.googleapis.com/auth/calendar','https://www.googleapis.com/auth/gmail.compose']


def get_google_credentials():
    # Load credentials or initiate OAuth flow
    credentials = None
    token_file = 'agents/receptionist_agent/token.json'
    if os.path.exists(token_file):
        credentials = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            try:
                credentials.refresh(GoogleRequest())
            except Exception as e:
                credentials = None
        if not credentials:
            flow = InstalledAppFlow.from_client_secrets_file("agents/receptionist_agent/credentials.json", SCOPES)
            credentials = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open(token_file, 'w') as token:
            token.write(credentials.to_json())

    return credentials


def create_gcal_event(title: str, client_name: str, client_email: str, start_time: datetime):
    credentials = get_google_credentials()
    service = build('calendar', 'v3', credentials=credentials)
    attendees = [{"email": client_email}]
    end_time = start_time + timedelta(hours=1)
    event = {
        'summary': title,
        'description': f"Appointment with {client_name}",
        'attendees': attendees,
        'start': {
            'dateTime': f"{start_time.strftime('%Y-%m-%dT%H:%M:%S')}",
            'timeZone': 'America/New_York'
        },
        'end': {
            'dateTime': f"{end_time.strftime('%Y-%m-%dT%H:%M:%S')}",
            'timeZone': 'America/New_York'
        }
    }
    event_result = service.events().insert(calendarId='primary', sendNotifications=True, body=event).execute()
    return event_result.get('htmlLink', None)

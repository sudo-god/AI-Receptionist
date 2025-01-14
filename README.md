# AI Receptionist MVP

This project is a simple AI-powered receptionist built with Flask, MongoDB, and Google’s PaLM (Generative AI) model (Gemini). It assists a small business by:
1. Providing business information (services, operating hours, contact info) 
2. Scheduling appointments
3. Handling various customer queries using an NLP model
4. Allowing custom, template-based responses for personalization

---

## Table of Contents
- [AI Receptionist MVP](#ai-receptionist-mvp)
  - [Table of Contents](#table-of-contents)
  - [Overview](#overview)
  - [Features](#features)
  - [Access from AWS](#access-from-aws)
  - [Run Locally](#run-locally)
    - [Installation and Setup](#installation-and-setup)
    - [Example `.env` File](#example-env-file)
  - [Endpoints](#endpoints)
      - [I have prepared a public postman workspace for you to invoke the endpoints.](#i-have-prepared-a-public-postman-workspace-for-you-to-invoke-the-endpoints)
    - [1. Business Information Integration](#1-business-information-integration)
    - [2. Appointment Scheduling](#2-appointment-scheduling)
    - [3. AI-Powered Customer Interaction](#3-ai-powered-customer-interaction)
    - [4. Personalization and Customization](#4-personalization-and-customization)
  - [Notes on Data Models](#notes-on-data-models)
  - [End](#end)

---

## Overview

The AI Receptionist MVP simulates how a small business can leverage AI to automate basic receptionist duties. It integrates with a MongoDB database to store:
- Business information
- Appointment calendar (available slots and bookings)
- Custom response templates

The solution uses a Generative AI model (Google PaLM, codenamed Gemini) to interpret natural language prompts, generate structured MongoDB queries on the fly, and respond to user requests accordingly.

---

## Features

1. **Business Information Integration**  
   - Stores and retrieves business data such as services, prices, operating hours, and contact information.  
   - Leverages an AI model to translate natural language queries into MongoDB queries.

2. **Appointment Scheduling**  
   - Maintains a list of available time slots in a MongoDB `calendar` collection.  
   - Books appointments and prevents double-booking through a single endpoint.

3. **AI-Powered Customer Interaction**  
   - Uses Google’s PaLM Generative AI (Gemini) to understand user intent.  
   - Processes queries about services, operating hours, and schedules.  
   - Logs every interaction for future analytics and improvements.

4. **Personalization and Customization**  
   - Admin interface to store and modify template-based responses.  
   - Customizable message templates per query type.

5. **Google Calendar API integration**
   - Integrated Google Calendar API to sync available slots and bookings in real-time.

---

## Access from AWS 
I have deployed the app on AWS and can be accessed via `http://16.170.151.93:80`. 
If you decide to use invoke the app on AWS jump to [Endpoints](#endpoints), otherwise continue further.

## Run Locally

### Installation and Setup

1. **Clone the Repository**
   ```bash
   git clone https://github.com/yourusername/ai-receptionist-mvp.git
   cd ai-receptionist-mvp
   ```

2. **Create a conda Virtual Environment (Optional but Recommended)**
   ```bash
   conda create -n <VENV_NAME> python=3.12    
   conda activate <VENV_NAME>
   ```

3. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set Up MongoDB**  
   - Ensure you have a MongoDB instance running (local or hosted via Atlas).  
   - Create a new database (in our case it's called `spaceo`).

5. **Create and Configure `.env` File**  
   Two key environment variables are needed:
   - `MONGODB_URI`: Connection string for your MongoDB instance.  
   - `GEMINI_API_KEY`: API key for the Google PaLM model.
   - Provide the required environment variables. See [Example `.env` File](#example-env-file).

---

### Example `.env` File

Below is an example `.env` file you might use locally:

```
MONGODB_URI=connection-uri–from-mongodb
GEMINI_API_KEY=google-ai-studio-api-key
```

---

**MongoDB Collections**:
1. `business_data`  
2. `calendar`  
3. `customer_queries`  
4. `custom_responses`

Each collection has a specific schema and purpose described in [Notes on Data Models](#notes-on-data-models).

---


Once the environment is set and the DB is ready, run the Flask application:

```bash
python main.py
```
The app will start on `http://127.0.0.1:5000` by default.


## Endpoints
#### I have prepared a public [postman workspace](https://www.postman.com/blue-shadow-459244/workspace/ai-receptionist/collection/19509196-3e7664a8-78be-466c-bb30-e7cfd23360bb?action=share&creator=19509196&active-environment=19509196-e7327572-f864-4ead-a106-16a902e7cb90) for you to invoke the endpoints.

If running locally make sure to change the `base_url` variable in the environment `AI Receptionist` in postman to `http://127.0.0.1:5000`.

Below are the endpoints and their usage in detail:
### 1. Business Information Integration

- **Endpoint**: `GET /get_business_info`  
  - **Description**: Fetches relevant business information from the `business_data` collection based on the user’s natural language prompt.  
  - **Parameters** (* indicates required):  
    - `prompt`*: The user’s natural language query.
    - `intent`*: A comma-separated string specifying the user’s intent. Valid options: `service`, `operating_hours`, `contact_information`.  
  - **Response**: Returns the matched data formatted according to the custom templates in `custom_responses`.

**Example**:
```bash
"http://127.0.0.1:5000/get_business_info?prompt=give me a list of the business who offer cooking service and sort them in ascending order of price&intent=service"
or
"http://127.0.0.1:5000/get_business_info?prompt=what services are available&intent=service"
```

### 2. Appointment Scheduling

- **Endpoint**: `POST /schedule`  
  - **Description**: Books an appointment if the requested time slot is available.  
  - **Request Body** (JSON):
    All of `customer_name`, `attendee_emails`, `service` and `start_time (YYYY-MM-DD HH:MM)` are mandatory.
    `attendee_emails` is a list of emails.
    ```json
    {
      "data": {
        "customer_name": "Jane Doe",
        "service": "Consultation",
        "start_time": "2025-01-10 14:30",
        "attendee_emails": ["abc@gmail.com","ijk@gmail.com"]
      }
    }
    ```
  - Alternatively, you can pass a `prompt` as a query parameter to extract and parse the data using AI. 
  - All the mandated fields must be present in either approach.
  - **Response**: Returns a success message along with an email notification for the google calendar invite or an error if double-booked/invalid slot.

**Example**:
```bash
curl -X POST -H "Content-Type: application/json" \
     -d '{"data":{"customer_name":"Jane Doe","attendee_emails":["abc@gmail.com","ijk@gmail.com"],"service":"Consultation","start_time":"2025-01-10 14:30"}}' \
     http://127.0.0.1:5000/schedule
or 
"http://127.0.0.1:5000/schedule?prompt=My friend Dixit has a meeting at 11:00 to 13:00, and he'll be free at 13:00, so book him an appointment for that time on 2025-01-02 for house cleaning. Email addresses are abc@gmail.com,ijk@gmail.com"
```

### 3. AI-Powered Customer Interaction

- **Endpoint**: `GET /chat`  
  - **Description**: Interprets the user’s prompt to identify the intent, then routes the request to the appropriate endpoint (`get_business_info` or `schedule`).  
  - **Parameters** (* indicates required):  
    - `prompt`*: The user’s chat text.
  - The AI receptionist can handle the following intents, so make sure your prompts are related to one of the four main intents; `None` is for avoiding hallucinations and respond with appropriate error message.:
    - `service`
    - `operating_hours`
    - `appointment_scheduling`
    - `contact_information`
    - `None`
  - **Response**: Returns relevant information or schedules an appointment, depending on the parsed intent.

**Example**:
```bash
"http://127.0.0.1:5000/chat?prompt=what are the available slots that I can book"
or
"http://127.0.0.1:5000/chat?prompt=what are the hours of operation, services and contact information of spaceo"
or
"http://127.0.0.1:5000/chat?prompt=My friend Dixit has a meeting at 11:00 to 13:00, but he'll be free at 9:00, so book him an appointment for that time on 2025-01-03 for house cleaning"
```

### 4. Personalization and Customization

- **Endpoint**: `GET` or `POST /admin_interface`  
  - **Description**: Basic admin interface to manage the `custom_responses` collection.  
  - **GET**: Renders an HTML page with existing custom response templates.  
  - **POST**: Updates a custom response template. Expects form fields `query_type` and `template`.

**Example**: Access via a browser  
```bash
"http://localhost:5000/admin_interface"
```
Then fill out the form to modify your custom response templates.

---

## Notes on Data Models

1. **`business_data` Collection**  
   Example Document:
   ```json
   {
     "name": "google",
     "operating_hours": "Mon-Fri 9am-5pm",
     "contact_info": "8888888888",
     "services": [
       {
         "name": "Consultation",
         "description": "One-on-one consultation",
         "price": 150
       },
       {
         "name": "Therapy Session",
         "description": "Physical or mental therapy session",
         "price": 200
       }
     ]
   }
   ```

2. **`calendar` Collection**  
   Example Document:
   ```json
   {
     "date": "2025-01-01",
     "available_slots": [
       {
         "start_time": "14:30",
         "end_time": "15:00",
         "is_booked": true,
         "service": "cleaning",
         "customer_name": "Batman"
       },
       {
         "start_time": "15:00",
         "end_time": "15:30",
         "is_booked": false,
         "service": "",
         "customer_name": ""
       }
     ]
   }
   ```

3. **`customer_queries` Collection**  
   - Logs user interactions: timestamps, original prompts, and generated queries.
  
   Example Document:
   ```json
     {
       "timestamp": "2025-01-02 00:41:45",
       "customer_prompt": "what service does google provide",
       "generated_MQL": [
           {
               "$match": {
                   "name": "google"
               }
           }
       ],
       "result": {
           "name": "google",
           "services": [
               {
                   "name": "Consultation",
                   "description": "One-on-one consultation",
                   "price": {
                       "$numberInt": "150"
                   }
               }
           ],
           "operating_hours": "10-11am",
           "contact_info": "8888888888"
       }
   }
   ```
  

4. **`custom_responses` Collection**  
   Example Document:
   ```json
   {
      "query_type": "service",
      "template": "{business_name} offers {service_name} at a price of ${price}. {description}"
   }
   ```
   - You can add or modify placeholders as needed, e.g., `{business_name}`, `{price}`, etc.

---

## End
Congratulations you have built an AI receptionist. Thankyou for your precious time.

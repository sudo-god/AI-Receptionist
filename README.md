
# Setup and run the chatbot:

## Frontend Setup and run

In a terminal window, change the directory to `chatbot_ui`, and run the following commands:

To install Angular CLI:
```bash
npm install -g @angular/cli
```

To install dependencies:
```bash
npm install
```

To build the app:
```bash
npm run build
```

To run the app:
```bash
npm start
```

## Backend Setup

In a separate terminal, ensure you're in the project root directory, and run the following commands:

To create a python virtual environment (optionally use conda virtual environment):
```bash
python -m venv ai_receptionist
```

To activate the virtual environment:
```bash
source ai_receptionist_venv/bin/activate
```

To install dependencies:
```bash
pip install -r requirements.txt
```

## Run the backend

Development mode:
```bash
# python manage.py runserver
uvicorn ai_receptionist_chat.asgi:application --reload
```

Production mode:
```bash
# python manage.py runserver
uvicorn ai_receptionist_chat.asgi:application
```

## Access the chatbot

**Note: When the response is a yellow bubble, it means that's the human in loop interrupt.**

Open a new browser window and navigate to `http://localhost:3000` to access the chatbot.

I've limited the number of user accounts to 2 for now. The accounts are selected automatically, and each browser tab is assigned an account. 

I am storing the account id in the browser's session storage, and the account id is selected from a list of available account ids stored in the browser's local storage.

To test the chatbot, you can open multiple browser tabs and chat with different accounts simultaneously.


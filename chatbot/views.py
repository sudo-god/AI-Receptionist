import asyncio
import nest_asyncio
from ai_receptionist_chat import settings
nest_asyncio.apply()

from io import BytesIO
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
import json
from django.core.cache import cache
import logging
import logging.config
import yaml
import hashlib

from agents.receptionist_agent.main import process_input
# from agents.RAG_agent.graph import process_input
from agents.RAG_agent.graph import file_upload_handler


with open("config/logging.yml", "r") as logging_config_file:
    logging.config.dictConfig(yaml.load(logging_config_file, Loader=yaml.FullLoader))

main_logger = logging.getLogger('main')


def get_interrupted_state(account_id: str):
    return cache.get(f'{account_id}:is_interrupted', False)


def set_interrupted_state(account_id: str, value: bool):
    cache.set(f'{account_id}:is_interrupted', value, timeout=None)


@csrf_exempt
async def chat_view(request):
    """
    A view to handle chat input. 
    Response will be JSON.
    """
    if request.method == 'POST':
        try:
            data = json.loads(request.body.decode('utf-8'))
            user_message = data.get('message', '')
            account_id = data.get('account_id', '')
            
            main_logger.info(f"Received message: {user_message} for account_id: {account_id}")
            is_interrupted = get_interrupted_state(account_id)
            
            response_text, is_interrupted = await process_input(user_message, account_id, is_interrupted)
            set_interrupted_state(account_id, is_interrupted)
            return JsonResponse({"response": response_text, "is_interrupted": is_interrupted}, status=200)
        except json.JSONDecodeError:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
    else:
        return JsonResponse({"error": "Invalid request method"}, status=405)


from django.core.files.storage import FileSystemStorage
from django.core.files.base import ContentFile


@csrf_exempt
def upload_file(request):
    if request.method != 'POST' or not request.FILES.get('file', None):
        return JsonResponse({'error': 'No file uploaded'}, status=400)

    if not request.POST.get('account_id', None):
        return JsonResponse({'error': 'No account_id provided'}, status=400)

    uploaded_file = request.FILES.get('file')
    account_id = request.POST.get('account_id', '')
    
    allowed_extensions = ['.jpeg', '.jpg', '.png', '.pdf', '.txt', '.csv']
    print(f"File extension check: {uploaded_file.name.endswith(tuple(allowed_extensions))}")
    if not uploaded_file.name.endswith(tuple(allowed_extensions)):
        return JsonResponse({'error': f"Invalid file type. Allowed types: {', '.join(allowed_extensions)}"}, status=400)

    # Check if the file already exists using checksum
    new_checksum = hashlib.md5(uploaded_file.read()).hexdigest()
    destination = FileSystemStorage(location=settings.MEDIA_ROOT + '/uploaded-files/raw-files')
    print(f"File exists: {destination.exists(uploaded_file.name)}")
    
    if not destination.exists(uploaded_file.name):
        destination.save(uploaded_file.name, ContentFile(uploaded_file.read()))
    elif destination.exists(uploaded_file.name) and new_checksum != hashlib.md5(destination.open(uploaded_file.name).read()).hexdigest():
        destination.delete(uploaded_file.name)
        FileSystemStorage(location=settings.MEDIA_ROOT + f'/uploaded-files/index-storage').delete(uploaded_file.name)
        destination.save(uploaded_file.name, ContentFile(uploaded_file.read()))

    file_upload_handler(file_name=uploaded_file.name, account_id=account_id, key="attachment_processors")
    return JsonResponse({'message': 'File uploaded successfully', 'file_name': uploaded_file.name})


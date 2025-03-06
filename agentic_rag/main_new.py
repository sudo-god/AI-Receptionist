import asyncio

import nest_asyncio
nest_asyncio.apply()

import os
from typing import List, Literal, TypedDict
from dotenv import load_dotenv
import logfire
import logging
import logging.config
import yaml
from supabase import create_client
import streamlit as st
from attachment_processor import AttachmentProcessor, AttachmentProcessors
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    UserPromptPart,
    TextPart
)
from graph import process_input, add_to_store


load_dotenv()

logfire.configure()
with open("config/logging.yml", "r") as logging_config_file:
    logging.config.dictConfig(yaml.load(logging_config_file, Loader=yaml.FullLoader))

main_logger = logging.getLogger('main')


supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)


class ChatMessage(TypedDict):
    """Format of messages sent to the browser/API."""
    role: Literal['user', 'model']
    timestamp: str
    content: str


def display_message_part(part):
    """
    Display a single part of a message in the Streamlit UI.
    Customize how you display system prompts, user prompts,
    tool calls, tool returns, etc.
    """
    # system-prompt
    if part.part_kind == 'system-prompt':
        with st.chat_message("system"):
            st.markdown(f"**System**: {part.content}")
    # user-prompt
    elif part.part_kind == 'user-prompt':
        with st.chat_message("user"):
            st.markdown(part.content)
    # text
    elif part.part_kind == 'text':
        with st.chat_message("assistant"):
            st.markdown(part.content)


def invoke_agent(prompt: str, account_id: str):
    print(f"INVOKE AGENT PROMPT: {prompt}")
    query_response = process_input(prompt, account_id, False)
    print(f"Streamlit received data: {query_response}")

    # Add the final response to the messages
    st.session_state.message_history.append(
        ModelResponse(parts=[TextPart(content=query_response)])
    )


def main():
    st.title("Dixit's RAG application")
    st.write("Ask me a question about {{something}}. You can provide a url, text document or an image as additional information source.")

    # Initialize chat history in session state if not present
    if "message_history" not in st.session_state:
        st.session_state.message_history = []

    if "account_id" not in st.session_state:
        st.session_state.account_id = "account_id_1"
    
    if "attachment_processors" not in st.session_state:
        st.session_state.attachment_processors = AttachmentProcessors()
        namespace = ("attachment_processors", st.session_state.account_id)
        add_to_store(namespace, "attachment_processors", st.session_state.attachment_processors)

    if "attachments_processed" not in st.session_state:
        st.session_state.attachments_processed = {}

    for msg in st.session_state.message_history:
        if isinstance(msg, ModelRequest) or isinstance(msg, ModelResponse):
            for part in msg.parts:
                display_message_part(part)

    prompt = st.chat_input("Ask me...")
    attachments = st.file_uploader("Upload a file.", type=("txt", "csv", "md", "pdf", "jpg", "jpeg", "png"), accept_multiple_files=True)
    
    if attachments:
        once = True
        for attachment in attachments:
            if attachment.file_id not in st.session_state.attachments_processed:
                with st.spinner("Processing attached document..."):
                    processor = AttachmentProcessor(attachment)
                    processor.process()
                    st.session_state.attachment_processors.add_attachment(processor)
                    st.session_state.attachments_processed[attachment.file_id] = processor
                if once:
                    st.success("Successfully processed attached document.")
                    once = False

    for file_id in list(st.session_state.attachments_processed.keys()):
        found = False
        for attachment in attachments:
            if attachment.file_id == file_id:
                found = True
        if not found:
            st.session_state.attachments_processed.pop(file_id)
            st.session_state.attachment_processors.remove_attachment(st.session_state.attachments_processed[file_id])

    if prompt:
        st.session_state.message_history.append(
            ModelRequest(parts=[UserPromptPart(content=prompt)])
        )

        with st.chat_message("user"):
            st.markdown(prompt)

        # Display the assistant's partial response while streaming
        with st.chat_message("assistant"):
            # Actually run the agent now, streaming the text
            print("INVOKING AGENT")
            with st.spinner("Thinking..."):
                invoke_agent(prompt, st.session_state.account_id)
            print("INVOKE CALL RETURNED")
    # print(f"STATE: {st.session_state}")


if __name__ == "__main__":
    # asyncio.run(main())
    # if not hasattr(st.session_state, "loop"):
    #     st.session_state.loop = asyncio.new_event_loop()
    # st.session_state.loop.run_until_complete(main())
    # try:
    #     loop = asyncio.new_event_loop()
    #     asyncio.set_event_loop(loop)
    #     loop.run_until_complete(main())
    # finally:
    #     loop.close()

    main()

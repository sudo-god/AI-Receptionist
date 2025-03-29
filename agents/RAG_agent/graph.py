import asyncio
import nest_asyncio
nest_asyncio.apply()

import sys
import os
import json
from dotenv import load_dotenv
import logging
import logging.config
import yaml
from typing import Optional, TypedDict, Annotated, List, Union, Any
from langchain_core.agents import AgentAction
from langchain.agents.output_parsers.tools import ToolAgentAction
from langchain_core.messages import ToolMessage
from langgraph.graph.message import add_messages

from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import tool
from langgraph.types import Command
from .attachment_processor import AttachmentProcessors, AttachmentProcessor, query_attachments, query_database, dummy_file_setup, storage_lookup



load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

with open("config/logging.yml", "r") as logging_config_file:
    logging.config.dictConfig(yaml.load(logging_config_file, Loader=yaml.FullLoader))

main_logger = logging.getLogger('main')


## ================= Declaring the state =================

class AgentState(TypedDict):
    # user_input: str
    # messages: Annotated[list, add_messages]
    # account_id: str
    # final_response: str
    # intermediate_steps: list[AgentAction]
    # last_tool_call: AgentAction

    user_input: str
    messages: Annotated[list, add_messages]
    account_id: str
    intermediate_steps: list[AgentAction]
    last_tool_call: AgentAction
    responses: list
    final_response: str
    is_interrupted: bool
    interrupt_queue: list[dict]


config = {"configurable": {"thread_id": ""}}
gemini_model = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp", google_api_key=GEMINI_API_KEY)
model = gemini_model

## ================= Setting up the agent prompts =================

rag_agent_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        'You are an AI assistant that retrieves information either from the attached documents or by querying the database.'
        'You already have access to the documents in the storage and the database, from the backend.'
    )),
    MessagesPlaceholder(variable_name="messages"),
    ("user", "{user_input}"),
])

## ================= Setting up the tools =================

tools = [query_attachments, query_database]
model = model.bind_tools(tools)
rag_llm = (rag_agent_prompt | model)
tools_by_name = {tool.name: tool for tool in tools}

## ================= Setting up the Nodes =================

async def agent_node(state: AgentState, config: RunnableConfig):
    if state.get('intermediate_steps', []) != []:
        # main_logger.info(f"intermediate_steps in agent_node: {state['intermediate_steps']}\n\n\n")
        return {"final_response": state["final_response"]}
    elif state.get('intermediate_steps', []) == [] and state.get('last_tool_call', None) is not None:
        # main_logger.info("RAN ALL TOOLS\n\n\n")
        return {"final_response": state["final_response"]}
    else:
        print(f"RAG Agent State: {state}")
        response = await rag_llm.ainvoke(state, config)
        agent_actions = []
        for tool_call in response.tool_calls:
            tool_call["args"]["account_id"] = state["account_id"]
            agent_actions.append(ToolAgentAction(
                tool=tool_call["name"],
                tool_input=tool_call["args"], 
                tool_call_id=tool_call["id"],
                log=f"Adding {tool_call['name']} to intermediate steps",
                message_log=state["messages"]
            ))
        return {
            "messages": [response],
            "intermediate_steps": agent_actions,
            "final_response": response.content
        }


async def tool_node(state: AgentState):
    outputs = []
    for action in list(state["intermediate_steps"]):
        tool_name = action.tool
        tool_args = action.tool_input.copy()
        tool_args["store"] = store
        tool_response = await tools_by_name[tool_name].ainvoke(tool_args)
        outputs.append(
            ToolMessage(
                content=json.dumps(tool_response),
                name=tool_name,
                tool_call_id=action.tool_call_id
            )
        )
        state["intermediate_steps"].remove(action)
        state["last_tool_call"] = action
        state["final_response"] += ("\n" + tool_response)
    return {
        "messages": outputs, 
        "intermediate_steps": state["intermediate_steps"],
        "last_tool_call": state["last_tool_call"],
        "final_response": state["final_response"]
    }

## ================= Define the conditional edge logic =================

def router(state: AgentState):
    if state.get("intermediate_steps", []) != []:
        return state["intermediate_steps"][0].tool
    return END

## ================= Setting up the graph =================

entry_point = "agent_node"
memory = MemorySaver()
store = InMemoryStore()

workflow = StateGraph(AgentState)
workflow.add_node(entry_point, agent_node)
workflow.add_node("query_attachments", tool_node)
workflow.add_node("query_database", tool_node)

workflow.set_entry_point(entry_point)
workflow.add_conditional_edges(
    entry_point,
    router
)

# Create edges from each tool back to the agent
for tool_obj in tools:
    workflow.add_edge(tool_obj.name, entry_point)

rag_agent = workflow.compile(name="rag_agent", store=store, checkpointer=memory)

## ================= Visualizing the graph =================

with open("agents/RAG_agent/rag_graph_visualization.jpg", "wb") as f:
    f.write(rag_agent.get_graph().draw_mermaid_png())

## ================= Running the agent =================

async def process_input(user_input: str, account_id: str, is_interrupted: bool = False) -> tuple[str, bool]:
    global inputs

    config["configurable"]["thread_id"] = account_id

    inputs = {
        "user_input": user_input,
        "messages": user_input,
        "account_id": account_id,
        "intermediate_steps": [],
        "last_tool_call": None,
        "final_response": ""
    }

    if is_interrupted:
        inputs = Command(resume=user_input)

    events = rag_agent.astream(
        inputs,
        config
    )

    async for event in events:
        sys.stdout.flush()
        if event.get("__interrupt__", None):
            is_interrupted = True
            response = event['__interrupt__'][0].value
        else:
            is_interrupted = False
            response = None

            if event.get(entry_point, None):
                response = event[entry_point]['final_response']
            elif event.get("final_response", None):
                response = event['final_response']
        if response:
            print('\n\n\n====================== RAG AGENT RESPONSE ======================')
            main_logger.info(response)
            print('======================================================\n\n\n')
    return response, is_interrupted


def file_upload_handler(file_name: str, account_id: str, key: str):
    namespace = (account_id,)
    attachment_processors = storage_lookup(store, namespace, key)
    if attachment_processors is None:
        attachment_processors = AttachmentProcessors()
        store.put(namespace, key, attachment_processors)
        main_logger.info(f"Attachment processors stored in store namespace: {namespace} key: {key}")

    attachment = AttachmentProcessor(file_name)
    attachment.process()
    attachment_processors.add_attachment(attachment)


if __name__ == "__main__":
    from attachment_processor import dummy_file_setup, add_new_attachment

    attachment_processors = AttachmentProcessors()

    account_id = "account_id_1"
    namespace = (account_id,)
    attachment_processors_store_key = "attachment_processors"
    store.put(namespace, attachment_processors_store_key, attachment_processors)

    account_id = "account_id_2"
    namespace = (account_id,)
    attachment_processors_store_key = "attachment_processors"
    store.put(namespace, attachment_processors_store_key, attachment_processors)

    file_obj = dummy_file_setup()
    add_new_attachment(store=store, namespace=namespace, key=attachment_processors_store_key, file_obj=file_obj)
    
    # ================================================================
    async def run_loop():
        is_interrupted = False
        while True:
            user_input = input("Enter your query: ")
            if user_input == "":
                main_logger.info("Please enter a valid query.")
                continue
            response, is_interrupted = await process_input(user_input, "account_id_1", is_interrupted)
    asyncio.run(run_loop())

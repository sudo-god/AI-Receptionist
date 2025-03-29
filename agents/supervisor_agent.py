import os
import time
import yaml
from dotenv import load_dotenv
import logging

from agents.receptionist_agent.graph import receptionist_agent, entry_point as receptionist_entry_point, receptionist_agent_prompt
from agents.RAG_agent.graph import rag_agent, entry_point as rag_entry_point, rag_agent_prompt
from langchain_core.agents import AgentAction
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langgraph.store.memory import InMemoryStore
from langgraph.types import Command
from langgraph_supervisor import create_supervisor
from typing import Optional, TypedDict, Annotated, List, Union, Any, Literal
from pydantic import BaseModel

load_dotenv()

with open("config/logging.yml", "r") as logging_config_file:
    logging.config.dictConfig(yaml.load(logging_config_file, Loader=yaml.FullLoader))

main_logger = logging.getLogger('main')

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

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
    next_agent: str

config = {"configurable": {"thread_id": ""}}
gemini_model = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp", google_api_key=GEMINI_API_KEY)
helper_model = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp", google_api_key=GEMINI_API_KEY)
model = gemini_model


class NextAgent(BaseModel):
    """Worker to route to next. If no workers needed, route to FINISH."""
    next_agent: Literal["receptionist_agent", "rag_agent", "FINISH"]

## ================= Setting up the agent prompts =================

supervisor_agent_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a supervisor agent that manages the receptionist_agent and the rag_agent."
        f"The receptionist agent has the following system prompt: {receptionist_agent_prompt.messages[0].prompt.template}."
        f"The RAG agent has the following system prompt: {rag_agent_prompt.messages[0].prompt.template}."
        "Given the following user request, respond only with the agent name to act next."
        "Do not produce anything else."
        "Your can route to the receptionist_agent, by default if you're unclear what to do with the prompt."
    )),
    MessagesPlaceholder(variable_name="messages"),
    ("user", "{user_input}"),
])

supervisor_llm = (supervisor_agent_prompt | model.with_structured_output(NextAgent))

## ================= Define the conditional edge logic =================

def router(state: AgentState):
    goto = state["next_agent"]
    if goto == "FINISH":
        goto = END
    return goto

## ================= Setting up the Nodes =================

def agent_node(state: AgentState):
    response = supervisor_llm.invoke(state, config)
    print(f"Response: {response}")
    goto = response.next_agent
    return {"next_agent": goto}

## ================= Setting up the graph =================

entry_point = "top_level_supervisor"
memory = MemorySaver()
store = InMemoryStore()

workflow = StateGraph(AgentState)
workflow.add_node(entry_point, agent_node)
workflow.add_node("receptionist_agent", receptionist_agent)
workflow.add_node("rag_agent", rag_agent)

workflow.set_entry_point(entry_point)
workflow.add_conditional_edges(
    entry_point,
    router
)

top_level_supervisor = workflow.compile(store=store, checkpointer=memory)
sub_agents_entry_points = ["receptionist_agent", "rag_agent"]

## ================= Visualizing the graph =================

with open("agents/super_visor_graph_visualization.jpg", "wb") as f:
    f.write(top_level_supervisor.get_graph().draw_mermaid_png())

## ================= Running/Invoking the graph =================

async def process_input(user_input: str, account_id: str, is_interrupted: bool = False) -> tuple[str, bool]:
    config["configurable"]["thread_id"] = account_id

    inputs = {
        "user_input": user_input,
        "messages": user_input, # This might look like it's only keeping the user input in the messages, but it's actually keeping the entire conversation history, because it's annotated with `add_messages`.
        "account_id": account_id,
        "intermediate_steps": [],
        "last_tool_call": None,
        "responses": [],
        "final_response": "",
        "is_interrupted": is_interrupted,
        "interrupt_queue": [],
        "next_agent": ''
    }
    if is_interrupted:
        inputs = Command(resume=user_input)

    print(f"Inputs: {inputs}")
    events = top_level_supervisor.astream(
        inputs,
        config
    )
    async for event in events:
        print(f"\n\n\nEvent: {event}\n\n\n")
        try:
            if not isinstance(event, dict):
                continue
            if event.get("__interrupt__", None):
                is_interrupted = True
                response = event['__interrupt__'][0].value
            else:
                is_interrupted = False
                response = None
                for sub_entry_point in sub_agents_entry_points:
                    if event.get(sub_entry_point, None):
                        ## This response is the final response from the supervisor agent
                        response = event[sub_entry_point]['final_response']
                        break
                    elif event.get("final_response", None):
                        ## This response is the intermediate responses from the emitted events i.e. intermediate steps/helper agent calls etc
                        response = event['final_response']
                        break
            if response:
                print('\n\n\n====================== SUPERVISOR AGENT RESPONSE ======================')
                print(response)
                print('======================================================\n\n\n')
        except Exception as e:
            print(f"Error: {e}")

    return response, is_interrupted


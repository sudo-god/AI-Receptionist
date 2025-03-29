import asyncio
import operator
import os
import json
from dotenv import load_dotenv
import logging
import logging.config
import yaml
from typing import Optional, TypedDict, Annotated, List, Union
from langchain_core.agents import AgentAction, AgentFinish
from langchain.agents.output_parsers.tools import ToolAgentAction

from langchain_core.messages import ToolMessage, BaseMessage, AIMessage, HumanMessage, SystemMessage
from langgraph.graph.message import add_messages

from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from .tools import crud_client_tool, book_job_tool, book_inquiry_tool, send_email_tool, check_slot_availability_tool
from langgraph.types import interrupt, Command


load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

with open("config/logging.yml", "r") as logging_config_file:
    logging.config.dictConfig(yaml.load(logging_config_file, Loader=yaml.FullLoader))

main_logger = logging.getLogger('main')

## ================= Declaring the state =================

class AgentState(TypedDict):
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
response_synthesizer_model = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp", google_api_key=GEMINI_API_KEY)
helper_model = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp", google_api_key=GEMINI_API_KEY)
model = gemini_model

## ================= Setting up the agent prompts =================

receptionist_agent_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a helpful assistant that can perform a few tasks such as creating a client, booking a meeting, and sending an email."
        "Only use the tools you have, do not generate code or instructions for the tools."
        "You can ignore the account_id parameter in the tool calls, it will be assigned manually."
        "Make sure to you confirm sensitive information like emails, phone numbers, etc with the human before proceeding in cases where the information is spread across multiple messages."
        "Do not answer any other questions outside your domain."
        "There could be multiple tasks to complete in a single prompt, so you need to identify all appropriate tools to use."
        "After completing a task, provide a clear confirmation message without calling any additional tools."
    )),
    MessagesPlaceholder(variable_name="messages"), # Necessary to keep the conversation history
    ("user", "{user_input}"),
])

helper_agent_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a helpful assistant that can help with updating the parameters of a previous tool call, or calling a new tool based on the human's response to a query."
        "Either call the tool with the updated parameters, or call a new tool, do not generate code or instructions for the tools."
        "Make sure to you confirm sensitive information like emails, phone numbers, etc with the human before proceeding in cases where the information is spread across multiple messages."
        "Do not answer any other questions outside your domain."
    )),
    MessagesPlaceholder(variable_name="messages"),
    ("user", "{user_input}"),
])

response_synthesizer_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        "You are a response synthesizer that will be given all the responses from the tools and helper agent to synthesize a final response."
        "Your final response should include all the information from the responses."
        "Never return the same response you received from the tools, always rewrite the response in your own words, use context from the conversation history if needed."
        "Do not include any other information in your response."
    )),
    # MessagesPlaceholder(variable_name="messages"),
    ("user", "{user_input}"),
])

## ================= Setting up the tools =================

tools = [crud_client_tool, book_job_tool, book_inquiry_tool, send_email_tool, check_slot_availability_tool]
# model = model.bind_tools(tools)
receptionist_llm = (receptionist_agent_prompt | model.bind_tools(tools))
helper_llm = (helper_agent_prompt | helper_model.bind_tools(tools))
response_synthesizer_llm = (response_synthesizer_prompt | response_synthesizer_model)
tools_by_name = {tool.name: tool for tool in tools}

## ================= Setting up the nodes =================

async def agent_node(state: AgentState):
    print("\n\n\nReceptionist Agent node called")
    print(f"Intermediate steps @ BEGINNING of supervisor agent node: {state['intermediate_steps']}")
    print(f"Last tool call @ BEGINNING of supervisor agent node: {state['last_tool_call']}")
    if state["intermediate_steps"] != []:
        ## More tools to run
        return {"responses": state["responses"]}
    elif state["intermediate_steps"] == [] and state["last_tool_call"] is not None:
        ## Finished running all tools
        responses = '\n'.join(state['responses'])
        messages = '\n'.join([message.content for message in state['messages']])
        prompt = (f"Here are the responses from the tools you have called: {responses}"
                #   f"Here is the conversation history: {messages}"
                )
        helper_agent_inputs = {
            "user_input": prompt,
            # "messages": state["messages"],
            "responses": state["responses"]
        }
        helper_response = await response_synthesizer_llm.ainvoke(helper_agent_inputs, config)
        print("\n\n\n=========== Helper INVOKED ==========")
        print(f"Receptionist final response: {helper_response}")
        print('======================================================\n\n\n')
        helper_response = helper_response.content.replace("```", "")
        return {"final_response": helper_response}
    else:
        print(f"\n\n\nReceptionist Agent State: {state}\n\n\n")
        response = await receptionist_llm.ainvoke(state, config)
        print(f"RECEPTIONIST AGENT INVOCATION OUTPUT: {response}\n\n\n")
        agent_actions = {}
        desired_action_order = ["crud_client_tool", "check_slot_availability_tool", "book_inquiry_tool", "book_job_tool", "send_email_tool"]
        for tool_call in response.tool_calls:
            tool_call["args"]["account_id"] = state["account_id"]
            agent_actions[tool_call["name"]] = ToolAgentAction(
                tool=tool_call["name"],
                tool_input=tool_call["args"], 
                tool_call_id=tool_call["id"],
                log=f"Adding {tool_call['name']} to intermediate steps",
                message_log=state["messages"]
            )
            
        agent_actions = [agent_actions[tool_name] for tool_name in desired_action_order if tool_name in agent_actions]
        print(f"Intermediate steps ADDED by supervisor agent node: {agent_actions}")
        messages = [response] if response.content else []
        return {
            "intermediate_steps": agent_actions,
            "final_response": response.content,
            "messages": messages,
        }


def run_tool(state: AgentState):
    if state.get("intermediate_steps", [])[0] == state.get("last_tool_call", None):
        # return state
        return {"response": state["response"]}
    elif isinstance(state["intermediate_steps"], list) and state["intermediate_steps"] != []:
        action = state["intermediate_steps"][0]
        original_tool_name = action.tool
        original_tool_args = action.tool_input
        out = {"is_interrupted": True}
        outputs = []
        new_out = {}
        while out.get("is_interrupted", False) or new_out.get("is_interrupted", False):
            print(f"\n\n\n============== Running tool {original_tool_name} ===============")
            print(f"Tool args: {original_tool_args}")
            print('======================================================\n\n\n')
            out = tools_by_name[original_tool_name].invoke(input=original_tool_args)
            print(f"OUT: {out}")
            outputs.append(
                ToolMessage(
                    content=json.dumps(out),
                    name=original_tool_name,
                    tool_call_id=action.tool_call_id
                )
            )
            if out.get("is_interrupted", False):
                state["interrupt_queue"].append({
                    "tool_name": original_tool_name,
                    "tool_args": original_tool_args,
                    "reason": out["response"]
                })
                human_response = interrupt(out["response"])
                print(f"Human response: {human_response}")
                helper_out = None
                while not helper_out or helper_out.tool_calls == [] or state["interrupt_queue"] != []:
                    print(f"Interrupt queue: {state['interrupt_queue']}")
                    tool_name = state["interrupt_queue"][0]["tool_name"]
                    tool_args = state["interrupt_queue"][0]["tool_args"]
                    interrupt_reason = state["interrupt_queue"][0]["reason"]
                    prompt = f"The tool call was for {tool_name} with arguments {tool_args}. The query was: {interrupt_reason}. The human has responded to the query with the following: {human_response}"
                    helper_agent_inputs = {
                        "user_input": prompt,
                        "messages": state["messages"]
                    }
                    print(f"Helper agent prompt: {prompt}")
                    helper_out = helper_llm.invoke(helper_agent_inputs, config)
                    print("\n\n\n=========== Helper INVOKED ==========")
                    print(f"Helper out: {helper_out.content}")
                    print(f"Helper out tool calls: {helper_out.tool_calls}")
                    print('======================================================\n\n\n')
                    if helper_out.tool_calls != []:
                        state["interrupt_queue"].pop(0)
                new_tool_name = helper_out.tool_calls[0]["name"]
                new_tool_args = helper_out.tool_calls[0]["args"]
                print("\n\n\n============== Running helper agent tool call ===============")
                print(f"Tool args: {new_tool_args}")
                print('======================================================\n\n\n')
                new_out = tools_by_name[new_tool_name].invoke(input=new_tool_args)
                state["responses"].append(new_out["response"])
                print(f"NEW OUT: {new_out}")
                outputs.append(
                    ToolMessage(
                        content=json.dumps(new_out),
                        name=new_tool_name,
                        tool_call_id=helper_out.tool_calls[0]["id"]
                    )
                )
                if new_tool_name == original_tool_name and not new_out.get("is_interrupted", True):
                    break

        state["intermediate_steps"].pop(0)
        state["last_tool_call"] = action
        state["responses"].append(out["response"])
        # graph.update_state(config, state)
        return {
            "messages": outputs, 
            "intermediate_steps": state["intermediate_steps"],
            "last_tool_call": action,
            "responses": state["responses"]
        }
    else:
        # return state
        return {"response": "No tool to run"}


def router(state: AgentState):
    if state.get("intermediate_steps", []) != []:
        return state["intermediate_steps"][0].tool
    return END

## ================= Setting up the graph =================

graph_builder = StateGraph(AgentState)
entry_point = "agent_node"
graph_builder.add_node(entry_point, agent_node)
graph_builder.add_node("crud_client_tool", run_tool)
graph_builder.add_node("book_job_tool", run_tool)
graph_builder.add_node("book_inquiry_tool", run_tool)
graph_builder.add_node("send_email_tool", run_tool)
graph_builder.add_node("check_slot_availability_tool", run_tool)

graph_builder.set_entry_point(entry_point)

graph_builder.add_conditional_edges(
    source=entry_point,  # where in graph to start
    path=router,  # function to determine which node is called
)

# create edges from each tool back to the agent
for tool_obj in tools:
    graph_builder.add_edge(tool_obj.name, entry_point)

memory = MemorySaver()
receptionist_agent = graph_builder.compile(name="receptionist_agent", checkpointer=memory)

## ================= Visualizing the graph =================

with open("agents/receptionist_agent/receptionist_graph_visualization.jpg", "wb") as f:
    f.write(receptionist_agent.get_graph().draw_mermaid_png())

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
        "interrupt_queue": []
    }
    if is_interrupted:
        inputs = Command(resume=user_input)

    print(f"Inputs: {inputs}")
    events = receptionist_agent.stream(
        inputs,
        config
    )
    for event in events:
        print(f"\n\n\nEvent: {event}\n\n\n")
        try:
            if event.get("__interrupt__", None):
                is_interrupted = True
                response = event['__interrupt__'][0].value
            else:
                is_interrupted = False
                response = None
                if event.get(entry_point, None):
                    ## This response is the final response from the supervisor agent
                    response = event[entry_point]['final_response']
                elif event.get("final_response", None):
                    ## This response is the intermediate responses from the emitted events i.e. intermediate steps/helper agent calls etc
                    response = event['final_response']
            if response:
                print('\n\n\n====================== RESPONSE ======================')
                print(response)
                print('======================================================\n\n\n')
        except Exception as e:
            print(f"Error: {e}")
    return response, is_interrupted


if __name__ == "__main__":
    is_interrupted = False
    async def runloop():
        while True:
            user_input = input("Enter your query: ")
            await process_input(user_input, "account_id_2", is_interrupted)
    asyncio.run(runloop())


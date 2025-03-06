import asyncio
import concurrent.futures
from dataclasses import dataclass, asdict
import json
import os
from typing import Any, Dict, List
from dotenv import load_dotenv
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
import faiss
from pydantic_ai import Agent, RunContext, ModelRetry
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
from pydantic_ai.models.gemini import GeminiModel
import logfire
import concurrent
import logging
import logging.config
import yaml
from supabase import create_client, Client
import google.generativeai as genai
import numpy as np
from typing import Optional, TypedDict, Annotated, List, Union


from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langgraph.types import interrupt, Command
from langgraph.graph.message import add_messages
 


load_dotenv()

main_logger = logging.getLogger('main')

executor = concurrent.futures.ThreadPoolExecutor(max_workers=20, thread_name_prefix=__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)

helper_model = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp", google_api_key=GEMINI_API_KEY)


## =============== Defining the dataclass ===============


@dataclass
class TransformedChunk:
    ''' Dataclass for transformed chunk of text containing some information.
    '''
    source_name: str = Field(description='Name of the source')
    url: str = Field(description='URL of the document')
    chunk_number: int = Field(description='Chunk number in the document')
    title: str = Field(description='Title of the text chunk')
    summary: str = Field(description='Summary of the text chunk')
    content: str = Field(description='Exact content of the text chunk')
    embedding: List[float] = Field(description='Embedding vector of the text chunk')


## =============== Defining the helper agent ===============

helper_agent_prompt = ChatPromptTemplate.from_messages([
    ("system", (
        'Extract the title and summary from the chunk of text.'
        'The title should be the document title if the chunk_number is 0, or a sub-title if the chunk is a sub-section of the document.'
        'If no title or subtitle is present, derive a short title from the text chunk.'
        'The summary should provide a brief overview of the text chunk.'
        'Return a JSON object with "title" and "summary" keys.'
    )),
    ("user", "{user_input}"),
])
helper_agent = (helper_agent_prompt | helper_model)


## =============== Constructing etl functions ===============

def chunk_text(text: str, chunk_size: int) -> List[str]:
    """ Chunk a text document into smaller parts, intelligently
        splitting at code blocks, paragraphs, or sentences.

    Args:
        text (str): Text document in markdown format

    Returns:
        List[str]: List of text chunks
    """
    # Split the text into chunks
    chunks = []
    start = 0
    text_length = len(text)

    while start < text_length:
        end = start + chunk_size
        chunk = text[start:end]
        if end >= text_length:
            chunks.append(chunk)
            break
 
        if "```" in chunk:
            new_end = chunk.rfind("```")
        elif "\n\n" in chunk:
            new_end = chunk.rfind("\n\n")
        elif "\n" in chunk:
            new_end = chunk.rfind("\n")
        elif ". " in chunk:
            new_end = chunk.rfind(". ")

        if new_end > chunk_size * 0.5: 
            end = start + new_end
        chunks.append(chunk[:end].strip())
        
        start = end
    return chunks


async def get_embeddings(text_chunk: str, is_document: bool = True) -> List[float]:
    """Get the embedding vector for the text chunk.
    """
    task_type = "RETRIEVAL_QUERY"
    if is_document:
        task_type = "RETRIEVAL_DOCUMENT"

    result = genai.embed_content(
        model="models/text-embedding-004",
        task_type=task_type,
        content=text_chunk)
    embedding = result['embedding']
    if len(embedding) < 1536:
        # pad with zeros at the end
        embedding = np.pad(embedding, (0, 1536 - len(embedding)), 'constant').tolist()
    return embedding

    # try:
    #     response = await openai_client.embeddings.create(
    #         model="text-embedding-3-small",
    #         input=text_chunk
    #     )
    #     print(response.data[0].embedding)
    #     return response.data[0].embedding
    # except Exception as e:
    #     main_logger.error(f"Error getting embedding: {e}")
    #     return [0] * 1536  # Return zero vector on error


async def transform_text_doc(url: str | None, source_name: str, text: str, build_index: bool = False, index: faiss.IndexFlatIP = None) -> List[TransformedChunk]:
    """ Transform a text document into a list of TransformedChunk objects,
        by chunking the text, populating the metadata, and embedding of the chunk.

    Args:
        url (str): URL of the document
        source_name (str): Name of the source
        text (str): Text document in markdown format
        build_index (bool): Whether to build an index of the chunks
        index (faiss.IndexFlatIP): FAISS index to add the chunks to

    Returns:
        List[TransformedChunk]: List of TransformedChunk objects
    """
    chunks = chunk_text(text=text, chunk_size=5000) # chunk size in num characters
    main_logger.info(f"Total chunks: {len(chunks)}")
    transformed_chunks = []
    for i, chunk in enumerate(chunks):
        if not chunk:
            main_logger.debug("Empty chunk")
            continue
        if "csv" in source_name:
            transformed_chunk = {"title": source_name, "summary": "CSV Data"}
        else:
            helper_agent_inputs = {
                "user_input": chunk,
            }
            transformed_chunk = helper_agent.invoke(helper_agent_inputs)
            print(f"Transformed chunk: {transformed_chunk}")
        
        embedding = await get_embeddings(chunk)
        transformed_chunk = TransformedChunk(
            source_name=source_name,
            url=url,
            chunk_number=i,
            title=transformed_chunk['title'],
            summary=transformed_chunk['summary'],
            content=chunk,
            embedding=embedding
        )
        transformed_chunks.append(transformed_chunk)
        if build_index:
            chunk_embedding_np = np.array(transformed_chunk.embedding, dtype='float32').reshape(1, -1)
            faiss.normalize_L2(chunk_embedding_np)
            index.add(chunk_embedding_np)

    return transformed_chunks


def load_text_doc(chunks: List[TransformedChunk]):
    """Insert a processed chunk into Supabase."""
    rows = [asdict(chunk) for chunk in chunks]
    try:
        result = supabase.table("agentic_rag").insert(rows).execute()
        main_logger.info(f"Inserted chunk {len(rows)} for {rows[0].get('url', 'unknown url')}")
        return result
    except Exception as e:
        main_logger.error(f"Error inserting chunk: {e}")
        return None


async def etl_from_url(urls: dict):
    # Crawl the URLs
    browser_config = BrowserConfig(
        headless=True,
        verbose=False,
        extra_args=["--disable-gpu", "--disable-dev-shm-usage", "--no-sandbox"],
    )
    crawl_config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
    web_crawler = AsyncWebCrawler(config=browser_config)
    
    await web_crawler.start()

    for source_name,url in urls.items():
        # await etl_text_doc(web_crawler, url, source_name, crawl_config)
        result = await web_crawler.arun(url=url, config=crawl_config, session_id="session_1")    
        if result.success:
            main_logger.info(f"Successfully crawled url: {url}, markdown length: {len(result.markdown_v2.raw_markdown)}")
            transformed_chunks = await transform_text_doc(url, source_name, result.markdown_v2.raw_markdown)
            load_text_doc(transformed_chunks)
        else:
            main_logger.error(f"Failed: {url} - Error: {result.error_message}")
        

async def match_query_embedding(prompt: str, index: faiss.IndexFlatIP, transformed_chunks: List[TransformedChunk]) -> str:
    top_k =10
    query_embedding = np.array(await get_embeddings(prompt, is_document=False), dtype=np.float32).reshape(1, -1)
    faiss.normalize_L2(query_embedding)
    _, I = index.search(query_embedding, top_k)
    print(f"Top {top_k} matches: {I}")
    matched_chunks = [transformed_chunks[i].content for i in I[0] if i >= 0]
    return "\n\n".join(matched_chunks)



if __name__ == "__main__":
    # use sitemap.xml to fetch all the url endpoints for a website
    asyncio.run(etl_from_url({"pydantic_ai_document":"https://ai.pydantic.dev/agents/"}))


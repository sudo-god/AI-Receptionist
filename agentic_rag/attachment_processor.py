import asyncio
import nest_asyncio
nest_asyncio.apply()

import os
import json
import fs
from dotenv import load_dotenv
import pandas as pd
import docx
from .etl import TransformedChunk, transform_text_doc, get_embeddings
from llama_index.core import Settings, VectorStoreIndex, StorageContext, load_index_from_storage
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.extractors import (
    SummaryExtractor,
    QuestionsAnsweredExtractor,
    TitleExtractor,
    KeywordExtractor,
)
from llama_index.core.ingestion import IngestionPipeline
from llama_index.llms.gemini import Gemini
from llama_index.embeddings.gemini import GeminiEmbedding
from llama_parse import LlamaParse
from typing import Annotated, Any, List, Optional, Dict, Tuple
from llama_index.core.retrievers import QueryFusionRetriever, BaseRetriever
from llama_index.core.postprocessor.llm_rerank import LLMRerank
from llama_index.core.query_engine import RetrieverQueryEngine, PandasQueryEngine
from langchain_core.tools import tool
from io import StringIO
from supabase import create_client
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import InjectedStore, InjectedState
from langgraph.store.base import BaseStore
import yaml
import logging
import logging.config

load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

with open("config/logging.yml", "r") as logging_config_file:
    logging.config.dictConfig(yaml.load(logging_config_file, Loader=yaml.FullLoader))

main_logger = logging.getLogger('main')

llm = Gemini(model="models/gemini-2.0-flash-exp", google_api_key=GEMINI_API_KEY)
transformation_llm = Gemini(model="models/gemini-2.0-flash", google_api_key=GEMINI_API_KEY)
Settings.llm = llm
Settings.embed_model = GeminiEmbedding(model="models/text-embedding-004", google_api_key=GEMINI_API_KEY)


class AttachmentProcessor:
    file_name: str
    transformed_chunks: List[TransformedChunk]
    index: VectorStoreIndex
    rag_pipeline: IngestionPipeline

    def __init__(self, file_name: str):
        self.file_name = file_name
        self.transformed_chunks = []
        self.index = None
        self.rag_pipeline = None

    def process(self) -> None:
        main_logger.info(f"Processing attachment: {self.file_name}")
        if self.file_name.endswith('.png') or\
            self.file_name.endswith('.jpeg') or\
            self.file_name.endswith('.jpg') :
            pass
        elif self.file_name.endswith('.pdf'):
            self.__parse_pdf()
        elif self.file_name.endswith('.csv'):
            self.__parse_csv()
        elif self.file_name.endswith('.txt') or self.file_name.endswith('.text'):
            self.__parse_txt()
        elif self.file_name.endswith('.doc') or self.file_name.endswith('.docx'):
            self.__parse_doc()

    def __parse_pdf(self):
        main_logger.info(f"Processing PDF attachment: {self.file_name}")

        index_storage_path = f"media/uploaded-files/index-storage/{self.file_name}"

        index_store_fs = fs.open_fs(index_storage_path, create=True)
        if index_store_fs.exists("docstore.json"):
            storage_context = StorageContext.from_defaults(persist_dir=index_storage_path)
            try:
                self.index = load_index_from_storage(storage_context, index_id=self.file_name)
                main_logger.info(f"Index from disk: {self.index}")
                return
            except ValueError as e:
                main_logger.info(f"Docstore does not contain index for {self.file_name}")

        file_path = f'media/uploaded-files/raw-files/{self.file_name}'
        parser = LlamaParse(result_type="markdown")
        documents = parser.load_data(file_path)
        self.rag_pipeline = IngestionPipeline(
            documents=documents,
            transformations=[
                SentenceSplitter(chunk_size=1024),
                TitleExtractor(nodes=5, llm=transformation_llm),
                SummaryExtractor(summaries=["self"], llm=transformation_llm),
                KeywordExtractor(keywords=10, llm=transformation_llm),
                # EntityExtractor(prediction_threshold=0.5),
            ]
        )

        nodes = self.rag_pipeline.run(documents)
        main_logger.info(f"Extracted Nodes: {len(nodes)}")

        self.index = VectorStoreIndex(nodes)
        ## save the index to local file
        self.index.set_index_id(self.file_name)
        self.index.storage_context.persist(index_storage_path)


    def __parse_txt(self):
        text = self.attachment.read().decode()
        self.transformed_chunks = transform_text_doc(url=None, source_name=self.file_name, text=text, build_index=True, index=self.index)

    def __parse_csv(self):
        df = pd.read_csv(self.attachment)
        query_engine = PandasQueryEngine(df=df, verbose=True)

    def __parse_doc(self):
        doc = docx.Document(self.attachment)
        text = ""
        for para in doc.paragraphs:
            text += para.text
        self.transformed_chunks = transform_text_doc(url=None, source_name=self.file_name, text=text, build_index=True, index=self.index)

    def __parse_image(self):
        pass


class AttachmentProcessors:
    attachment_processors: Dict[str, Tuple[AttachmentProcessor, BaseRetriever]]
    multi_index_retriever: QueryFusionRetriever
    reranker: LLMRerank
    query_engine: RetrieverQueryEngine

    def __init__(self, attachment_processors: List[AttachmentProcessor] = None):
        self.multi_index_retriever = None
        self.query_engine = None
        self.reranker = LLMRerank(top_n=5, llm=llm)
        self.attachment_processors = {}
        if attachment_processors:
            for processor in attachment_processors:
                self.attachment_processors[processor.file_name] = (processor, processor.index.as_retriever())
            self.__build_query_engine()

    def __build_query_engine(self):
        self.multi_index_retriever = QueryFusionRetriever(
            retrievers=[tup[1] for tup in self.attachment_processors.values()],
            llm=llm,
            similarity_top_k=10,
            num_queries=4,
            mode="simple"
        )
        self.query_engine = RetrieverQueryEngine.from_args(self.multi_index_retriever, node_postprocessors=[self.reranker])

    def add_attachment(self, new_attachment: AttachmentProcessor):
        for attachment,_ in self.attachment_processors.values():
            if attachment.file_name == new_attachment.file_name:
                self.attachment_processors.pop(attachment.file_name)
                break
        self.attachment_processors[new_attachment.file_name] = (new_attachment, new_attachment.index.as_retriever())
        self.__build_query_engine()

    def remove_attachment(self, attachment: AttachmentProcessor):
        self.attachment_processors.pop(attachment.file_name)
        self.__build_query_engine()


helper_agent = ChatGoogleGenerativeAI(model="gemini-2.0-flash-exp", google_api_key=GEMINI_API_KEY)
supabase = create_client(
    os.getenv("SUPABASE_URL"),
    os.getenv("SUPABASE_SERVICE_KEY")
)


def storage_lookup(store: InjectedStore, namespace: tuple, key: str) -> Optional[Any]:
    # print(f"Namespace: {namespace}")
    items = store.search(namespace)
    # print(f"Items: {items}")
    for item in items:
        if item.key == key:
            return item.value
    return None


@tool
async def query_attachments(
    store: Annotated[BaseStore, InjectedStore],
    account_id: Annotated[str, InjectedState("account_id")],
    prompt: Annotated[str, "User's prompt"]
) -> str:
    """ Query the attachments and return the response based on the user's prompt. """
    attachment_processors = None
    namespace = (account_id,)
    attachment_processors = storage_lookup(store, namespace, "attachment_processors")
    main_logger.info(f"Attachment processors from store: {attachment_processors}")

    if attachment_processors is None:
        return "No attachment processors found in storage."
    
    main_logger.info(f"Query engine: {attachment_processors.query_engine}")

    response = await attachment_processors.query_engine.aquery(prompt)
    main_logger.info(f"response {type(response)}: {response.response}")

    return response.response


@tool
def query_database(prompt: Annotated[str, "The user's prompt"]) -> str:
    """ Determine the most relevant source_name(s), based on the user's prompt.

    Args:
        ctx: The context including the Supabase client

    Returns:
        A list of strings which could be the potential source_names for the user prompt.
    """
    user_prompt = prompt

    # try:
    # get all the unique source_name's from the table
    possible_source_names = supabase.table('agentic_rag')\
        .select('source_name')\
        .execute().data
    unique_src_names = set()
    for d in possible_source_names:
        unique_src_names.add(d["source_name"])
    
    engineered_prompt = (
        f'Help me determine the most relevant source_name from a prompt, i.e. the subject of the prompt.'
        f'Choose from the following list of source_name\'s: `{list(unique_src_names)}`.'
        f'You can choose multiple source_name\'s if you think they are relevant.'
        f'If none of the source_name\'s are relevant, return `None`.'
        f'Return a list of the choices made, strictly use double quotes to wrap each source_name.'
        f'Here is the prompt: {user_prompt}'
    )

    result = helper_agent.invoke(engineered_prompt)
    if 'None' in result.content:
        return ""
    result = result.data.strip()
    source_names = json.loads(result[result.find("["):result.rfind("]")+1])
    main_logger.info(f"Most relevant source names {type(source_names)}: {source_names}")
    
    # ------------------------------------------------------------------------------------------------------------
    urls = supabase.from_('agentic_rag')\
        .select('url')\
        .in_('source_name', source_names)\
        .execute().data

    unique_urls = set()
    for d in urls:
        unique_urls.add(d["url"])
    unique_urls = list(unique_urls)

    # try:
    main_logger.info(f"User query: {user_prompt}")
    query_embedding = get_embeddings(user_prompt, is_document=False)
    main_logger.info(f"Source names: {source_names}")
    main_logger.info(f"URLs: {unique_urls}")
    # get the most relevant content from the table
    relevant_content = supabase.rpc(
        'match_agentic_rag',
        {
            'query_embedding': query_embedding,
            'source_names': source_names,
            'urls': unique_urls,
            'match_count': 10
        }
    ).execute().data

    main_logger.info(f"Relevant content: {relevant_content}")
    if not relevant_content:
        return "No relevant content found."
    
    new_content = ''
    for content in relevant_content:
        new_content += f"#{content['title']}\n{content['content']}\n\n"
    main_logger.info(f"NEW CONTENT: {new_content}")
    return new_content
    # except Exception as e:
    #     raise ModelRetry(f"Error retrieving the most relevant content: {e}")
    
    # return source_names
    # except Exception as e:
    #     raise ModelRetry(f"Error determining the most relevant source_name(s): {e}")


def dummy_file_setup():
    import mimetypes
    from streamlit.runtime.uploaded_file_manager import UploadedFile, UploadedFileRec
    from streamlit.proto.Common_pb2 import FileURLs as FileURLsProto

    file_path = "media/uploaded-files/raw-files/Dixit-Resume-C.pdf"
    with open(file_path, "rb") as f:
        file_bytes = f.read()

    # Extract file metadata
    file_name = os.path.basename(file_path)
    mime_type, _ = mimetypes.guess_type(file_path)
    if not mime_type:
        mime_type = "application/octet-stream"

    # Construct the UploadedFile
    file_obj = UploadedFile(record=UploadedFileRec(
                            file_id="1",
                            name=file_name,
                            type=mime_type,
                            data=file_bytes
                        ),
                        file_urls=FileURLsProto(
                            file_id="1",
                            upload_url=file_path,
                            delete_url=file_path
                        )
            )
    return file_obj


if __name__ == "__main__":
    attachment_processors = AttachmentProcessors()

    account_id = "1"
    # namespace = ("attachment_processors", "1")
    namespace = account_id
    attachment_processors_store_key = "attachment_processors"

    from langgraph.store.memory import InMemoryStore
    store = InMemoryStore()
    store.put(namespace, attachment_processors_store_key, attachment_processors)

    file_obj = dummy_file_setup()
    add_new_attachment(store=store, namespace=namespace, key=attachment_processors_store_key, file_obj=file_obj)

    query_attachments.invoke({"store": store, "account_id": account_id, "prompt": "what does the attachment contain"})


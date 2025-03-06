# Agentic RAG

## Conda environment

```bash
conda create -n agentic-rag python=3.10
conda activate agentic-rag
```

## Installing requirements

```bash
pip install -r requirements.txt
```

## Installing faiss-cpu
If you encounter an error installing faiss-cpu, you can install it using:

```bash
conda install pytorch::faiss-cpu
```

Rerun the `pip install` command from above to ensure all the dependencies are installed.

## Running the app

```bash
streamlit run main.py
```
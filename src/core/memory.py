import os
import chromadb
from chromadb.utils import embedding_functions

CHROMA_DB_PATH = ".revi/chroma_db"
COLLECTION_NAME = "codebase_index"

# Ensure the DB directory exists
os.makedirs(CHROMA_DB_PATH, exist_ok=True)

# Initialize ChromaDB
chroma_client = chromadb.PersistentClient(path=CHROMA_DB_PATH)

# We use the default sentence-transformers model from Chroma, which is all-MiniLM-L6-v2
# It downloads automatically the first time it runs
sentence_transformer_ef = embedding_functions.SentenceTransformerEmbeddingFunction(model_name="all-MiniLM-L6-v2")

collection = chroma_client.get_or_create_collection(
    name=COLLECTION_NAME,
    embedding_function=sentence_transformer_ef
)

def chunk_file(filepath: str, content: str) -> list:
    """Split a file into smaller chunks for vector storage."""
    # Simple chunking strategy: split by blank lines or paragraphs to try to keep functions together
    # A more sophisticated approach would use an AST parser, but this works well for a start.
    chunks = []
    
    # Split roughly by double newlines or classes/functions
    lines = content.split('\n')
    current_chunk = []
    chunk_id = 0
    
    for line in lines:
        current_chunk.append(line)
        
        # Check for start of new logical block in Py, JS, HTML, CSS
        is_new_block = (
            line.startswith('def ') or 
            line.startswith('class ') or 
            line.startswith('function ') or 
            line.startswith('const ') or 
            line.startswith('let ') or 
            line.startswith('<div') or 
            line.startswith('<section') or
            (line.strip().endswith('{') and not line.startswith(' '))
        )
        
        if len(current_chunk) >= 40 and is_new_block:
            # Don't split exactly at definition, split before it. So pop it.
            popped = current_chunk.pop()
            if current_chunk:
                chunks.append({
                    "id": f"{filepath}_chunk{chunk_id}",
                    "text": "\n".join(current_chunk),
                    "metadata": {"filepath": filepath}
                })
                chunk_id += 1
            current_chunk = [popped]
        elif len(current_chunk) > 100:
            # Hard limit chunk size
            chunks.append({
                "id": f"{filepath}_chunk{chunk_id}",
                "text": "\n".join(current_chunk),
                "metadata": {"filepath": filepath}
            })
            chunk_id += 1
            current_chunk = []
            
    if current_chunk:
         chunks.append({
            "id": f"{filepath}_chunk{chunk_id}",
            "text": "\n".join(current_chunk),
            "metadata": {"filepath": filepath}
        })
        
    return chunks

def index_file(filepath: str, content: str):
    """Index a single file into ChromaDB."""
    chunks = chunk_file(filepath, content)
    if not chunks:
        return
        
    mtime = os.path.getmtime(filepath) if os.path.exists(filepath) else 0
        
    # Delete existing chunks for this file to prevent duplicates
    try:
        collection.delete(where={"filepath": filepath})
    except Exception:
        pass
        
    ids = [chunk["id"] for chunk in chunks]
    documents = [chunk["text"] for chunk in chunks]
    metadatas = [chunk["metadata"] for chunk in chunks]
    
    for meta in metadatas:
        meta["mtime"] = mtime
    
    collection.add(
        ids=ids,
        documents=documents,
        metadatas=metadatas
    )

def index_codebase(directory: str):
    """Walk a directory and incrementally index all supported files."""
    files_indexed = 0
    files_skipped = 0
    allowed_exts = (".py", ".js", ".jsx", ".ts", ".tsx", ".html", ".css", ".json")
    for root, dirs, files in os.walk(directory):
        # Skip hidden directories and massive build folders
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in ('node_modules', 'build', 'dist', '__pycache__', 'coverage', 'out', 'venv', 'env')]
        
        for file in files:
            if file.endswith(allowed_exts):
                filepath = os.path.join(root, file)
                try:
                    mtime = os.path.getmtime(filepath)
                    
                    # Check if already indexed and up to date
                    existing = collection.get(where={"filepath": filepath}, limit=1)
                    if existing and existing.get('metadatas') and len(existing['metadatas']) > 0:
                        stored_mtime = existing['metadatas'][0].get("mtime", 0)
                        if stored_mtime >= mtime:
                            files_skipped += 1
                            continue
                            
                    with open(filepath, "r", encoding="utf-8") as f:
                        content = f.read()
                    index_file(filepath, content)
                    files_indexed += 1
                except Exception as e:
                    print(f"Failed to index {filepath}: {e}")
                    
    return f"Successfully indexed {files_indexed} files. Skipped {files_skipped} unchanged files."

def semantic_search(query: str, n_results: int = 3):
    """Search the vector database for relevant code chunks."""
    if collection.count() == 0:
        return "The codebase index is empty. Please run index_codebase first."
        
    # Prevent crashing if n_results is greater than the number of chunks
    n_results = min(n_results, collection.count())
        
    results = collection.query(
        query_texts=[query],
        n_results=n_results
    )
    
    if not results['documents'] or not results['documents'][0]:
        return "No relevant code found."
        
    formatted_results = []
    for doc, metadata in zip(results['documents'][0], results['metadatas'][0]):
        filepath = metadata.get("filepath", "Unknown")
        formatted_results.append(f"--- File: {filepath} ---\n{doc}\n-----------------------")
        
    return "\n\n".join(formatted_results)

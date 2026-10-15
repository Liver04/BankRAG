"""Stable parent/child chunks with registered provenance. Unreviewed files fail closed."""
from pathlib import Path
from datetime import datetime
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownTextSplitter
from base.config import config
from base.knowledge import metadata_for,digest,retire_superseded
from base.safety import APPROVED

def _parse_filename(filename):
    import re
    from base.safety import parse_date
    p=Path(filename)
    m=re.search(r'__(\d{8})$',p.stem)
    return (p.stem[:m.start()],parse_date(m.group(1))) if m else (p.stem,0)

def load_documents_from_directory(directory_path):
    root=Path(directory_path)
    docs=[]
    for p in sorted(root.rglob('*')):
        if not p.is_file() or p.suffix.lower() not in {'.md','.txt','.pdf','.docx','.ppt','.pptx','.jpg','.png'}:continue
        # FAQ eligibility/provenance is per answer in MySQL, not per Markdown file.
        # Indexing the whole file would resurrect pending or foreign-scope rows.
        if p.relative_to(root).parts[0]=='faq':continue
        if p.suffix.lower() in {'.md','.txt'}:loaded=[Document(page_content=p.read_text(encoding='utf-8-sig'))]
        else:
            from rag_qa.edu_document_loaders import OCRPDFLoader,OCRDOCLoader,OCRPPTLoader,OCRIMGLoader
            loaders={'.pdf':OCRPDFLoader,'.docx':OCRDOCLoader,'.ppt':OCRPPTLoader,'.pptx':OCRPPTLoader,'.jpg':OCRIMGLoader,'.png':OCRIMGLoader}
            loaded=loaders[p.suffix.lower()](str(p)).load()
        # Page-specific metadata retained; review hash is over the assembled document.
        full='\n'.join(d.page_content for d in loaded)
        meta=metadata_for(p,root,full)
        if meta['review_status']!=APPROVED:continue
        # One logical document avoids replacing one PDF page by another during retirement.
        docs.append(Document(page_content=full,metadata=meta))
    return retire_superseded(docs)

def process_documents(directory_path,parent_chunk_size=config.PARENT_CHUNK_SIZE,
                      child_chunk_size=config.CHILD_CHUNK_SIZE,chunk_overlap=config.CHUNK_OVERLAP):
    parents=MarkdownTextSplitter(chunk_size=parent_chunk_size,chunk_overlap=chunk_overlap)
    children=MarkdownTextSplitter(chunk_size=child_chunk_size,chunk_overlap=chunk_overlap)
    result=[]
    for doc in load_documents_from_directory(directory_path):
        for j,parent in enumerate(parents.split_documents([doc])):
            pid=digest(doc.metadata['doc_id']+doc.metadata['version']+str(j)+parent.page_content)[:48]
            for k,child in enumerate(children.split_documents([parent])):
                child.metadata.update(parent_id=pid,parent_content=parent.page_content,
                    id=digest(pid+str(k)+child.page_content)[:48])
                result.append(child)
    return result

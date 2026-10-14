"""Authenticated knowledge access and administrator PDF ingestion."""
import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.core.security import get_current_user
from app.database import SessionLocal, get_db
from app.models.knowledge import KnowledgeDocument
from app.schemas.knowledge import (
    ConversationContextRequest, ConversationContextResponse, DocumentResponse,
    KnowledgeIngestRequest, KnowledgeIngestResponse, KnowledgeSearchRequest,
    KnowledgeSearchResponse, KnowledgeSearchResult, KnowledgeStats,
    SPINQuestionRequest, SPINQuestionResponse,
)
from app.services.rag import EmbeddingService, PDFParser, TextChunker, VectorStore

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/knowledge", tags=["knowledge"],
                   dependencies=[Depends(get_current_user)])

# Construction is cheap; model loading and the Chroma connection remain lazy.
_pdf_parser = PDFParser()
_text_chunker = TextChunker(chunk_size=500, overlap=50)
_embedding_service = EmbeddingService()
_vector_store = VectorStore(use_milvus=False)


def require_knowledge_admin(user=Depends(get_current_user)):
    if not (user.is_superuser or user.role == "admin"):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


def resolve_knowledge_pdf(file_path: str) -> Path:
    """Resolve and validate again in the worker, including symlink containment."""
    try:
        requested = Path(file_path)
        if ".." in requested.parts or ".." in PureWindowsPath(file_path).parts:
            raise HTTPException(status_code=400, detail="Invalid document path")
        if requested.suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
        root = Path(settings.KNOWLEDGE_DATA_DIR).resolve()
        candidate = (requested if requested.is_absolute() else root / requested).resolve()
        if not candidate.is_relative_to(root):
            raise HTTPException(status_code=400, detail="Document must be inside the knowledge directory")
        if candidate.suffix.lower() != ".pdf":
            raise HTTPException(status_code=400, detail="Only PDF files are supported")
        if not candidate.exists():
            raise HTTPException(status_code=404, detail="Document not found")
        if not candidate.is_file():
            raise HTTPException(status_code=400, detail="Document must be a PDF file")
        return candidate
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(status_code=400, detail="Invalid document path") from None


def _queue_document(db: Session, pdf_path: Path, category: str) -> KnowledgeDocument:
    root = Path(settings.KNOWLEDGE_DATA_DIR).resolve()
    document = KnowledgeDocument(name=pdf_path.name, source_type="pdf", category=category,
                                 file_path=str(pdf_path.relative_to(root)), status="queued")
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _write_vectors(chunks: list[dict], document_id: str) -> None:
    """Persist precomputed vectors without the legacy wrapper's silent fallback."""
    _vector_store._connect()
    collection = _vector_store._collection
    if collection is None:
        raise RuntimeError("Persistent vector storage unavailable")
    for start in range(0, len(chunks), 1000):
        batch = chunks[start:start + 1000]
        collection.upsert(
            ids=[f"{document_id}_{start + index}" for index in range(len(batch))],
            documents=[chunk["text"] for chunk in batch],
            embeddings=[chunk["embedding"] for chunk in batch],
            metadatas=[{**chunk.get("metadata", {}), "source": chunk["source"],
                        "document_id": document_id} for chunk in batch],
        )


async def ingest_document(document_id: str) -> None:
    """In-process background work with its own SQL session and persisted outcome."""
    with SessionLocal() as db:
        document = db.get(KnowledgeDocument, document_id)
        if document is None or document.status != "queued":
            return
        path, category = document.file_path, document.category
        document.status = "processing"
        db.commit()
    try:
        pdf_path = resolve_knowledge_pdf(path)
        parsed = await asyncio.to_thread(_pdf_parser.parse_file, str(pdf_path))
        chunks = await asyncio.to_thread(
            _text_chunker.chunk_by_paragraph, parsed["full_text"],
            source=pdf_path.name,
            metadata={"category": category, "page_count": parsed["page_count"]},
        )
        if not chunks:
            raise ValueError("PDF has no extractable knowledge text")
        embedded = await _embedding_service.embed_with_metadata(chunks, source_name=pdf_path.name)
        if len(embedded) != len(chunks):
            raise ValueError("Incomplete embedding result")
        await asyncio.to_thread(_write_vectors, embedded, document_id)
        status, count, error = "completed", len(embedded), None
    except Exception:
        logger.exception("Knowledge ingestion failed for document %s", document_id)
        try:
            if _vector_store._collection is not None:
                await asyncio.to_thread(_vector_store._collection.delete,
                                        where={"document_id": document_id})
        except Exception:
            logger.exception("Could not clean partial vectors for document %s", document_id)
        status, count, error = "failed", 0, "Document processing failed; verify the PDF and retry"
    with SessionLocal() as db:
        document = db.get(KnowledgeDocument, document_id)
        if document is not None:
            document.status, document.chunk_count, document.error = status, count, error
            document.processed_at = datetime.now(timezone.utc)
            db.commit()


def recover_interrupted_ingestions() -> int:
    """Single-worker startup: remove partial vectors before failing interrupted jobs."""
    with SessionLocal() as db:
        interrupted = db.query(KnowledgeDocument).filter(
            KnowledgeDocument.status.in_(["queued", "processing"])).all()
        if not interrupted:
            return 0
        try:
            # No model loading: connect only the persisted Chroma collection,
            # and only when unfinished work needs recovery.
            _vector_store._connect()
            if _vector_store._collection is None:
                raise RuntimeError("Persistent vector storage unavailable")
            for document in interrupted:
                _vector_store._collection.delete(where={"document_id": document.id})
        except Exception:
            # Leave SQL unfinished so the next startup can retry idempotently.
            # The lifespan caller must abort startup instead of serving partial
            # vectors while claiming that recovery completed.
            logger.exception("Interrupted knowledge vectors could not be removed")
            raise RuntimeError("Knowledge recovery blocked: interrupted vectors could not be removed") from None
        for document in interrupted:
            document.status = "failed"
            document.chunk_count = 0
            document.error = "Processing interrupted by service restart; submit the document again"
            document.processed_at = datetime.now(timezone.utc)
        db.commit()
        return len(interrupted)


def _search_result(result: dict) -> KnowledgeSearchResult:
    # A legacy vector record may contain an absolute source/full_path.
    source = Path(PureWindowsPath(result.get("source", "")).name).name
    allowed = {"category", "chapter", "section", "spin_stage", "page_count", "source"}
    metadata = {key: value for key, value in result.get("metadata", {}).items() if key in allowed}
    if "source" in metadata:
        metadata["source"] = source
    return KnowledgeSearchResult(id=result["id"], text=result["text"], source=source,
                                 score=result["score"], metadata=metadata)


async def _search(query: str, top_k: int = 5, source_filter: str | None = None) -> list[dict]:
    try:
        embedding = await _embedding_service.embed_text(query)
        return await asyncio.to_thread(_vector_store.search, query_embedding=embedding,
                                       top_k=top_k, source_filter=source_filter)
    except Exception:
        logger.exception("Knowledge search failed")
        raise HTTPException(status_code=503, detail="Knowledge search is temporarily unavailable") from None


@router.post("/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(request: KnowledgeSearchRequest):
    results = await _search(request.query, max(request.top_k * 5, request.top_k), request.source_filter)
    seen_ids = {}
    for result in results:
        cid = result.get("id")
        previous = seen_ids.get(cid)
        if previous is None or len(result.get("text", "")) > len(previous.get("text", "")):
            seen_ids[cid] = result
    seen_keys, deduped = set(), []
    for result in sorted(seen_ids.values(), key=lambda item: -item.get("score", 0)):
        if request.category and result.get("metadata", {}).get("category") != request.category:
            continue
        key = (result.get("source", ""), result.get("metadata", {}).get("chapter", ""),
               (result.get("text", "") or "")[:80])
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append(_search_result(result))
        if len(deduped) >= request.top_k:
            break
    return KnowledgeSearchResponse(results=deduped, query=request.query, total=len(deduped))


@router.post("/ingest", response_model=KnowledgeIngestResponse,
             dependencies=[Depends(require_knowledge_admin)])
async def ingest_document_endpoint(request: KnowledgeIngestRequest, background_tasks: BackgroundTasks,
                                   db: Session = Depends(get_db)):
    document = _queue_document(db, resolve_knowledge_pdf(request.file_path), request.category)
    background_tasks.add_task(ingest_document, document.id)
    return KnowledgeIngestResponse(document_id=document.id, status="queued", chunk_count=0,
                                   message="Document queued for processing")


@router.get("/documents", response_model=list[DocumentResponse])
async def list_documents(db: Session = Depends(get_db)):
    return db.query(KnowledgeDocument).order_by(KnowledgeDocument.created_at, KnowledgeDocument.id).all()


@router.get("/documents/{doc_id}", response_model=DocumentResponse)
async def get_document(doc_id: str, db: Session = Depends(get_db)):
    document = db.get(KnowledgeDocument, doc_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.get("/stats", response_model=KnowledgeStats)
async def get_knowledge_stats(db: Session = Depends(get_db)):
    try:
        counts = await asyncio.to_thread(_vector_store.count)
    except Exception:
        logger.exception("Knowledge statistics unavailable")
        raise HTTPException(status_code=503, detail="Knowledge statistics are temporarily unavailable") from None
    documents = db.query(KnowledgeDocument).all()
    categories, sources = {}, {}
    for document in documents:
        categories[document.category] = categories.get(document.category, 0) + 1
        if document.status == "completed":
            sources[document.name] = sources.get(document.name, 0) + document.chunk_count
    return KnowledgeStats(total_documents=len(documents), total_chunks=counts.get("total", 0),
                          documents_by_category=categories, chunks_by_source=sources)


@router.post("/spin/questions", response_model=SPINQuestionResponse)
async def generate_spin_questions(request: SPINQuestionRequest):
    query = f"{request.customer_industry} {request.customer_scale} " + " ".join(request.pain_points)
    results = await _search(query)
    return SPINQuestionResponse(
        situation_questions=[f"请描述一下{request.customer_industry}行业当前的发展状况？",
                             "贵公司目前的业务规模有多大？", "你们目前有多少销售团队成员？"],
        problem_questions=[f"在{request.customer_industry}行业，您遇到最大的挑战是什么？",
                           f"目前销售团队在{request.pain_points[0] if request.pain_points else '客户开发'}方面表现如何？",
                           "您认为现有销售流程中有哪些地方可以改进？"],
        implication_questions=["这个问题如果不解决，对您的业务会有什么影响？", "市场竞争日益激烈，这给您带来了哪些压力？",
                               "如果成单周期继续延长，会影响哪些关键指标？"],
        need_payoff_questions=["如果有一种方法能帮您缩短成单周期，您想了解吗？", "您希望通过这次合作实现什么具体目标？",
                               "对我们来说，最重要的是帮您解决什么问题？"],
        context_used=[result["text"][:100] + "..." for result in results[:3]],
    )


@router.post("/conversation/context", response_model=ConversationContextResponse)
async def get_conversation_context(request: ConversationContextRequest):
    query = (f"{request.scenario_type} {request.customer_profile.get('industry', '')} "
             f"{request.customer_profile.get('role', '')} {request.topic_focus or ''}")
    results = await _search(query)
    return ConversationContextResponse(
        relevant_knowledge=[_search_result(result) for result in results],
        suggested_topics=[request.scenario_type, request.customer_profile.get("industry", "")],
        talking_points=[result["text"][:200] + "..." for result in results[:3] if len(result["text"]) > 50],
    )


@router.post("/ingest-all", response_model=dict, dependencies=[Depends(require_knowledge_admin)])
async def ingest_all_documents(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    root = Path(settings.KNOWLEDGE_DATA_DIR).resolve()
    if not root.is_dir():
        raise HTTPException(status_code=404, detail="Knowledge directory not found")
    results = []
    for candidate in sorted(root.iterdir()):
        if candidate.suffix.lower() != ".pdf":
            continue
        try:
            path = resolve_knowledge_pdf(str(candidate))
        except HTTPException:
            results.append({"file": candidate.name, "status": "failed", "chunks": 0,
                            "error": "Invalid PDF document"})
            continue
        name = path.name.lower()
        category = ("spin" if "spin" in name else "strategic_marketing" if "战略营销" in name
                    else "solution_selling" if "解决方案销售" in name or "solution" in name else "general")
        document = _queue_document(db, path, category)
        background_tasks.add_task(ingest_document, document.id)
        results.append({"file": document.name, "document_id": document.id, "status": "queued", "chunks": 0})
    return {"total": len(results), "results": results}

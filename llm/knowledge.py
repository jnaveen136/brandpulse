"""Knowledge base for the Q&A layer (the retrieval half of RAG).

Holds the *non-numeric* context the model needs to interpret numbers: KPI
definitions and formulas, business rules (competitor matching, Health Score),
data caveats from validation, and each core brand's competitive set.
Numbers never come from here; they come from the KPI tools.

Retrieval is hybrid: semantic search in a persistent Chroma collection with
free local all-MiniLM-L6-v2 embeddings (ONNX), fused with BM25 keyword search
by reciprocal-rank fusion. Without chromadb installed it uses BM25 alone.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import Counter
from pathlib import Path

from kpi import registry as R
from kpi import time_intel as T
from pipeline.schema import CORE_BRANDS

ROOT = Path(__file__).resolve().parents[1]
CHROMA_DIR = ROOT / "data" / "chroma"
_TOKEN = re.compile(r"[a-z0-9&%]+")


def _tokens(s: str) -> list[str]:
    return _TOKEN.findall(s.lower())


def build_chunks(service) -> list[dict]:
    chunks = []
    for k in R.KPIS:
        chunks.append({"id": f"kpi:{k.id}", "source": "KPI registry", "title": k.name,
                       "text": f"{k.name} (id {k.id}, group {k.group}, unit {k.unit}). {k.description} "
                               f"Formula: {k.formula_text}. {'Higher is better.' if k.higher_is_better else 'Lower is better.'} "
                               f"{k.scope_note}".strip()})
    chunks.append({"id": "time:presets", "source": "Time Intelligence", "title": "Period presets",
                   "text": "Periods: " + "; ".join(f"{k} = {v}" for k, v in T.PRESETS.items())
                           + ". Comparisons: previous period (the period just before, same shape: MTD vs the same days last "
                             "month) or same period last year (yoy). Data runs 1 Jan 2024 to 30 Dec 2025."})
    dec = ROOT / "docs" / "DECISIONS.md"
    if dec.exists():
        section = "Decisions"
        for line in dec.read_text(encoding="utf-8").splitlines():
            if line.startswith("## "):
                section = line[3:].strip()
            elif line.startswith("- ") or (line.startswith("|") and not line.startswith("|---") and "Caveat" not in line):
                text = re.sub(r"[*`|]", " ", line.lstrip("- ")).strip()
                chunks.append({"id": f"rule:{hashlib.md5(text.encode()).hexdigest()[:10]}", "source": "docs/DECISIONS.md",
                               "title": section, "text": f"{section}: {re.sub(r' +', ' ', text)}"})
    dq = ROOT / "reports" / "data_quality.json"
    if dq.exists():
        for r in json.loads(dq.read_text(encoding="utf-8"))["results"]:
            if not r["passed"] or r["severity"] == "info":
                chunks.append({"id": f"caveat:{r['check']}", "source": "Data validation", "title": r["check"],
                               "text": f"Data caveat ({r['sheet']}): {r['detail']}"})
    comp = service.c
    for b in CORE_BRANDS:
        cr = comp.closest_rivals(b)
        subs = comp.subcategories(b)
        chunks.append({"id": f"comp:{b}", "source": "Competitor mapping", "title": f"{b} competitive set",
                       "text": f"{b} (Reckitt) sells in sub-categories {', '.join(subs)}. External rivals by number of {b} "
                               "variants they compete with: " + ", ".join(
                                   f"{r.RivalBrand} ({r.RivalManufacturer}) {r.variants_overlapped} of {r.total_variants} in "
                                   f"{'/'.join(r.subcategories)}" for r in cr.itertuples())
                               + f". Market share data for {b}: {'yes' if b in set(service.e.m.market_share['Brand']) else 'no'}."})
    return chunks


class BM25:
    def __init__(self, docs: list[str], k1: float = 1.4, b: float = 0.75):
        self.docs = [_tokens(d) for d in docs]
        self.avg = sum(map(len, self.docs)) / max(len(self.docs), 1)
        self.df = Counter(t for d in self.docs for t in set(d))
        self.n, self.k1, self.b = len(self.docs), k1, b
        self.tf = [Counter(d) for d in self.docs]

    def scores(self, q: str) -> list[float]:
        qt = _tokens(q)
        out = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for t in qt:
                if t not in tf:
                    continue
                idf = math.log(1 + (self.n - self.df[t] + 0.5) / (self.df[t] + 0.5))
                s += idf * tf[t] * (self.k1 + 1) / (tf[t] + self.k1 * (1 - self.b + self.b * len(self.docs[i]) / self.avg))
            out.append(s)
        return out


_INIT_LOCK = threading.Lock()  # one embedding-model download / index build per process, never two at once


class Knowledge:
    """Keyword search works the moment this is created. The semantic index (which may need a one-off
    79 MB model download) is built in a background thread and joins in when it is ready."""

    def __init__(self, service, background: bool = True):
        self.chunks = build_chunks(service)
        self.bm25 = BM25([c["title"] + " " + c["text"] for c in self.chunks])
        self.collection = None
        self.ready = threading.Event()
        try:
            import chromadb  # noqa: F401
        except ImportError:
            self.mode = "bm25 (chromadb not installed)"
            self.ready.set()
            return
        self.mode = "bm25 (semantic index loading)"
        if background:
            threading.Thread(target=self._init_semantic, name="knowledge-index", daemon=True).start()
        else:
            self._init_semantic()

    def wait(self, timeout: float | None = None) -> bool:
        """Block until the semantic index is ready (or has failed). Used by the evaluation and tests."""
        return self.ready.wait(timeout)

    def _init_semantic(self) -> None:
        try:
            with _INIT_LOCK:
                import chromadb
                from chromadb.utils import embedding_functions as ef
                self._client = chromadb.PersistentClient(path=str(CHROMA_DIR))
                self._ef = ef.DefaultEmbeddingFunction()
                # One collection per knowledge-base version. Old versions are left in place: another process
                # (API, tests, evaluation) may still be reading them; they are small and rebuilt on `make data`.
                self._name = "brandpulse_" + hashlib.md5(json.dumps(self.chunks, sort_keys=True).encode()).hexdigest()[:12]
                self._open()
                self.mode = "hybrid (Chroma all-MiniLM-L6-v2 + BM25)"
        except Exception as e:  # model download failed, offline, ...: keyword search keeps working
            self.collection = None
            self.mode = f"bm25 (semantic index unavailable: {type(e).__name__})"
        finally:
            self.ready.set()

    def _open(self) -> None:
        col = self._client.get_or_create_collection(self._name, embedding_function=self._ef,
                                                    metadata={"hnsw:space": "cosine"})
        if col.count() != len(self.chunks):
            col.upsert(ids=[c["id"] for c in self.chunks], documents=[c["text"] for c in self.chunks],
                       metadatas=[{"source": c["source"], "title": c["title"]} for c in self.chunks])
        self.collection = col  # only published once fully built, so searches never see a half-built index

    def _semantic(self, query: str) -> list[str]:
        for attempt in range(2):
            col = self.collection
            if col is None:
                return []
            try:
                return col.query(query_texts=[query], n_results=min(20, len(self.chunks)))["ids"][0]
            except Exception:
                if attempt == 0:
                    try:
                        with _INIT_LOCK:
                            self._open()  # collection removed underneath us: rebuild once
                        continue
                    except Exception:
                        pass
                self.collection, self.mode = None, "bm25 (semantic index unavailable)"
        return []

    def search(self, query: str, k: int = 4) -> list[dict]:
        ranks: dict[int, float] = {}
        bm = self.bm25.scores(query)
        for r, i in enumerate(sorted(range(len(bm)), key=lambda i: -bm[i])[:20]):
            if bm[i] > 0:
                ranks[i] = ranks.get(i, 0) + 1 / (60 + r)
        if self.collection is not None:
            idx = {c["id"]: i for i, c in enumerate(self.chunks)}
            for r, cid in enumerate(self._semantic(query)):
                if cid in idx:
                    ranks[idx[cid]] = ranks.get(idx[cid], 0) + 1 / (60 + r)
        best = sorted(ranks, key=lambda i: -ranks[i])[:k]
        return [{"source": self.chunks[i]["source"], "title": self.chunks[i]["title"], "text": self.chunks[i]["text"]} for i in best]


if __name__ == "__main__":
    # Pre-download the embedding model and build the index:  python -m llm.knowledge
    from api.service import Service
    print("Building the knowledge index (first run downloads the 79 MB all-MiniLM-L6-v2 model once)...")
    kb = Knowledge(Service(), background=False)
    print(f"Done: {len(kb.chunks)} passages, retrieval = {kb.mode}")

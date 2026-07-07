"""Shared search + ingest for Fuche RAG. Single import used by fuche, plugin, cascade."""

import csv, hashlib, json, os, re, sys, time, socket, threading
from pathlib import Path

import numpy as np

try:
    import faiss
    HAS_FAISS = True
except ImportError:
    HAS_FAISS = False

_MODEL = None

def _get_model():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer("all-MiniLM-L6-v2", device="cuda")
    return _MODEL

EMBED_MODEL = "all-MiniLM-L6-v2"
BASE_RAG = os.path.expanduser("~/.fuche")
DIM = 384
BATCH_SIZE = 20
MAX_CHARS = 600
MIN_CHUNK = 20
OVERLAP = 100
SKIP_DIRS = {
    "node_modules", ".venv", "venv", ".git", "target", "__pycache__",
    ".next", "dist", ".cache", "build", "vendor", ".svelte-kit",
    ".trunk", "out", "_build", ".ruff_cache", ".pytest_cache", "result",
}
EXTS = {
    ".txt", ".md", ".py", ".rs", ".js", ".ts", ".html", ".css",
    ".json", ".yaml", ".toml", ".sh", ".c", ".h", ".java", ".go",
    ".rb", ".php", ".vue", ".svelte", ".jsx", ".tsx",
}


def _no_proxy():
    for k in list(os.environ.keys()):
        if "proxy" in k.lower():
            os.environ.pop(k, None)


def _gpu_resources():
    if not HAS_FAISS:
        return None
    try:
        ngpu = faiss.get_num_gpus()
        if ngpu > 0:
            res = faiss.StandardGpuResources()
            res.setDefaultNullStreamAllDevices()
            return res
    except Exception:
        pass
    return None


GPU_RES = _gpu_resources()


def embed(texts):
    model = _get_model()
    single = isinstance(texts, str)
    inputs = [texts] if single else texts
    inputs = [t[:MAX_CHARS] if len(t) > MAX_CHARS else t for t in inputs]
    embs = model.encode(inputs, normalize_embeddings=True, show_progress_bar=False)
    embs = np.array(embs, dtype=np.float32)
    if embs.ndim == 1:
        embs = embs.reshape(1, -1)
    return embs


def _collection_path(collection=""):
    return os.path.join(BASE_RAG, collection) if collection else BASE_RAG


def _faiss_path(coll_path):
    return os.path.join(coll_path, "index.faiss")


def _ids_path(coll_path):
    return os.path.join(coll_path, "embedding_ids.csv")


def _manifest_path(coll_path):
    return os.path.join(coll_path, "manifest.csv")


def _build_index(embeddings, ids):
    if not HAS_FAISS or len(embeddings) < 1:
        return None
    index = faiss.IndexFlatIP(DIM)
    if GPU_RES:
        index = faiss.index_cpu_to_gpu(GPU_RES, 0, index)
    index.add(embeddings)
    return index


def load_index(collection=""):
    coll_path = _collection_path(collection)
    fp = _faiss_path(coll_path)
    ids_path = _ids_path(coll_path)
    manifest_path = _manifest_path(coll_path)

    src_map = {}
    snip_map = {}
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            for row in csv.reader(f):
                if row:
                    src_map[row[0]] = row[1] if len(row) > 1 else "?"
                    snip_map[row[0]] = row[2] if len(row) > 2 else ""

    emb_ids = []
    if os.path.exists(ids_path):
        emb_ids = [l.strip() for l in open(ids_path) if l.strip()]

    index = None
    if os.path.exists(fp) and HAS_FAISS:
        index = faiss.read_index(fp)
        if GPU_RES:
            index = faiss.index_cpu_to_gpu(GPU_RES, 0, index)

    return {
        "index": index,
        "emb_ids": emb_ids,
        "src_map": src_map,
        "snip_map": snip_map,
        "coll_path": coll_path,
        "emb_path": os.path.join(coll_path, "embeddings.npy"),
    }


def _keyword_score(query, snippet):
    qwords = set(w.lower() for w in re.findall(r"\w+", query) if len(w) > 2)
    if not qwords:
        return 0.0
    sw = set(w.lower() for w in re.findall(r"\w+", snippet))
    matches = qwords & sw
    return len(matches) / len(qwords)


def search(query, collection="", top_k=10, file_type=""):
    _no_proxy()
    state = load_index(collection)
    if not state["emb_ids"]:
        return []

    qv = embed(query)[0]
    fetch_k = min(top_k * 3 + 20, len(state["emb_ids"]))

    if state["index"] is not None:
        scores, indices = state["index"].search(qv.reshape(1, -1), fetch_k)
        scores = scores[0]
        indices = indices[0]
    else:
        embs = np.load(state["emb_path"])
        scores = qv @ embs.T
        indices = np.argsort(scores)[::-1][:fetch_k]
        scores = scores[indices]

    # Hybrid: combine FAISS score + keyword overlap
    results = []
    for i, idx in enumerate(indices):
        if idx < 0 or idx >= len(state["emb_ids"]):
            continue
        h = state["emb_ids"][idx]
        src = state["src_map"].get(h, "?")
        snip = state["snip_map"].get(h, "")
        if file_type and not src.endswith(file_type):
            continue
        kw = _keyword_score(query, snip)
        combined = 0.6 * float(scores[i]) + 0.4 * kw
        results.append((combined, float(scores[i]), kw, src, snip))

    # Rerank by combined score
    results.sort(key=lambda r: r[0], reverse=True)
    return results[:top_k]


def chunk_text(text, max_chars=MAX_CHARS, overlap=OVERLAP, min_chunk=MIN_CHUNK):
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks = []
    current = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue
        if current and len(current) + len(sent) > max_chars:
            chunks.append(current)
            if overlap > 0 and len(current) > overlap:
                current = current[-overlap:]
            else:
                current = ""
        current = (current + " " + sent).strip() if current else sent
    if current:
        chunks.append(current)
    return [c for c in chunks if len(c) >= min_chunk]


def ingest_directory(root, collection=""):
    _no_proxy()
    coll_path = _collection_path(collection)
    os.makedirs(coll_path, exist_ok=True)

    manifest_path = _manifest_path(coll_path)
    ids_path = _ids_path(coll_path)
    emb_path = os.path.join(coll_path, "embeddings.npy")
    faiss_path_ = _faiss_path(coll_path)

    existing_hashes = set()
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            for line in f:
                h = line.strip().split(",")[0]
                if h:
                    existing_hashes.add(h)

    print(f"  walking {root} ...", flush=True)
    texts_map = {}
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            ext = os.path.splitext(fn)[1].lower()
            if ext not in EXTS:
                continue
            fpath = os.path.join(dirpath, fn)
            try:
                with open(fpath, "r", errors="ignore") as f:
                    text = f.read()
            except Exception:
                continue
            rel = os.path.relpath(fpath, root)
            for c in chunk_text(text):
                c = c.strip()
                if len(c) < MIN_CHUNK:
                    continue
                h = hashlib.sha256(c.encode()).hexdigest()
                if h in existing_hashes:
                    continue
                with open(manifest_path, "a") as f:
                    snippet = c[:MAX_CHARS].replace("\n", " ").replace(",", " ").strip()
                    f.write(f"{h},{rel},{snippet}\n")
                existing_hashes.add(h)
                texts_map[h] = c[:MAX_CHARS]
                count += 1
                if count % 100 == 0:
                    print(f"  chunked {count} ...", flush=True)

    print(f"  found {count} new chunks in {root}", flush=True)

    existing_ids = set()
    if os.path.exists(ids_path):
        existing_ids = set(l.strip() for l in open(ids_path) if l.strip())

    all_hashes = []
    with open(manifest_path) as f:
        for line in f:
            h = line.strip().split(",")[0]
            if h and h not in existing_ids and h in texts_map:
                all_hashes.append(h)

    if not all_hashes:
        old_count = len(existing_ids)
        print(f"  all {old_count} chunks already embedded", flush=True)
        if os.path.exists(emb_path) and HAS_FAISS and not os.path.exists(faiss_path_):
            print("  rebuilding FAISS index from existing embeddings...", flush=True)
            rebuild_index(collection)
        return

    total = len(all_hashes)
    print(f"  embedding {total} chunks (batch={BATCH_SIZE}) ...", flush=True)
    all_embs = []
    for start in range(0, total, BATCH_SIZE):
        batch = all_hashes[start:start + BATCH_SIZE]
        texts = [texts_map.get(h, "") for h in batch]
        if not any(texts):
            continue
        try:
            embs = embed(texts)
            all_embs.append(embs)
            n = start // BATCH_SIZE + 1
            tot = (total + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"    batch {n}/{tot} done ({len(batch)} chunks)", flush=True)
        except Exception as e:
            print(f"    batch {n} FAILED: {e}, retrying individually...", flush=True)
            for h in batch:
                t = texts_map.get(h, "")
                if not t:
                    continue
                try:
                    e = embed([t])
                    all_embs.append(e)
                except Exception:
                    pass

    if all_embs:
        new_matrix = np.vstack(all_embs)
        if os.path.exists(emb_path):
            old_matrix = np.load(emb_path)
            emb_matrix = np.vstack([old_matrix, new_matrix])
        else:
            emb_matrix = new_matrix
        np.save(emb_path, emb_matrix)

        with open(ids_path, "a") as f:
            for h in all_hashes:
                f.write(h + "\n")

        new_count = len(all_hashes)
        total_count = len(existing_ids) + new_count
        print(f"  done — embedded {new_count} new chunks (total {total_count})", flush=True)

        if HAS_FAISS:
            print("  building FAISS index...", flush=True)
            index = _build_index(emb_matrix, None)
            if index:
                if GPU_RES:
                    index = faiss.index_gpu_to_cpu(index)
                faiss.write_index(index, faiss_path_)
                print(f"  FAISS index saved ({emb_matrix.shape[0]} vectors)", flush=True)


def rebuild_index(collection=""):
    coll_path = _collection_path(collection)
    emb_path = os.path.join(coll_path, "embeddings.npy")
    faiss_path_ = _faiss_path(coll_path)
    if not os.path.exists(emb_path):
        print(f"  no embeddings at {emb_path}", flush=True)
        return
    embs = np.load(emb_path)
    if len(embs) < 1:
        print("  empty embeddings", flush=True)
        return
    index = _build_index(embs, None)
    if index:
        if GPU_RES:
            index = faiss.index_gpu_to_cpu(index)
        faiss.write_index(index, faiss_path_)
        print(f"  FAISS index rebuilt ({embs.shape[0]} vectors)", flush=True)


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "search":
        coll = ""
        top_k = 10
        file_type = ""
        rest = []
        i = 2
        while i < len(sys.argv):
            if sys.argv[i] == "--collection" and i + 1 < len(sys.argv):
                coll = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--top-k" and i + 1 < len(sys.argv):
                top_k = int(sys.argv[i + 1])
                i += 2
            elif sys.argv[i] == "--type" and i + 1 < len(sys.argv):
                file_type = sys.argv[i + 1]
                i += 2
            else:
                rest.append(sys.argv[i])
                i += 1
        query = " ".join(rest)
        if not query:
            print("usage: search.py search [--collection <name>] [--top-k <n>] [--type .md|.py|.rs] <query>")
            sys.exit(1)
        results = search(query, coll, top_k, file_type)
        print(f"Top {len(results)} for \"{query}\":")
        print("─" * 66)
        for i, (combined, faiss_s, kw_s, src, snip) in enumerate(results):
            print(f"{i+1}.  combined={combined:.3f} faiss={faiss_s:.3f} kw={kw_s:.3f}  {src}")
            print(f"     {snip}")
            print()
    elif cmd == "ingest":
        root = sys.argv[2] if len(sys.argv) > 2 else "."
        coll = ""
        if len(sys.argv) > 3 and sys.argv[3] == "--collection":
            coll = sys.argv[4] if len(sys.argv) > 4 else ""
        ingest_directory(root, coll)
    elif cmd == "reindex":
        coll = sys.argv[2] if len(sys.argv) > 2 else ""
        rebuild_index(coll)
    elif cmd == "--daemon":
        _no_proxy()
        sock_path = "/tmp/search-daemon.sock"
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        state = load_index("")
        state_lock = threading.Lock()
        _get_model()

        def _reload_loop():
            while True:
                time.sleep(3600)
                try:
                    new_state = load_index("")
                    with state_lock:
                        state.clear()
                        state.update(new_state)
                    print(f"  [{time.strftime('%H:%M:%S')}] index reloaded ({len(state['emb_ids'])} vectors)", flush=True)
                except Exception as e:
                    print(f"  [{time.strftime('%H:%M:%S')}] reload failed: {e}", flush=True)

        threading.Thread(target=_reload_loop, daemon=True).start()

        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(sock_path)
        server.listen(5)
        os.chmod(sock_path, 0o666)

        def handle(conn):
            f = conn.makefile("r", buffering=1)
            w = conn.makefile("w", buffering=1)
            for line in f:
                try:
                    msg = json.loads(line.strip())
                    if msg.get("cmd") == "ingest":
                        root = msg.get("path", ".")
                        coll = msg.get("collection", "")
                        ingest_directory(root, coll)
                        w.write(json.dumps({"status": "ok", "path": root}) + "\n")
                        w.flush()
                        continue
                    q = msg.get("query", "")
                    top_k = msg.get("top_k", 10)
                    coll = msg.get("collection", "")
                    ft = msg.get("file_type", "")
                    with state_lock:
                        current_state = state if not coll else load_index(coll)
                    results = []
                    qv = embed(q)[0]
                    fetch_k = min(top_k * 3 + 20, len(current_state["emb_ids"]))
                    if current_state["index"] is not None:
                        scores, indices = current_state["index"].search(qv.reshape(1, -1), fetch_k)
                        scores, indices = scores[0], indices[0]
                    else:
                        embs = np.load(current_state["emb_path"])
                        scores = qv @ embs.T
                        indices = np.argsort(scores)[::-1][:fetch_k]
                        scores = scores[indices]
                    for i, idx in enumerate(indices):
                        if idx < 0 or idx >= len(current_state["emb_ids"]):
                            continue
                        h = current_state["emb_ids"][idx]
                        src = current_state["src_map"].get(h, "?")
                        snip = current_state["snip_map"].get(h, "")
                        if ft and not src.endswith(ft):
                            continue
                        kw = _keyword_score(q, snip)
                        combined = 0.6 * float(scores[i]) + 0.4 * kw
                        results.append((combined, float(scores[i]), kw, src, snip))
                    results.sort(key=lambda r: r[0], reverse=True)
                    results = results[:top_k]
                    w.write(json.dumps({"results": [{"combined": r[0], "faiss": r[1], "kw": r[2], "source": r[3], "snippet": r[4][:200]} for r in results]}) + "\n")
                    w.flush()
                except Exception:
                    w.write(json.dumps({"results": []}) + "\n")
                    w.flush()
            conn.close()

        while True:
            conn, _ = server.accept()
            threading.Thread(target=handle, args=(conn,), daemon=True).start()
    else:
        print("Usage: search.py [search|ingest|reindex|--daemon] ...")

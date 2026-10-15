"""Model-based components for real runs (optional extras, see requirements-real.txt).

- DenseRetriever: a sentence-transformers embedding model, cosine similarity
  over normalized embeddings of each document's title and text. Results can
  differ slightly across hardware and library versions.
- LLMPointwiseReranker: experimental. Asks a generative model (for example
  allenai/Olmo-3-7B-Instruct) to rate each of the top candidates from 0 to 10
  and reorders them. It is a simple prompt, not a trained reranker, and a 7B
  model is slow without a GPU.

Both import their libraries lazily, so the rest of the workbench works without
them. Searches return (doc_id, score) pairs sorted by score, highest first,
with ties broken by doc_id.
"""

from __future__ import annotations

import heapq
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

Hits = List[Tuple[str, float]]


class MissingDependency(ImportError):
    """An optional dependency for model-based real runs is not installed."""


def _require(module: str):
    try:
        return __import__(module)
    except ImportError as e:
        raise MissingDependency(
            f"This backend needs '{module}'. Install the optional extras: pip install -r requirements-real.txt"
        ) from e


def _versions(*modules: str) -> Dict[str, str]:
    found = {}
    for module in modules:
        try:
            found[f"{module}_version"] = __import__(module).__version__
        except ImportError:
            pass
    return found


def _top_k(scored, k: int) -> Hits:
    return heapq.nsmallest(k, scored, key=lambda pair: (-pair[1], pair[0]))


class DenseRetriever:
    """Embedding retrieval with a sentence-transformers model (cosine similarity)."""

    def __init__(
        self,
        model_name: str,
        revision: Optional[str] = None,
        query_prefix: str = "",
        device: Optional[str] = None,
        batch_size: int = 32,
        encoder: Any = None,
    ):
        self.model_name = model_name
        self.revision = revision
        self.query_prefix = query_prefix
        self.device = device
        self.batch_size = batch_size
        self._encoder = encoder  # anything with .encode(list_of_texts, **kwargs) -> (n, d) array
        self._doc_ids: List[str] = []
        self._matrix = None

    def _model(self):
        if self._encoder is None:
            _require("sentence_transformers")
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(self.model_name, revision=self.revision, device=self.device)
        return self._encoder

    def environment(self) -> Dict[str, Any]:
        """Values that can change results but are not part of the spec."""
        env: Dict[str, Any] = {"device": self.device, "batch_size": self.batch_size}
        model = self._encoder
        try:
            env["resolved_revision"] = model[0].auto_model.config._commit_hash
        except (AttributeError, IndexError, KeyError, TypeError):
            env["resolved_revision"] = None
        try:
            env["max_seq_length"] = model.max_seq_length
        except AttributeError:
            pass
        env.update(_versions("sentence_transformers", "transformers", "torch", "numpy"))
        return env

    def _encode(self, texts: List[str]):
        np = _require("numpy")
        vectors = self._model().encode(
            texts,
            batch_size=self.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return np.asarray(vectors, dtype=np.float32)

    def index(self, corpus: Dict[str, str]) -> None:
        """Embed every document (corpus maps doc_id to its title and text)."""
        self._doc_ids = sorted(corpus)
        self._matrix = self._encode([corpus[d] for d in self._doc_ids])

    def search(self, query: str, k: int) -> Hits:
        np = _require("numpy")
        k = min(k, len(self._doc_ids))
        if k <= 0:
            return []
        scores = self._matrix @ self._encode([self.query_prefix + query])[0]
        # Take a margin beyond k so ties at the cut-off are broken by doc_id, not by argpartition.
        margin = min(len(self._doc_ids), k + 10)
        candidates = np.argpartition(-scores, margin - 1)[:margin]
        return _top_k([(self._doc_ids[i], float(scores[i])) for i in candidates], k)


RERANK_PROMPT = (
    "Rate how relevant the document is to the query on a scale from 0 (not relevant) "
    "to 10 (perfectly relevant). Reply with the number only.\n\n"
    "Query: {query}\n\nDocument: {document}\n\nRelevance:"
)
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


def parse_rating(text: str) -> Optional[float]:
    """First number in the model's reply, if it lies in [0, 10]."""
    m = _NUMBER.search(text or "")
    if not m:
        return None
    value = float(m.group())
    return value if 0.0 <= value <= 10.0 else None


class LLMPointwiseReranker:
    """Experimental: reorder the top candidates by a generative model's 0-10 relevance ratings."""

    def __init__(
        self,
        model_id: str,
        revision: Optional[str] = None,
        top_n: int = 20,
        max_doc_chars: int = 2000,
        device: Optional[str] = None,
        generate: Optional[Callable[[str], str]] = None,
    ):
        self.model_id = model_id
        self.revision = revision
        self.top_n = top_n
        self.max_doc_chars = max_doc_chars
        self.device = device
        self._generate = generate  # prompt -> reply; tests inject one
        self._model = None
        self._tokenizer = None
        self.unparsed_total = 0
        self.rated_total = 0

    def environment(self) -> Dict[str, Any]:
        env: Dict[str, Any] = {
            "device": self.device,
            "prompt": RERANK_PROMPT,
            "decoding": "greedy, max_new_tokens=8",
            "max_doc_chars": self.max_doc_chars,
            "ratings_parsed": self.rated_total,
            "ratings_unparsed": self.unparsed_total,
        }
        try:
            env["resolved_revision"] = self._model.config._commit_hash
        except AttributeError:
            env["resolved_revision"] = None
        env.update(_versions("transformers", "torch"))
        return env

    def _load(self) -> Callable[[str], str]:
        if self._generate is not None:
            return self._generate
        torch = _require("torch")
        _require("transformers")
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_id, revision=self.revision)
        self._model = AutoModelForCausalLM.from_pretrained(self.model_id, revision=self.revision, dtype="auto")
        device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._model.to(device)
        self._model.eval()

        def generate(prompt: str) -> str:
            inputs = self._tokenizer.apply_chat_template(
                [{"role": "user", "content": prompt}],
                add_generation_prompt=True,
                return_tensors="pt",
                return_dict=True,
            ).to(device)
            with torch.no_grad():
                output = self._model.generate(**inputs, max_new_tokens=8, do_sample=False)
            return self._tokenizer.decode(output[0][inputs["input_ids"].shape[-1]:], skip_special_tokens=True)

        self._generate = generate
        return generate

    def rerank(self, query: str, hits: Hits, corpus: Dict[str, str]) -> Hits:
        """Rate the first top_n hits; rated ones go first by rating, then unparsed replies, then the rest.

        The returned scores encode the final order (n, n-1, ..., 1). Replies
        that can't be parsed keep their original order and are counted in
        environment()["ratings_unparsed"].
        """
        generate = self._load()
        head, tail = hits[: self.top_n], hits[self.top_n:]
        rated, unparsed = [], []
        for position, (doc_id, _) in enumerate(head):
            prompt = RERANK_PROMPT.format(query=query, document=corpus[doc_id][: self.max_doc_chars])
            rating = parse_rating(generate(prompt))
            (rated if rating is not None else unparsed).append((position, doc_id, rating))
        self.rated_total += len(rated)
        self.unparsed_total += len(unparsed)
        rated.sort(key=lambda item: (-item[2], item[0]))
        order = [d for _, d, _ in rated] + [d for _, d, _ in unparsed] + [d for d, _ in tail]
        return [(doc_id, float(len(order) - i)) for i, doc_id in enumerate(order)]

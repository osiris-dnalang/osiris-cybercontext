"""Tests for the model-based real backends (dense retrieval, LLM reranking) and the dataset downloader.

No network access and no model downloads: the toy BEIR dataset from
test_real_scifact is written to a temp directory, downloads are served by a
local HTTP server, and the embedding model and the reranker's language model
are injected stand-ins. tests/test_real_models.py runs the same code paths
against the real libraries with tiny random-weight models.
"""

import functools
import http.server
import json
import math
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_real_scifact import TOY_CORPUS, TOY_QRELS, TOY_QUERIES, _toy_spec, _write_toy_dataset  # noqa: E402

from workbench.beir_download import BeirDownloadError, download_beir, file_digests  # noqa: E402
from workbench.capsule import EvidenceCapsule  # noqa: E402
from workbench.real_models import (  # noqa: E402
    DenseRetriever,
    LLMPointwiseReranker,
    MissingDependency,
    parse_rating,
)
from workbench.real_scifact import (  # noqa: E402
    DENSE_BACKEND,
    RERANK_BACKEND,
    build_components,
    load_beir_dataset,
    run_real_scifact,
    tokenize,
)
from workbench.replay import ReplayEngine, ReplayStatus  # noqa: E402
from workbench.schema import ExperimentSpec, canonical_json_bytes, compute_sha256  # noqa: E402

try:
    import numpy
except ImportError:  # dense retrieval needs numpy (installed with the optional extras)
    numpy = None

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCAB = sorted({t for text in TOY_CORPUS.values() for t in tokenize(text)})


class FakeEncoder:
    """Deterministic bag-of-words embeddings standing in for a sentence-transformers model."""

    def __init__(self, vocab=VOCAB):
        self.vocab = vocab

    def encode(self, texts, **kwargs):
        rows = []
        for text in texts:
            tokens = tokenize(text)
            vec = [float(tokens.count(term)) for term in self.vocab]
            norm = math.sqrt(sum(v * v for v in vec)) or 1.0
            rows.append([v / norm for v in vec])
        return numpy.asarray(rows, dtype=numpy.float32)


class ConstantEncoder(FakeEncoder):
    """Gives every text the same embedding, so all scores tie and the ranking falls back to doc_id: a re-run that drifts."""

    def encode(self, texts, **kwargs):
        return numpy.ones((len(texts), len(self.vocab)), dtype=numpy.float32) / math.sqrt(len(self.vocab))


def dense_spec(**options):
    return _toy_spec(model_id="fake/bow", similarity_metric="cosine",
                     retrieval_options={"backend": "dense", **options})


def fake_components(encoder_cls=FakeEncoder, generate=None):
    def factory(spec):
        retriever, reranker = build_components(spec)
        retriever._encoder = encoder_cls()
        if reranker is not None:
            reranker._generate = generate
        return retriever, reranker
    return factory


def toy_generate(replies):
    """A stand-in LLM: answers with the reply configured for whichever toy document the prompt contains."""
    def generate(prompt):
        document = prompt.split("Document: ", 1)[1].split("\n\nRelevance:", 1)[0]
        for doc_id, text in TOY_CORPUS.items():
            if document == text:
                return replies.get(doc_id, "0")
        return "0"
    return generate


class SpecCompatibilityTests(unittest.TestCase):
    def test_retrieval_options_change_the_digest_only_when_set(self):
        # The default simulated spec's digest must not move (capsules already in circulation use it).
        plain = ExperimentSpec(
            experiment_id="EXP-OLMO3-BEIR-SCIFACT-001", model_id="allenai/Olmo-3-7B-Instruct",
            benchmark_suite="MTEB/BEIR", dataset="SciFact", split="test", query_count=5,
        )
        self.assertEqual(plain.canonical_digest(),
                         "0e93ed6a8b9afc911fab7be08698eca7fce01bdd7e61de5e6c5821e873ab0a68")
        self.assertNotEqual(dense_spec().canonical_digest(), _toy_spec().canonical_digest())
        self.assertNotEqual(dense_spec(query_prefix="q: ").canonical_digest(), dense_spec().canonical_digest())


class RealTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_dir = _write_toy_dataset(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def rewrite(self, path, edit):
        """Apply edit(records, manifest) and rewrite every checksum, as a careful forger would."""
        with zipfile.ZipFile(path) as zf:
            files = {n: zf.read(n) for n in zf.namelist()}
        manifest = json.loads(files["manifest.json"])
        records = json.loads(files["raw_queries.json"])
        edit(records, manifest)
        raw = canonical_json_bytes(records)
        files["raw_queries.json"] = raw
        manifest["manifest_files"]["raw_queries.json"] = {"sha256": compute_sha256(raw), "bytes": len(raw)}
        files["manifest.json"] = canonical_json_bytes(manifest)
        out = os.path.join(self.tmp.name, "edited.evidence.zip")
        with zipfile.ZipFile(out, "w") as zf:
            for n, data in files.items():
                zf.writestr(n, data)
        return out


@unittest.skipIf(numpy is None, "dense retrieval needs numpy")
class DenseBackendTests(RealTestBase):
    def run_dense(self, spec=None, encoder_cls=FakeEncoder, generate=None):
        spec = spec or dense_spec()
        return run_real_scifact(spec, self.data_dir,
                                components=fake_components(encoder_cls, generate)(spec))

    def capsule(self, spec=None, generate=None):
        spec = spec or dense_spec()
        result = self.run_dense(spec, generate=generate)
        return result, EvidenceCapsule.pack(result, os.path.join(self.tmp.name, "dense.evidence.zip"))

    def test_dense_run_ranks_by_cosine_and_records_provenance(self):
        result = self.run_dense()
        self.assertEqual(result.retrieval_backend, DENSE_BACKEND)
        q1 = result.evaluated_queries[0]
        self.assertEqual(q1.query_id, "q-1")
        self.assertEqual(q1.retrieved_doc_ids[0], "doc-4")  # "alpha alpha unique four" is closest to "alpha"
        self.assertEqual(len(q1.retrieved_doc_ids), len(TOY_CORPUS))
        self.assertEqual(q1.relevance_scores, [float(TOY_QRELS["q-1"].get(d, 0)) for d in q1.retrieved_doc_ids])
        env = result.environment_telemetry
        self.assertEqual(env["dataset_files"], file_digests(self.data_dir, "test"))
        self.assertIn("batch_size", env["retriever"])
        self.assertNotIn("bm25_k1", env)

    def test_dense_capsule_replays_exactly_with_the_same_model(self):
        _, path = self.capsule()
        manifest = EvidenceCapsule.unpack(path)["manifest"]
        self.assertEqual(manifest["retrieval_backend"], DENSE_BACKEND)
        self.assertTrue(manifest["notice"].startswith("Real retrieval: a sentence-transformers"))
        verdict = ReplayEngine.replay(path, real_data_dir=self.data_dir, component_factory=fake_components())
        self.assertEqual(verdict.status, ReplayStatus.EXACT_MATCH, verdict.details)

    def test_dense_replay_without_the_dataset_or_with_other_files_is_not_replayable(self):
        _, path = self.capsule()
        self.assertEqual(ReplayEngine.replay(path).status, ReplayStatus.NOT_REPLAYABLE)
        with open(os.path.join(self.data_dir, "corpus.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"_id": "doc-5", "title": "", "text": "alpha"}) + "\n")
        verdict = ReplayEngine.replay(path, real_data_dir=self.data_dir, component_factory=fake_components())
        self.assertEqual(verdict.status, ReplayStatus.NOT_REPLAYABLE)
        self.assertIn("dataset files differ", verdict.details)

    def test_ranking_differences_that_keep_the_metrics_are_equivalence(self):
        _, path = self.capsule()

        def swap_irrelevant(records, manifest, recompute_digest):
            rec = records[0]  # q-1: doc-4 and doc-1 are relevant, doc-2 and doc-3 are not
            ids = rec["retrieved_doc_ids"]
            i, j = ids.index("doc-2"), ids.index("doc-3")
            ids[i], ids[j] = ids[j], ids[i]
            rec["relevance_scores"] = [float(TOY_QRELS["q-1"].get(d, 0)) for d in ids]
            if recompute_digest:
                rec["query_digest"] = compute_sha256(
                    f"{rec['query_id']}:{rec['query_text']}:{','.join(ids)}:{rec['ndcg_at_10']}:{rec['mrr_at_10']}")

        careless = self.rewrite(path, lambda r, m: swap_irrelevant(r, m, False))
        verdict = ReplayEngine.replay(careless, real_data_dir=self.data_dir, component_factory=fake_components())
        self.assertEqual(verdict.status, ReplayStatus.DRIFT_DETECTED)
        self.assertIn("stored query_digest does not match", verdict.details)

        # A consistent rewrite of a ranking that keeps the metrics is indistinguishable from
        # hardware nondeterminism, so it passes as equivalence. This is the documented limit.
        careful = self.rewrite(path, lambda r, m: swap_irrelevant(r, m, True))
        verdict = ReplayEngine.replay(careful, real_data_dir=self.data_dir, component_factory=fake_components())
        self.assertEqual(verdict.status, ReplayStatus.STATISTICAL_EQUIVALENCE, verdict.details)
        self.assertTrue(verdict.is_passing())

    def test_inconsistent_records_and_metric_drift_are_caught(self):
        _, path = self.capsule()

        def inflate(records, manifest):
            records[1]["ndcg_at_10"] = 1.0

        def edit_mean(records, manifest):
            manifest["metrics"]["NDCG@10"] = 0.99

        def wrong_grades(records, manifest):
            records[0]["relevance_scores"] = [0.0] * len(records[0]["relevance_scores"])

        for edit, message in [
            (inflate, "query q-2: stored NDCG/MRR do not match its stored ranking"),
            (edit_mean, "manifest NDCG@10 is not the mean of the stored records"),
            (wrong_grades, "query q-1: stored relevance grades differ from the qrels"),
        ]:
            verdict = ReplayEngine.replay(self.rewrite(path, edit), real_data_dir=self.data_dir,
                                          component_factory=fake_components())
            self.assertEqual(verdict.status, ReplayStatus.DRIFT_DETECTED, edit.__name__)
            self.assertIn(message, verdict.details, edit.__name__)

        drifted = ReplayEngine.replay(path, real_data_dir=self.data_dir,
                                      component_factory=fake_components(ConstantEncoder))
        self.assertEqual(drifted.status, ReplayStatus.DRIFT_DETECTED, drifted.details)
        self.assertIn("metric drift", drifted.details)

    def test_reranker_reorders_and_is_recorded(self):
        generate = toy_generate({"doc-1": "9", "doc-4": "7", "doc-2": "no idea"})
        spec = dense_spec(rerank_model="fake/llm", rerank_top_n=3)
        result, path = self.capsule(spec, generate=generate)
        self.assertEqual(result.retrieval_backend, RERANK_BACKEND)
        q1 = result.evaluated_queries[0]
        # The dense top 3 for "alpha" are doc-4, doc-1 and one irrelevant doc; ratings put doc-1 first.
        self.assertEqual(q1.retrieved_doc_ids[:2], ["doc-1", "doc-4"])
        rerank_env = result.environment_telemetry["reranker"]
        self.assertGreater(rerank_env["ratings_parsed"], 0)
        self.assertIn("Relevance:", rerank_env["prompt"])
        summary = EvidenceCapsule.unpack(path)["summary_md"]
        self.assertIn("- **Reranker (experimental):** fake/llm", summary)
        verdict = ReplayEngine.replay(path, real_data_dir=self.data_dir,
                                      component_factory=fake_components(generate=generate))
        self.assertEqual(verdict.status, ReplayStatus.EXACT_MATCH, verdict.details)

    def test_reranker_ordering_rules(self):
        corpus = {"a": "x", "b": "y", "c": "z", "d": "w", "e": "v"}
        replies = {"x": "3", "y": "unparseable", "z": "8", "w": "8"}
        reranker = LLMPointwiseReranker(model_id="fake", top_n=4, generate=lambda p: replies[p.split("Document: ")[1][0]])
        hits = [("a", 0.9), ("b", 0.8), ("c", 0.7), ("d", 0.6), ("e", 0.5)]
        reranked = reranker.rerank("q", hits, corpus)
        # rated by rating (ties keep dense order), then unparsed, then the unrated tail
        self.assertEqual([d for d, _ in reranked], ["c", "d", "a", "b", "e"])
        self.assertEqual([s for _, s in reranked], [5.0, 4.0, 3.0, 2.0, 1.0])
        self.assertEqual((reranker.rated_total, reranker.unparsed_total), (3, 1))

    def test_rating_parser(self):
        self.assertEqual(parse_rating(" 8\n"), 8.0)
        self.assertEqual(parse_rating("Relevance: 3.5/10"), 3.5)
        self.assertIsNone(parse_rating("eleven"))
        self.assertIsNone(parse_rating("12"))


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


class DownloadTests(RealTestBase):
    def setUp(self):
        super().setUp()
        # Serve the toy dataset at the Hub's URL layout: /datasets/<repo>/resolve/<revision>/<path>
        served = os.path.join(self.tmp.name, "hub")
        hub_copy = os.path.join(served, "datasets", "mteb", "toy", "resolve", "main")
        os.makedirs(os.path.dirname(hub_copy))
        os.rename(_write_toy_dataset(os.path.join(self.tmp.name, "src")), hub_copy)
        handler = functools.partial(_QuietHandler, directory=served)
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/datasets/{{repo}}/resolve/{{revision}}/{{path}}"
        self.source_digests = file_digests(hub_copy, "test")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        super().tearDown()

    def test_download_then_load(self):
        dest = os.path.join(self.tmp.name, "downloaded")
        fetched = download_beir("toy", dest, url_template=self.url)
        self.assertEqual(fetched, ["corpus.jsonl", "queries.jsonl", "qrels/test.tsv"])
        self.assertEqual(file_digests(dest, "test"), self.source_digests)
        self.assertEqual(len(load_beir_dataset(dest).queries), len(TOY_QUERIES))
        with open(os.path.join(dest, "SOURCE.json"), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["repo"], "mteb/toy")
        self.assertEqual(download_beir("toy", dest, url_template=self.url), [])  # already present

    def test_download_failure_names_the_url_and_leaves_no_partial_file(self):
        dest = os.path.join(self.tmp.name, "downloaded")
        with self.assertRaises(BeirDownloadError) as caught:
            download_beir("missing", dest, url_template=self.url)
        self.assertIn("/datasets/mteb/missing/resolve/main/corpus.jsonl", str(caught.exception))
        self.assertEqual([n for n in os.listdir(dest) if n.startswith(".download-")], [])

    def test_cli_download_then_run_real_bm25(self):
        dest = os.path.join(self.tmp.name, "cli")
        env = dict(os.environ, PYTHONPATH=REPO_ROOT, PYTHONIOENCODING="utf-8", OSIRIS_HF_DATASET_URL=self.url)
        dl = subprocess.run([sys.executable, "-m", "workbench.cli", "download-beir", "toy", "--dest", dest],
                            cwd=self.tmp.name, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(dl.returncode, 0, dl.stdout + dl.stderr)
        self.assertIn("3 judged test queries (4 in queries.jsonl)", dl.stdout)
        self.assertIn(self.source_digests["corpus.jsonl"]["sha256"], dl.stdout)
        run = subprocess.run([sys.executable, "-m", "workbench.cli", "run-real", "--data", dest,
                              "--out", os.path.join(self.tmp.name, "r.evidence.zip")],
                             cwd=self.tmp.name, env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)


class CliOptionTests(RealTestBase):
    def _cli(self, *args):
        env = dict(os.environ, PYTHONPATH=REPO_ROOT, PYTHONIOENCODING="utf-8")
        return subprocess.run([sys.executable, "-m", "workbench.cli", *args], cwd=self.tmp.name, env=env,
                              capture_output=True, text=True, timeout=120)

    def test_rerank_model_requires_the_dense_backend(self):
        proc = self._cli("run-real", "--data", self.data_dir, "--rerank-model", "x/y")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("--rerank-model needs --backend dense", proc.stderr)

    def test_dense_backend_without_the_extras_explains_how_to_install_them(self):
        try:
            import sentence_transformers  # noqa: F401
            self.skipTest("sentence-transformers is installed")
        except ImportError:
            pass
        proc = self._cli("run-real", "--data", self.data_dir, "--backend", "dense")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertIn("requirements-real.txt", proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)

    def test_missing_dependency_is_raised_by_the_retriever(self):
        try:
            import sentence_transformers  # noqa: F401
            self.skipTest("sentence-transformers is installed")
        except ImportError:
            pass
        with self.assertRaises(MissingDependency):
            DenseRetriever("x/y")._model()


if __name__ == "__main__":
    unittest.main()

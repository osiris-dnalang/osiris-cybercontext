"""Code-path tests for the dense retriever and LLM reranker with tiny random-weight models.

These need the optional extras (requirements-real.txt) and are skipped
otherwise. The models are built locally with random weights, so nothing is
downloaded and the scores mean nothing: the tests check that DenseRetriever
and LLMPointwiseReranker drive sentence-transformers and transformers
(including an Olmo3ForCausalLM) correctly, end to end through run-real, a
capsule and its replay.
"""

import os
import sys
import tempfile
import unittest

os.environ.setdefault("HF_HUB_OFFLINE", "1")

try:
    import torch
    import transformers
    from sentence_transformers import SentenceTransformer, models
except ImportError:
    torch = None

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_real_scifact import TOY_CORPUS, TOY_QUERIES, _toy_spec, _write_toy_dataset  # noqa: E402

from workbench.capsule import EvidenceCapsule  # noqa: E402
from workbench.real_scifact import DENSE_BACKEND, RERANK_BACKEND, run_real_scifact, tokenize  # noqa: E402
from workbench.replay import ReplayEngine  # noqa: E402

CHAT_TEMPLATE = (
    "{% for message in messages %}<|{{ message['role'] }}|> {{ message['content'] }} {% endfor %}"
    "{% if add_generation_prompt %}<|assistant|>{% endif %}"
)


def _write_vocab(path):
    words = sorted({t for text in TOY_CORPUS.values() for t in tokenize(text)} |
                   {t for text in TOY_QUERIES.values() for t in tokenize(text)} |
                   set("0123456789") | {"relevance", "query", "document", "rate"})
    special = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", "<|user|>", "<|assistant|>"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(special + words) + "\n")
    return len(special) + len(words)


def build_tiny_sentence_transformer(root):
    bert_dir = os.path.join(root, "tiny-bert")
    os.makedirs(bert_dir)
    vocab_size = _write_vocab(os.path.join(bert_dir, "vocab.txt"))
    tokenizer = transformers.BertTokenizerFast(os.path.join(bert_dir, "vocab.txt"))
    torch.manual_seed(0)
    config = transformers.BertConfig(vocab_size=vocab_size, hidden_size=32, num_hidden_layers=2,
                                     num_attention_heads=4, intermediate_size=64, max_position_embeddings=128)
    transformers.BertModel(config).save_pretrained(bert_dir)
    tokenizer.save_pretrained(bert_dir)
    word = models.Transformer(bert_dir, max_seq_length=64)
    pooling = models.Pooling(word.get_word_embedding_dimension(), pooling_mode="cls")
    st_dir = os.path.join(root, "tiny-st")
    SentenceTransformer(modules=[word, pooling], device="cpu").save(st_dir)
    return st_dir


def build_tiny_olmo3(root):
    olmo_dir = os.path.join(root, "tiny-olmo3")
    os.makedirs(olmo_dir)
    vocab_size = _write_vocab(os.path.join(olmo_dir, "vocab.txt"))
    tokenizer = transformers.BertTokenizerFast(os.path.join(olmo_dir, "vocab.txt"))
    tokenizer.chat_template = CHAT_TEMPLATE
    torch.manual_seed(0)
    config = transformers.Olmo3Config(vocab_size=vocab_size, hidden_size=32, intermediate_size=64,
                                      num_hidden_layers=2, num_attention_heads=4, num_key_value_heads=4,
                                      max_position_embeddings=1024, pad_token_id=0, eos_token_id=3,
                                      bos_token_id=2)
    transformers.Olmo3ForCausalLM(config).save_pretrained(olmo_dir)
    tokenizer.save_pretrained(olmo_dir)
    return olmo_dir


@unittest.skipIf(torch is None, "needs the optional extras in requirements-real.txt")
class RealModelCodePathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.st_dir = build_tiny_sentence_transformer(cls.tmp.name)
        cls.olmo_dir = build_tiny_olmo3(cls.tmp.name)
        cls.data_dir = _write_toy_dataset(cls.tmp.name)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def spec(self, **options):
        return _toy_spec(model_id=self.st_dir, similarity_metric="cosine",
                         retrieval_options={"backend": "dense", **options})

    def test_dense_backend_with_a_real_sentence_transformer(self):
        result = run_real_scifact(self.spec(), self.data_dir)
        self.assertEqual(result.retrieval_backend, DENSE_BACKEND)
        self.assertEqual(len(result.evaluated_queries), len(TOY_QUERIES))
        env = result.environment_telemetry["retriever"]
        self.assertEqual(env["sentence_transformers_version"], __import__("sentence_transformers").__version__)
        self.assertEqual(env["max_seq_length"], 64)

        path = EvidenceCapsule.pack(result, os.path.join(self.tmp.name, "dense.evidence.zip"))
        verdict = ReplayEngine.replay(path, real_data_dir=self.data_dir)
        self.assertTrue(verdict.is_passing(), verdict.details)

    def test_reranker_with_a_real_olmo3_model(self):
        spec = self.spec(rerank_model=self.olmo_dir, rerank_top_n=3)
        result = run_real_scifact(spec, self.data_dir)
        self.assertEqual(result.retrieval_backend, RERANK_BACKEND)
        env = result.environment_telemetry["reranker"]
        self.assertEqual(env["ratings_parsed"] + env["ratings_unparsed"], 3 * len(TOY_QUERIES))
        self.assertIn("transformers_version", env)

        path = EvidenceCapsule.pack(result, os.path.join(self.tmp.name, "rerank.evidence.zip"))
        verdict = ReplayEngine.replay(path, real_data_dir=self.data_dir)
        self.assertTrue(verdict.is_passing(), verdict.details)


if __name__ == "__main__":
    unittest.main()

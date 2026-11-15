"""Behavior of the "Threads per File" (``threads``) setting.

Parallel translation must stay a pure speed-up: the same requests, in the same
order, with the same preceding-source history as the sequential path.
"""

import json
import os
import tempfile
import threading
import unittest
from contextlib import contextmanager
from unittest import mock

from util import translation as T


class ThreadCountTests(unittest.TestCase):
    def test_env_value_is_parsed_and_clamped(self):
        original = os.environ.get("threads")
        cases = (
            (None, 1),
            ("", 1),
            ("3", 3),
            ("0", 1),
            ("-2", 1),
            ("21", 20),
            ("abc", 1),
            (" 7 ", 7),
        )
        try:
            for raw, expected in cases:
                if raw is None:
                    os.environ.pop("threads", None)
                else:
                    os.environ["threads"] = raw
                self.assertEqual(T._translation_thread_count(), expected, raw)
        finally:
            if original is None:
                os.environ.pop("threads", None)
            else:
                os.environ["threads"] = original


class ParallelTranslationTests(unittest.TestCase):
    SOURCE_REGEX = r"[\u3040-\u30ff\u4e00-\u9fff]"

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)

    def _config(self, batch_size=2):
        return T.TranslationConfig(
            model="gpt-5.6-terra",
            language="English",
            prompt="Translate Japanese to English.",
            vocab="",
            batchSize=batch_size,
            maxHistory=10,
            langRegex=self.SOURCE_REGEX,
            logFilePath=os.path.join(self.temporary.name, "translation.log"),
            mismatchLogPath=os.path.join(self.temporary.name, "mismatch.log"),
        )

    @staticmethod
    def _lines(count):
        return [f"\u30c6\u30b9\u30c8{i}\u884c\u76ee" for i in range(count)]

    @staticmethod
    def _payload(user):
        body = user.split("```json\n", 1)[1].rsplit("\n```", 1)[0]
        return json.loads(body)

    @contextmanager
    def _live_patches(self, translate):
        with (
            mock.patch.dict(os.environ, {"source_language": "Japanese"}),
            mock.patch.object(T, "get_batch_phase", return_value=None),
            mock.patch.object(T, "getBatchProvider", return_value=None),
            mock.patch.object(T, "get_cached_translation", return_value=None),
            mock.patch.object(T, "translateText", side_effect=translate),
            mock.patch.object(T, "cache_translation"),
            mock.patch.object(T, "save_cache"),
        ):
            yield

    def test_parallel_chunks_keep_order_and_sum_tokens(self):
        lines = self._lines(6)
        config = self._config(batch_size=2)
        barrier = threading.Barrier(3, timeout=10)
        seen = set()
        seen_lock = threading.Lock()
        barrier_results = []

        def translate(_system, user, _history, *_args, **_kwargs):
            thread_id = threading.get_ident()
            with seen_lock:
                first_call = thread_id not in seen
                seen.add(thread_id)
            if first_call:
                try:
                    barrier.wait()
                    barrier_results.append(True)
                except threading.BrokenBarrierError:
                    barrier_results.append(False)
            payload = self._payload(user)
            output = {key: f"Translated {key}" for key in payload}
            return T._AnthropicCompat(json.dumps(output), 10, 20, 0, 0)

        with self._live_patches(translate):
            with mock.patch.dict(os.environ, {"threads": "3"}):
                result, tokens = T.translateAI(lines, [], config)

        self.assertEqual(
            result, ["Translated Line1", "Translated Line2"] * 3
        )
        self.assertEqual(tokens, [30, 60])
        self.assertEqual(len(seen), 3)
        self.assertEqual(barrier_results, [True, True, True])

    def test_parallel_chunks_use_the_same_history_as_sequential(self):
        lines = self._lines(8)
        config = self._config(batch_size=2)
        barrier = threading.Barrier(2, timeout=10)
        seen = set()
        seen_lock = threading.Lock()
        captured = []

        def translate(_system, user, history, *_args, **kwargs):
            thread_id = threading.get_ident()
            with seen_lock:
                first_call = thread_id not in seen
                seen.add(thread_id)
            if first_call:
                barrier.wait()
            payload = self._payload(user)
            first_source = next(iter(payload.values()))
            batch_index = lines.index(first_source) // 2
            with seen_lock:
                captured.append((
                    batch_index,
                    list(history) if isinstance(history, list) else history,
                    kwargs.get("request_instructions"),
                ))
            output = {key: f"Translated {key}" for key in payload}
            return T._AnthropicCompat(json.dumps(output), 1, 1, 0, 0)

        with self._live_patches(translate):
            with mock.patch.dict(os.environ, {"threads": "2"}):
                T.translateAI(
                    lines,
                    "Keep the tone neutral.",
                    config,
                )

        expected = [
            (0, [], ["Keep the tone neutral."]),
            (1, lines[0:2], ["Keep the tone neutral."]),
            (2, lines[2:4], ["Keep the tone neutral."]),
            (3, lines[4:6], ["Keep the tone neutral."]),
        ]
        self.assertEqual(sorted(captured, key=lambda item: item[0]), expected)

    def test_parallel_cost_counters_are_merged_once(self):
        lines = self._lines(6)
        config = self._config(batch_size=2)
        config.model = "claude-sonnet-4-6"

        def translate(_system, user, _history, *_args, **_kwargs):
            payload = self._payload(user)
            output = {key: f"Translated {key}" for key in payload}
            return T._AnthropicCompat(json.dumps(output), 100, 20, 10, 5)

        T.begin_file_cost_tracking(config.model)
        before = T._global_accurate_cost
        with self._live_patches(translate):
            with mock.patch.dict(os.environ, {"threads": "3"}):
                _result, tokens = T.translateAI(lines, [], config)
        file_cost = T.calculateCost(tokens[0], tokens[1], config.model)
        after = T._global_accurate_cost

        self.assertGreater(file_cost, 0)
        # Workers already added their cost globally; the parent must not add it
        # a second time when it merges their counters.
        self.assertAlmostEqual(file_cost, after - before, places=10)

    def test_threads_one_stays_sequential(self):
        lines = self._lines(6)
        config = self._config(batch_size=2)
        main_thread = threading.get_ident()
        call_threads = []

        def translate(_system, user, _history, *_args, **_kwargs):
            call_threads.append(threading.get_ident())
            payload = self._payload(user)
            output = {key: f"Translated {key}" for key in payload}
            return T._AnthropicCompat(json.dumps(output), 5, 5, 0, 0)

        with self._live_patches(translate):
            with mock.patch.dict(os.environ, {"threads": "1"}):
                result, tokens = T.translateAI(lines, [], config)

        self.assertEqual(result, ["Translated Line1", "Translated Line2"] * 3)
        self.assertEqual(tokens, [15, 15])
        self.assertEqual(call_threads, [main_thread] * 3)

    def test_batch_collect_phase_never_runs_in_parallel(self):
        lines = self._lines(6)
        config = self._config(batch_size=2)
        main_thread = threading.get_ident()
        call_threads = []

        def capture(_system, _user, _history, *_args, **_kwargs):
            call_threads.append(threading.get_ident())
            return {"model": config.model, "messages": []}

        with (
            mock.patch.object(T, "get_batch_phase", return_value="collect"),
            mock.patch.object(T, "getBatchProvider", return_value="anthropic"),
            mock.patch.object(T, "peek_cached_translation", return_value=None),
            mock.patch.object(T, "buildClaudeRequest", side_effect=capture),
            mock.patch.object(T, "queue_batch_request"),
            mock.patch.object(T, "flush_batch_queue"),
            mock.patch.object(T, "save_cache"),
            mock.patch.dict(os.environ, {"threads": "3"}),
        ):
            T.reset_batch_collect_file_stats()
            T.translateAI(lines, [], config)

        self.assertEqual(call_threads, [main_thread] * 3)


if __name__ == "__main__":
    unittest.main()

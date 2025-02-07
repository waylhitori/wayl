from typing import List, Dict, Tuple, Optional
from transformers import AutoTokenizer
import torch
import logging
from prometheus_client import Counter, Histogram
import json
from pathlib import Path
import asyncio

logger = logging.getLogger(__name__)

# Metrics
tokenization_time = Histogram('tokenization_time_seconds', 'Time taken for tokenization')
token_counts = Counter('token_counts_total', 'Total number of tokens processed')


class TokenizerManager:
    def __init__(
            self,
            model_path: str,
            max_length: int = 2048,
            cache_dir: Optional[str] = None
    ):
        self.model_path = model_path
        self.max_length = max_length
        self.cache_dir = cache_dir
        self._tokenizer = None
        self._lock = asyncio.Lock()
        self._special_tokens_cache = {}

    async def initialize(self):
        if self._tokenizer is not None:
            return

        async with self._lock:
            if self._tokenizer is not None:
                return

            try:
                self._tokenizer = AutoTokenizer.from_pretrained(
                    self.model_path,
                    trust_remote_code=True,
                    use_fast=True,
                    cache_dir=self.cache_dir
                )
                await self._load_special_tokens()
            except Exception as e:
                logger.error(f"Failed to initialize tokenizer: {str(e)}")
                raise

    async def encode(
            self,
            text: str,
            add_special_tokens: bool = True,
            return_tensors: bool = True
    ) -> Dict:
        await self.initialize()

        with tokenization_time.time():
            inputs = self._tokenizer(
                text,
                add_special_tokens=add_special_tokens,
                max_length=self.max_length,
                padding=True,
                truncation=True,
                return_tensors="pt" if return_tensors else None
            )

            token_counts.inc(len(inputs["input_ids"][0]) if return_tensors else len(inputs["input_ids"]))
            return inputs

    async def decode(
            self,
            token_ids: torch.Tensor,
            skip_special_tokens: bool = True
    ) -> str:
        await self.initialize()
        return self._tokenizer.decode(token_ids[0], skip_special_tokens=skip_special_tokens)

    async def count_tokens(self, text: str) -> int:
        await self.initialize()
        tokens = await self.encode(text, return_tensors=False)
        return len(tokens["input_ids"])

    async def batch_encode(
            self,
            texts: List[str],
            max_length: Optional[int] = None
    ) -> Dict:
        await self.initialize()

        with tokenization_time.time():
            batch_inputs = self._tokenizer(
                texts,
                max_length=max_length or self.max_length,
                padding=True,
                truncation=True,
                return_tensors="pt"
            )

            total_tokens = sum(len(ids) for ids in batch_inputs["input_ids"])
            token_counts.inc(total_tokens)
            return batch_inputs

    async def get_vocabulary(self) -> Dict[str, int]:
        await self.initialize()
        return self._tokenizer.get_vocab()

    async def get_special_tokens(self) -> Dict[str, str]:
        await self.initialize()
        return {
            "pad": self._tokenizer.pad_token,
            "eos": self._tokenizer.eos_token,
            "bos": self._tokenizer.bos_token,
            "unk": self._tokenizer.unk_token,
            "mask": self._tokenizer.mask_token
        }

    async def save_vocabulary(self, save_path: str):
        await self.initialize()
        vocab_path = Path(save_path)
        vocab_path.parent.mkdir(parents=True, exist_ok=True)

        vocab = await self.get_vocabulary()
        with open(vocab_path, 'w', encoding='utf-8') as f:
            json.dump(vocab, f, ensure_ascii=False, indent=2)

    async def estimate_tokens(self, text: str) -> Tuple[int, float]:
        # Rough estimation before actual tokenization
        words = len(text.split())
        chars = len(text)

        # Average token/word ratio for DeepSeek models
        estimated_tokens = int(words * 1.3)
        confidence = 0.85 if chars / words < 8 else 0.7

        return estimated_tokens, confidence

    async def _load_special_tokens(self):
        try:
            if self.cache_dir:
                cache_path = Path(self.cache_dir) / "special_tokens.json"
                if cache_path.exists():
                    with open(cache_path, 'r', encoding='utf-8') as f:
                        self._special_tokens_cache = json.load(f)
                        return

            self._special_tokens_cache = await self.get_special_tokens()

            if self.cache_dir:
                cache_path = Path(self.cache_dir) / "special_tokens.json"
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                with open(cache_path, 'w', encoding='utf-8') as f:
                    json.dump(self._special_tokens_cache, f, ensure_ascii=False, indent=2)

        except Exception as e:
            logger.warning(f"Failed to load special tokens cache: {str(e)}")
            self._special_tokens_cache = {}
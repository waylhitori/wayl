
from typing import List, Dict
from transformers import AutoTokenizer
import torch


class TokenizerManager:
    def __init__(self, model_path: str):
        self.tokenizer = AutoTokenizer.from_pretrained(
            model_path,
            trust_remote_code=True
        )

    def encode(
            self,
            text: str,
            max_length: int = None,
            padding: bool = True,
            truncation: bool = True
    ) -> Dict:
        return self.tokenizer(
            text,
            max_length=max_length,
            padding=padding,
            truncation=truncation,
            return_tensors="pt"
        )

    def decode(self, token_ids: torch.Tensor) -> str:
        return self.tokenizer.decode(token_ids[0], skip_special_tokens=True)

    def get_vocab_size(self) -> int:
        return len(self.tokenizer)

    def get_special_tokens(self) -> Dict[str, str]:
        return {
            "pad": self.tokenizer.pad_token,
            "eos": self.tokenizer.eos_token,
            "bos": self.tokenizer.bos_token,
            "unk": self.tokenizer.unk_token
        }
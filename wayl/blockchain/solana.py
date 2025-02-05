
from typing import Dict, Optional, List
from solana.rpc.api import Client
from solana.rpc.commitment import Commitment
from solana.transaction import Transaction
from solana.system_program import TransferParams, transfer
from solana.keypair import Keypair
from base58 import b58encode, b58decode


class SolanaClient:
    def __init__(
            self,
            rpc_url: str,
            commitment: Commitment = Commitment.CONFIRMED
    ):
        self.client = Client(rpc_url, commitment=commitment)

    def get_balance(self, public_key: str) -> float:
        try:
            response = self.client.get_balance(public_key)
            return response['result']['value'] / 1e9  # Convert lamports to SOL
        except Exception as e:
            raise Exception(f"Failed to get balance: {str(e)}")

    def send_transaction(
            self,
            from_keypair: Keypair,
            to_pubkey: str,
            amount: float,
            memo: Optional[str] = None
    ) -> str:
        try:
            amount_lamports = int(amount * 1e9)

            transaction = Transaction()
            transfer_params = TransferParams(
                from_pubkey=from_keypair.public_key,
                to_pubkey=to_pubkey,
                lamports=amount_lamports
            )

            transaction.add(transfer(transfer_params))

            if memo:
                from spl.memo.instructions import create_memo
                transaction.add(create_memo(from_keypair.public_key, memo))

            signature = self.client.send_transaction(
                transaction,
                from_keypair,
                recent_blockhash=self.client.get_recent_blockhash()['result']['value']['blockhash']
            )

            return signature['result']

        except Exception as e:
            raise Exception(f"Failed to send transaction: {str(e)}")

    def get_transaction_history(
            self,
            address: str,
            limit: int = 50
    ) -> List[Dict]:
        try:
            signatures = self.client.get_signatures_for_address(
                address,
                limit=limit
            )['result']

            transactions = []
            for sig in signatures:
                tx = self.client.get_transaction(
                    sig['signature'],
                    encoding="jsonParsed"
                )['result']
                transactions.append(tx)

            return transactions

        except Exception as e:
            raise Exception(f"Failed to get transaction history: {str(e)}")
# SPDX-License-Identifier: Apache-2.0
"""DID:key identity plugin — Ed25519 key-based identity.

Uses hashlib for deterministic key derivation in simulation (no real crypto
needed for testing). For real deployments, swap to a proper Ed25519 library.

Example::

    identity = DidKeyIdentity(AgentId("a1"), seed=b"secret")
    sig = identity.sign(b"payload")
    ok = identity.verify(b"payload", sig, AgentId("a1"))
"""

from __future__ import annotations

import hashlib
import hmac

from nest_core.types import AgentId, AgentIdentity, Signature


class DidKeyIdentity:
    """Ed25519-style identity using HMAC-SHA256 for simulation.

    Example::

        ident = DidKeyIdentity(AgentId("a1"), seed=b"seed")
        sig = ident.sign(b"hello")
    """

    def __init__(self, agent_id: AgentId, seed: bytes = b"") -> None:
        self._agent_id = agent_id
        self._seed = seed
        key_material = hashlib.sha256(seed + agent_id.encode()).digest()
        self._private_key = key_material
        self._public_key = hashlib.sha256(key_material).digest()
        self._known_keys: dict[AgentId, bytes] = {agent_id: self._public_key}
        self._private_keys: dict[AgentId, bytes] = {agent_id: self._private_key}

    def register_peer(
        self,
        agent_id: AgentId,
        public_key: bytes,
        private_key: bytes | None = None,
    ) -> None:
        """Register a peer's public key (and optionally private key) for verification.

        Example::

            ident.register_peer(AgentId("a2"), peer_pk)
        """
        self._known_keys[agent_id] = public_key
        if private_key is not None:
            self._private_keys[agent_id] = private_key

    @property
    def public_key(self) -> bytes:
        """This agent's public key.

        Example::

            pk = ident.public_key
        """
        return self._public_key

    def sign(self, payload: bytes) -> Signature:
        """Sign a payload with this agent's private key.

        Example::

            sig = ident.sign(b"data")
        """
        sig_bytes = hmac.new(self._private_key, payload, hashlib.sha256).digest()
        return Signature(signer=self._agent_id, value=sig_bytes, algorithm="hmac-sha256")

    def verify(self, payload: bytes, sig: Signature, agent: AgentId) -> bool:
        """Verify a signature from a given agent.

        Example::

            ok = ident.verify(b"data", sig, AgentId("a1"))
        """
        private_key = self._private_keys.get(agent)
        if private_key is None:
            return False
        expected = hmac.new(private_key, payload, hashlib.sha256).digest()
        return hmac.compare_digest(sig.value, expected)

    async def resolve(self, agent: AgentId) -> AgentIdentity:
        """Resolve an agent ID to its identity record.

        Example::

            info = await ident.resolve(AgentId("a1"))
        """
        pk = self._known_keys.get(agent, b"")
        return AgentIdentity(
            agent_id=agent,
            public_key=pk,
            method="did:key",
        )

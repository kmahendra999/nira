"""A2A client — discover and call external A2A agents."""

from __future__ import annotations

from typing import Any, Optional

from nira.a2a.protocol import A2ARequest, A2ATask, AgentCard


class A2AClient:
    """Client for calling external A2A-compatible agents.

    Discovers agent capabilities via /.well-known/agent.json and
    sends tasks via /a2a/tasks.
    """

    def __init__(
        self,
        base_url: str,
        *,
        timeout: float = 30.0,
        auth_token: Optional[str] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._auth_token = auth_token
        self._card: Optional[AgentCard] = None

    def _headers(self) -> dict[str, str]:
        """Bearer header for the remote agent, when a token is configured.

        A2AServer supports bearer auth and advertises ``{"schemes": ["bearer"]}``
        on its card, but this client sent no Authorization header at all, so any
        authenticated peer rejected every request. An A2A deployment was
        therefore either open or unreachable.
        """
        if not self._auth_token:
            return {}
        return {"Authorization": f"Bearer {self._auth_token}"}

    def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """POST a JSON-RPC request to /a2a/tasks and return its ``result``."""
        import httpx

        resp = httpx.post(
            f"{self._base_url}/a2a/tasks",
            json=A2ARequest(method=method, params=params).to_dict(),
            timeout=self._timeout,
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json().get("result", {})

    def discover(self) -> AgentCard:
        """Fetch the agent card from /.well-known/agent.json."""
        import httpx

        resp = httpx.get(
            f"{self._base_url}/.well-known/agent.json",
            timeout=self._timeout,
            headers=self._headers(),
        )
        resp.raise_for_status()
        data = resp.json()
        self._card = AgentCard(
            name=data.get("name", ""),
            description=data.get("description", ""),
            url=data.get("url", self._base_url),
            version=data.get("version", ""),
            capabilities=data.get("capabilities", []),
            skills=data.get("skills", []),
        )
        return self._card

    def send_task(self, input_text: str, **kwargs: Any) -> A2ATask:
        """Send a task to the remote agent and return the result."""
        result = self._rpc(
            "tasks/send",
            {"message": {"role": "user", "parts": [{"text": input_text}]}},
        )
        return A2ATask(
            task_id=result.get("id", ""),
            state=result.get("state", "unknown"),
            input_text=result.get("input", input_text),
            output_text=result.get("output", ""),
            history=result.get("history", []),
        )

    def get_task(self, task_id: str) -> A2ATask:
        """Get the status of a previously submitted task."""
        result = self._rpc("tasks/get", {"id": task_id})
        return A2ATask(
            task_id=result.get("id", task_id),
            state=result.get("state", "unknown"),
            output_text=result.get("output", ""),
        )

    def cancel_task(self, task_id: str) -> A2ATask:
        """Cancel a running task."""
        result = self._rpc("tasks/cancel", {"id": task_id})
        return A2ATask(
            task_id=result.get("id", task_id),
            state=result.get("state", "canceled"),
        )


__all__ = ["A2AClient"]

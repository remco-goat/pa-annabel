"""To-do-adapter — lezen én schrijven.

Dit is het enige bestand dat weet welke to-do-app je gebruikt. Zet
TODO_PROVIDER in .env en de rest van de agent merkt er niets van.

Ondersteund:
  todoist   — volledig (unified API v1; /rest/v2 is uitgezet en geeft 410)
  microsoft — Microsoft To Do via Graph; endpoints staan erin, auth nog te doen
  none      — geen to-do-bron (agent draait gewoon door)
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Protocol

import httpx

from .. import config


class TodoAdapter(Protocol):
    def fetch(self) -> list[dict[str, Any]]: ...
    def create(self, title: str, *, due: str | None = None, note: str | None = None,
               subtasks: list[str] | None = None) -> str: ...


# --------------------------------------------------------------------------
# Todoist
# --------------------------------------------------------------------------
class TodoistAdapter:
    """Todoist unified API v1.

    De oude /rest/v2 is uitgezet (410 Gone). v1 pagineert met een cursor en
    gebruikt andere veldnamen: `checked` i.p.v. `is_completed`, `added_at`
    i.p.v. `created_at`, en er is geen `url` meer — die stellen we zelf samen.
    Ook nieuw: `deadline` staat los van `due` (wanneer je eraan werkt vs
    wanneer het af moet).
    """

    BASE = "https://api.todoist.com/api/v1"
    PAGE_SIZE = 200

    def __init__(self, token: str):
        if not token:
            raise RuntimeError("TODOIST_TOKEN ontbreekt in .env")
        self._client = httpx.Client(
            base_url=self.BASE,
            headers={"Authorization": f"Bearer {token}"},
            timeout=20.0,
        )

    def _all_tasks(self) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        cursor: str | None = None
        while True:
            params: dict[str, Any] = {"limit": self.PAGE_SIZE}
            if cursor:
                params["cursor"] = cursor
            resp = self._client.get("/tasks", params=params)
            resp.raise_for_status()
            page = resp.json()
            tasks.extend(page.get("results", []))
            cursor = page.get("next_cursor")
            if not cursor:
                return tasks

    def fetch(self) -> list[dict[str, Any]]:
        today = datetime.now(timezone.utc).date().isoformat()
        signals = []
        for task in self._all_tasks():
            if task.get("checked") or task.get("is_deleted"):
                continue
            due = (task.get("due") or {}).get("date")
            deadline = (task.get("deadline") or {}).get("date")
            hard_date = deadline or due
            signals.append(
                {
                    "source": "todo",
                    "external_id": str(task["id"]),
                    "kind": "task",
                    "title": task.get("content") or "(geen titel)",
                    "summary": (task.get("description") or "")[:500],
                    "occurred_at": due or task.get("added_at"),
                    "payload": {
                        "due": due,
                        "deadline": deadline,
                        "recurring": bool((task.get("due") or {}).get("is_recurring")),
                        "priority": task.get("priority"),
                        "project_id": task.get("project_id"),
                        "labels": task.get("labels", []),
                        "url": f"https://app.todoist.com/app/task/{task['id']}",
                        # Vergelijking op de datum-prefix: `due.date` kan ook een
                        # volledig tijdstip zijn bij taken met een kloktijd.
                        "overdue": bool(hard_date and hard_date[:10] < today),
                    },
                }
            )
        return signals

    def create(self, title: str, *, due: str | None = None, note: str | None = None,
               subtasks: list[str] | None = None) -> str:
        body: dict[str, Any] = {"content": title}
        if due:
            body["due_date"] = due          # YYYY-MM-DD
        if note:
            body["description"] = note
        resp = self._client.post("/tasks", json=body)
        resp.raise_for_status()
        task = resp.json()

        # Subtaken: los afvinkbaar onder de hoofdtaak.
        for sub in subtasks or []:
            self._client.post("/tasks", json={"content": sub, "parent_id": task["id"]}).raise_for_status()

        url = f"https://app.todoist.com/app/task/{task['id']}"
        return f"{url} (+{len(subtasks)} subtaken)" if subtasks else url

    def complete(self, task_id: str) -> str:
        """Vinkt een taak af (close). Herhalende taken schuiven door naar de
        volgende datum — dat is Todoist-gedrag en meestal precies de bedoeling."""
        self._client.post(f"/tasks/{task_id}/close").raise_for_status()
        return "afgevinkt in Todoist"

    def delete(self, task_id: str) -> None:
        """Alleen gebruikt om een testtaak weer op te ruimen."""
        self._client.delete(f"/tasks/{task_id}").raise_for_status()


# --------------------------------------------------------------------------
# Microsoft To Do (Graph) — auth nog in te vullen
# --------------------------------------------------------------------------
class MicrosoftTodoAdapter:
    BASE = "https://graph.microsoft.com/v1.0/me/todo"

    def __init__(self, access_token: str = ""):
        self._token = access_token

    def _client(self) -> httpx.Client:
        if not self._token:
            raise RuntimeError(
                "Microsoft To Do vereist een Graph-token (scope Tasks.ReadWrite). "
                "Zie README > 'Microsoft To Do aanzetten'."
            )
        return httpx.Client(
            base_url=self.BASE,
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=20.0,
        )

    def fetch(self) -> list[dict[str, Any]]:
        with self._client() as client:
            lists = client.get("/lists").json().get("value", [])
            signals = []
            for lst in lists:
                items = client.get(f"/lists/{lst['id']}/tasks").json().get("value", [])
                for task in items:
                    if task.get("status") == "completed":
                        continue
                    due = (task.get("dueDateTime") or {}).get("dateTime")
                    signals.append(
                        {
                            "source": "todo",
                            "external_id": task["id"],
                            "kind": "task",
                            "title": task.get("title") or "(geen titel)",
                            "summary": ((task.get("body") or {}).get("content") or "")[:500],
                            "occurred_at": due or task.get("createdDateTime"),
                            "payload": {"due": due, "list": lst.get("displayName"), "importance": task.get("importance")},
                        }
                    )
            return signals

    def create(self, title: str, *, due: str | None = None, note: str | None = None,
               subtasks: list[str] | None = None) -> str:
        with self._client() as client:
            lists = client.get("/lists").json().get("value", [])
            default = next((l for l in lists if l.get("wellknownListName") == "defaultList"), lists[0])
            body: dict[str, Any] = {"title": title}
            if note:
                body["body"] = {"content": note, "contentType": "text"}
            if due:
                body["dueDateTime"] = {"dateTime": f"{due}T09:00:00", "timeZone": "Europe/Amsterdam"}
            resp = client.post(f"/lists/{default['id']}/tasks", json=body)
            resp.raise_for_status()
            return resp.json().get("id", "aangemaakt")


class NullAdapter:
    def fetch(self) -> list[dict[str, Any]]:
        return []

    def create(self, title: str, *, due: str | None = None, note: str | None = None,
               subtasks: list[str] | None = None) -> str:
        return "overgeslagen (TODO_PROVIDER=none)"


def adapter() -> TodoAdapter:
    if config.TODO_PROVIDER == "todoist":
        return TodoistAdapter(config.TODOIST_TOKEN)
    if config.TODO_PROVIDER == "microsoft":
        return MicrosoftTodoAdapter()
    return NullAdapter()


def collect() -> list[dict]:
    return adapter().fetch()

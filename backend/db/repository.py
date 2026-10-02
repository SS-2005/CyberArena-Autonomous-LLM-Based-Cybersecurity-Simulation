import json
import threading
from datetime import datetime, timezone
from typing import List, Optional, Dict, Any

from backend.db.database import Database, get_database
from backend.schemas.experiment import (
    ExperimentStatus,
    ExperimentDetail,
    ExperimentSummary,
    ExperimentAgentState,
    ExperimentEvent,
    ExperimentCreateRequest,
)
from backend.schemas.agent import AgentStep, AgentActionRequest
from backend.utils.logger import logger


class ExperimentRepository:
    """
    Persistence repository for experiments, agents, and events in CyberArena.
    Decoupled from execution logic.
    """

    def __init__(self, db: Optional[Database] = None):
        self.db = db or get_database()
        self._write_lock = threading.Lock()

    def create_experiment(
        self,
        experiment_id: str,
        name: str,
        description: Optional[str],
        agents: List[Dict[str, Any]],
        raw_config: Dict[str, Any],
    ) -> ExperimentDetail:
        """Create a new experiment and associated agent records in SQLite."""
        now = datetime.now(timezone.utc).isoformat()
        config_json = json.dumps(raw_config)

        with self._write_lock:
            conn = self.db.get_connection()
            with conn:
                conn.execute(
                    """
                    INSERT INTO experiments (id, name, description, status, config_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        experiment_id,
                        name,
                        description,
                        ExperimentStatus.CREATED.value,
                        config_json,
                        now,
                        now,
                    ),
                )

            agent_states: List[ExperimentAgentState] = []
            for a in agents:
                agent_pk = f"{experiment_id}_{a['agent_id']}"
                conn.execute(
                    """
                    INSERT INTO experiment_agents (
                        id, experiment_id, agent_id, role, vm_id, model_id,
                        status, iteration_limit, current_iteration, command_timeout,
                        error_message, history_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        agent_pk,
                        experiment_id,
                        a["agent_id"],
                        a["role"],
                        a["vm_id"],
                        a["model_id"],
                        "idle",
                        a.get("iteration_limit", 10),
                        0,
                        a.get("command_timeout", 60),
                        None,
                        "[]",
                        now,
                        now,
                    ),
                )
                agent_states.append(
                    ExperimentAgentState(
                        agent_id=a["agent_id"],
                        role=a["role"],
                        vm_id=a["vm_id"],
                        model_id=a["model_id"],
                        status="idle",
                        current_iteration=0,
                        iteration_limit=a.get("iteration_limit", 10),
                        command_timeout=a.get("command_timeout", 60),
                        error_message=None,
                        history=[],
                        created_at=now,
                        updated_at=now,
                    )
                )

        return ExperimentDetail(
            id=experiment_id,
            name=name,
            description=description,
            status=ExperimentStatus.CREATED,
            agents=agent_states,
            created_at=now,
            updated_at=now,
            completed_at=None,
            error_message=None,
            total_events=0,
        )

    def get_experiment(self, experiment_id: str) -> Optional[ExperimentDetail]:
        """Fetch full experiment detail including agent states and history."""
        conn = self.db.get_connection()
        exp_row = conn.execute(
            "SELECT * FROM experiments WHERE id = ?;", (experiment_id,)
        ).fetchone()

        if not exp_row:
            return None

        agent_rows = conn.execute(
            "SELECT * FROM experiment_agents WHERE experiment_id = ? ORDER BY agent_id ASC;",
            (experiment_id,),
        ).fetchall()

        events_count = conn.execute(
            "SELECT COUNT(*) as cnt FROM experiment_events WHERE experiment_id = ?;",
            (experiment_id,),
        ).fetchone()["cnt"]

        agents: List[ExperimentAgentState] = []
        for r in agent_rows:
            raw_hist = r["history_json"] or "[]"
            try:
                hist_data = json.loads(raw_hist)
                history = [
                    AgentStep(
                        step_number=s["step_number"],
                        action=AgentActionRequest(**s["action"]),
                        observation=s["observation"],
                        success=s["success"],
                        duration=s["duration"],
                        timestamp=s["timestamp"],
                    )
                    for s in hist_data
                ]
            except Exception as e:
                logger.warning(f"Failed to parse agent history for {r['agent_id']}: {e}")
                history = []

            agents.append(
                ExperimentAgentState(
                    agent_id=r["agent_id"],
                    role=r["role"],
                    vm_id=r["vm_id"],
                    model_id=r["model_id"],
                    status=r["status"],
                    current_iteration=r["current_iteration"],
                    iteration_limit=r["iteration_limit"],
                    command_timeout=r["command_timeout"],
                    error_message=r["error_message"],
                    final_conclusion=r["final_conclusion"] if "final_conclusion" in r.keys() else None,
                    history=history,
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                )
            )

        exp_conclusion = exp_row["final_conclusion"] if "final_conclusion" in exp_row.keys() else None

        return ExperimentDetail(
            id=exp_row["id"],
            name=exp_row["name"],
            description=exp_row["description"],
            status=ExperimentStatus(exp_row["status"]),
            agents=agents,
            final_conclusion=exp_conclusion,
            created_at=exp_row["created_at"],
            updated_at=exp_row["updated_at"],
            completed_at=exp_row["completed_at"],
            error_message=exp_row["error_message"],
            total_events=events_count,
        )

    def list_experiments(self) -> List[ExperimentSummary]:
        """Fetch summary of all experiments sorted by created_at descending."""
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT e.id, e.name, e.description, e.status, e.created_at, e.updated_at, e.completed_at,
                   COUNT(a.id) as agent_count
            FROM experiments e
            LEFT JOIN experiment_agents a ON e.id = a.experiment_id
            GROUP BY e.id
            ORDER BY e.created_at DESC;
            """
        ).fetchall()

        summaries: List[ExperimentSummary] = []
        for r in rows:
            duration = None
            if r["completed_at"] and r["created_at"]:
                try:
                    start_dt = datetime.fromisoformat(r["created_at"])
                    end_dt = datetime.fromisoformat(r["completed_at"])
                    duration = round((end_dt - start_dt).total_seconds(), 2)
                except Exception:
                    pass

            summaries.append(
                ExperimentSummary(
                    id=r["id"],
                    name=r["name"],
                    description=r["description"],
                    status=ExperimentStatus(r["status"]),
                    agent_count=r["agent_count"],
                    created_at=r["created_at"],
                    updated_at=r["updated_at"],
                    completed_at=r["completed_at"],
                    duration_seconds=duration,
                )
            )
        return summaries

    def update_experiment_status(
        self,
        experiment_id: str,
        status: ExperimentStatus,
        error_message: Optional[str] = None,
        completed_at: Optional[str] = None,
    ) -> None:
        """Update experiment status and optional completion timestamp."""
        conn = self.db.get_connection()
        now = datetime.now(timezone.utc).isoformat()
        with self._write_lock:
            with conn:
                conn.execute(
                    """
                    UPDATE experiments
                    SET status = ?, error_message = coalesce(?, error_message), completed_at = coalesce(?, completed_at), updated_at = ?
                    WHERE id = ?;
                    """,
                    (status.value, error_message, completed_at, now, experiment_id),
                )

    def update_experiment_conclusion(
        self,
        experiment_id: str,
        final_conclusion: str,
    ) -> None:
        """Update the synthesized experiment-level final conclusion."""
        conn = self.db.get_connection()
        now = datetime.now(timezone.utc).isoformat()
        with self._write_lock:
            with conn:
                conn.execute(
                    """
                    UPDATE experiments
                    SET final_conclusion = ?, updated_at = ?
                    WHERE id = ?;
                    """,
                    (final_conclusion, now, experiment_id),
                )

    def update_agent_state(
        self,
        experiment_id: str,
        agent_id: str,
        status: str,
        current_iteration: int,
        error_message: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        final_conclusion: Optional[str] = None,
    ) -> None:
        """Update individual agent state within an experiment."""
        conn = self.db.get_connection()
        now = datetime.now(timezone.utc).isoformat()
        with self._write_lock:
            with conn:
                if history is not None:
                    hist_json = json.dumps(history)
                    conn.execute(
                        """
                        UPDATE experiment_agents
                        SET status = ?, current_iteration = ?, error_message = ?, history_json = ?, final_conclusion = coalesce(?, final_conclusion), updated_at = ?
                        WHERE experiment_id = ? AND agent_id = ?;
                        """,
                        (status, current_iteration, error_message, hist_json, final_conclusion, now, experiment_id, agent_id),
                    )
                else:
                    conn.execute(
                        """
                        UPDATE experiment_agents
                        SET status = ?, current_iteration = ?, error_message = coalesce(?, error_message), final_conclusion = coalesce(?, final_conclusion), updated_at = ?
                        WHERE experiment_id = ? AND agent_id = ?;
                        """,
                        (status, current_iteration, error_message, final_conclusion, now, experiment_id, agent_id),
                    )

    def add_event(self, event: ExperimentEvent) -> int:
        """Append an event to experiment_events."""
        conn = self.db.get_connection()
        merged_data = dict(event.data) if event.data else {}
        if event.event_id and "event_id" not in merged_data:
            merged_data["event_id"] = event.event_id
        if event.summary and "summary" not in merged_data:
            merged_data["summary"] = event.summary
        if event.parameters and "parameters" not in merged_data:
            merged_data["parameters"] = event.parameters
        if event.output_chunk and "output_chunk" not in merged_data:
            merged_data["output_chunk"] = event.output_chunk
        if event.stream and "stream" not in merged_data:
            merged_data["stream"] = event.stream
        if event.vm_id and "vm_id" not in merged_data:
            merged_data["vm_id"] = event.vm_id
        if event.conclusion and "conclusion" not in merged_data:
            merged_data["conclusion"] = event.conclusion

        data_json = json.dumps(merged_data)
        with self._write_lock:
            with conn:
                cursor = conn.execute(
                    """
                    INSERT INTO experiment_events (
                        experiment_id, agent_id, event_type, iteration, timestamp,
                        tool_name, content, status, error, data_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        event.experiment_id,
                        event.agent_id,
                        event.event_type,
                        event.iteration,
                        event.timestamp,
                        event.tool_name,
                        event.content,
                        event.status,
                        event.error,
                        data_json,
                    ),
                )
                return cursor.lastrowid

    def get_events(self, experiment_id: str, limit: int = 500) -> List[ExperimentEvent]:
        """Fetch past events for an experiment ordered chronologically."""
        conn = self.db.get_connection()
        rows = conn.execute(
            """
            SELECT id, experiment_id, agent_id, event_type, iteration, timestamp,
                   tool_name, content, status, error, data_json
            FROM experiment_events
            WHERE experiment_id = ?
            ORDER BY id ASC
            LIMIT ?;
            """,
            (experiment_id, limit),
        ).fetchall()

        events: List[ExperimentEvent] = []
        for r in rows:
            data = {}
            try:
                data = json.loads(r["data_json"]) if r["data_json"] else {}
            except Exception:
                pass

            events.append(
                ExperimentEvent(
                    id=r["id"],
                    event_id=data.get("event_id"),
                    experiment_id=r["experiment_id"],
                    agent_id=r["agent_id"],
                    event_type=r["event_type"],
                    iteration=r["iteration"],
                    timestamp=r["timestamp"],
                    tool_name=r["tool_name"],
                    content=r["content"],
                    status=r["status"],
                    error=r["error"],
                    summary=data.get("summary"),
                    parameters=data.get("parameters"),
                    output_chunk=data.get("output_chunk"),
                    stream=data.get("stream"),
                    vm_id=data.get("vm_id"),
                    conclusion=data.get("conclusion"),
                    data=data,
                )
            )
        return events

    def delete_experiment(self, experiment_id: str) -> bool:
        """Delete experiment and cascaded agents & events."""
        conn = self.db.get_connection()
        with self._write_lock:
            with conn:
                cursor = conn.execute("DELETE FROM experiments WHERE id = ?;", (experiment_id,))
                return cursor.rowcount > 0

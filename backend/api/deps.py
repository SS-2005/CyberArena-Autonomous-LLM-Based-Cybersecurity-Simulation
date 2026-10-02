from typing import Optional
from backend.services.vm_service import VMService
from backend.services.llm_service import LLMService
from backend.services.agent_service import AgentService
from backend.services.experiment_service import ExperimentService

_vm_service_instance: Optional[VMService] = None
_llm_service_instance: Optional[LLMService] = None
_agent_service_instance: Optional[AgentService] = None
_experiment_service_instance: Optional[ExperimentService] = None


def get_vm_service() -> VMService:
    global _vm_service_instance
    if _vm_service_instance is None:
        _vm_service_instance = VMService()
    return _vm_service_instance


def set_vm_service(service: Optional[VMService]) -> None:
    """Useful for unit tests and custom dependency injection."""
    global _vm_service_instance
    _vm_service_instance = service


def get_llm_service() -> LLMService:
    global _llm_service_instance
    if _llm_service_instance is None:
        _llm_service_instance = LLMService()
    return _llm_service_instance


def set_llm_service(service: Optional[LLMService]) -> None:
    """Useful for unit tests and mock LLM injection."""
    global _llm_service_instance
    _llm_service_instance = service


def get_agent_service() -> AgentService:
    global _agent_service_instance
    if _agent_service_instance is None:
        _agent_service_instance = AgentService(
            llm_service=get_llm_service(),
            vm_service=get_vm_service(),
        )
    return _agent_service_instance


def set_agent_service(service: Optional[AgentService]) -> None:
    """Useful for unit tests."""
    global _agent_service_instance
    _agent_service_instance = service


def get_experiment_service() -> ExperimentService:
    global _experiment_service_instance
    if _experiment_service_instance is None:
        _experiment_service_instance = ExperimentService(
            llm_service=get_llm_service(),
            vm_service=get_vm_service(),
        )
    return _experiment_service_instance


def set_experiment_service(service: Optional[ExperimentService]) -> None:
    """Useful for unit tests."""
    global _experiment_service_instance
    _experiment_service_instance = service


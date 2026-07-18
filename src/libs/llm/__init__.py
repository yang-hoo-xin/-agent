"""
LLM Module.

This package contains LLM client abstractions and implementations:
- Base LLM class (text-only)
- Base Vision LLM class (multimodal: text + image)
- LLM factory
- Provider implementations (OpenAI, Azure, Ollama, DeepSeek)
"""

from src.libs.llm.base_llm import BaseLLM, ChatResponse, Message
from src.libs.llm.agent_turn import (
    AgentMessage,
    AgentResponseFormat,
    AgentToolCall,
    AgentToolDefinition,
    AgentToolResult,
    AgentTurnClient,
    AgentTurnProviderError,
    AgentTurnRequest,
    AgentTurnResponse,
    AgentUsage,
    OllamaChatAgentAdapter,
    OpenAIResponsesAgentAdapter,
    QwenChatAgentAdapter,
    validate_loopback_http_base_url,
)
from src.libs.llm.base_vision_llm import BaseVisionLLM, ImageInput
from src.libs.llm.llm_factory import LLMFactory
from src.libs.llm.openai_llm import OpenAILLM, OpenAILLMError
from src.libs.llm.openai_vision_llm import OpenAIVisionLLM, OpenAIVisionLLMError
from src.libs.llm.azure_llm import AzureLLM, AzureLLMError
from src.libs.llm.deepseek_llm import DeepSeekLLM, DeepSeekLLMError
from src.libs.llm.ollama_llm import OllamaLLM, OllamaLLMError

# Register text-only LLM providers with factory
LLMFactory.register_provider("openai", OpenAILLM)
LLMFactory.register_provider("azure", AzureLLM)
LLMFactory.register_provider("deepseek", DeepSeekLLM)
LLMFactory.register_provider("ollama", OllamaLLM)

# Note: Vision LLM providers will be registered in task B9+

__all__ = [
    # Base classes
    "BaseLLM",
    "BaseVisionLLM",
    "AgentTurnClient",
    # Data types
    "ChatResponse",
    "Message",
    "ImageInput",
    "AgentMessage",
    "AgentResponseFormat",
    "AgentToolCall",
    "AgentToolDefinition",
    "AgentToolResult",
    "AgentTurnProviderError",
    "AgentTurnRequest",
    "AgentTurnResponse",
    "AgentUsage",
    "validate_loopback_http_base_url",
    # Factory
    "LLMFactory",
    # Text-only LLM implementations
    "OpenAILLM",
    "OpenAILLMError",
    "OpenAIResponsesAgentAdapter",
    "OllamaChatAgentAdapter",
    "QwenChatAgentAdapter",
    "AzureLLM",
    "AzureLLMError",
    "DeepSeekLLM",
    "DeepSeekLLMError",
    "OllamaLLM",
    "OllamaLLMError",
    # Vision LLM implementations
    "OpenAIVisionLLM",
    "OpenAIVisionLLMError",
]

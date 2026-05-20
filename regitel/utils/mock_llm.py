"""Mock LLM for dry-run testing without any API calls.

Domain: Generative AI / Agentic AI governance for Tier 1 banks.
"""

from __future__ import annotations

import json
from typing import Any, Optional

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class MockChatModel(BaseChatModel):
    """A mock LLM that returns plausible JSON responses for each agent role.

    Detects what agent is calling based on prompt content and returns
    appropriate mock data for GenAI governance research.
    """

    model_name: str = "mock-model"

    @property
    def _llm_type(self) -> str:
        return "mock"

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> ChatResult:
        # Combine all message content to detect context
        full_text = " ".join(
            m.content if isinstance(m.content, str) else str(m.content)
            for m in messages
        )

        if "Generate a list of specific web search queries" in full_text:
            content = self._mock_plan_response(full_text)
        elif "extracting structured regulatory data" in full_text:
            content = self._mock_extract_response(full_text)
        elif "Validate the following research findings" in full_text:
            content = self._mock_validate_response(full_text)
        elif "research findings for" in full_text and "are under review" in full_text:
            content = self._mock_reflection_response()
        else:
            content = json.dumps({"message": "Mock response", "data": []})

        return ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=content))]
        )

    def _mock_plan_response(self, text: str) -> str:
        """Mock search query planning for GenAI governance."""
        jid = "unknown"
        if "eu" in text.lower() or "european" in text.lower():
            jid = "eu"
        elif "singapore" in text.lower():
            jid = "singapore"
        elif "usa" in text.lower() or "us-" in text.lower():
            jid = "usa"

        return json.dumps([
            {
                "query": f"{jid} generative AI governance requirements for banks 2025",
                "purpose": "Find Gen AI governance mandates for financial institutions",
                "priority": 1,
            },
            {
                "query": f"{jid} AI model risk management requirements financial services",
                "purpose": "Discover MRM applicability to Gen AI",
                "priority": 2,
            },
        ])

    def _mock_extract_response(self, text: str) -> str:
        """Mock regulation extraction from search results — GenAI governance domain."""
        jid = "unknown"
        if "eu" in text.lower() or "european" in text.lower():
            jid = "eu"
            return json.dumps([{
                "regulation_id": "eu-ai-act-gen-ai",
                "jurisdiction_id": "eu",
                "name": "EU AI Act — Generative AI Provisions",
                "short_name": "EU AI Act Gen AI",
                "issuing_body": "European Commission",
                "regulation_type": "regulation",
                "status": "active",
                "effective_date": "2026-08-02",
                "version": "1.0",
                "url": "https://www.europarl.europa.eu/legislation-topics/thematic-event/0522/artificial-intelligence_en.html",
                "confidence_score": 0.95,
                "ai_governance_requirements": [{
                    "requirement_type": "transparency_disclosure",
                    "governance_scope": ["customer_facing", "internal_productivity"],
                    "entity_types": ["all"],
                    "risk_tier": "high_risk",
                    "mandatory": True,
                    "applicable_to_deployers": True,
                    "applicable_to_providers": True,
                    "key_controls": ["disclosure_of_ai_generated_content", "training_data_transparency"],
                    "notes": "Gen AI providers and deployers must disclose AI-generated content",
                }],
                "ai_control_framework": None,
            }])
        elif "singapore" in text.lower():
            jid = "singapore"
            return json.dumps([{
                "regulation_id": "sg-mas-ai-model-risk",
                "jurisdiction_id": "singapore",
                "name": "MAS AI Model Risk Management Standards",
                "short_name": "MAS AI MRM",
                "issuing_body": "Monetary Authority of Singapore",
                "regulation_type": "standard",
                "status": "active",
                "effective_date": "2026-01-01",
                "version": "1.0",
                "url": "https://www.mas.gov.sg/regulation/financial-sector-policy/ai-digital-rmb",
                "confidence_score": 0.9,
                "ai_governance_requirements": [{
                    "requirement_type": "model_risk_management",
                    "governance_scope": ["credit_underwriting", "risk_modeling"],
                    "entity_types": ["bank", "insurer", "payment_processor"],
                    "risk_tier": "high_risk",
                    "mandatory": True,
                    "applicable_to_deployers": True,
                    "applicable_to_providers": False,
                    "key_controls": ["model_validation", "bias_testing", "explainability"],
                    "notes": "Gen AI used in credit/risk must follow SR 11-7/SR 19-13 MRM framework",
                }],
                "ai_control_framework": None,
            }])
        else:
            return json.dumps([{
                "regulation_id": f"{jid}-mock-ai-reg",
                "jurisdiction_id": jid,
                "name": f"Mock Gen AI Regulation for {jid}",
                "short_name": f"{jid.upper()} Mock",
                "issuing_body": "Mock Regulatory Body",
                "regulation_type": "guideline",
                "status": "active",
                "effective_date": "2026-01-01",
                "version": "1.0",
                "url": "https://example.com/mock-ai-regulation",
                "confidence_score": 0.7,
                "ai_governance_requirements": [{
                    "requirement_type": "ai_inventory",
                    "governance_scope": ["all"],
                    "entity_types": ["all"],
                    "risk_tier": "high_risk",
                    "mandatory": True,
                    "applicable_to_deployers": True,
                    "applicable_to_providers": False,
                    "key_controls": ["inventory_registration"],
                    "notes": "Mock AI inventory requirement for testing",
                }],
                "ai_control_framework": None,
            }])

    def _mock_validate_response(self, text: str) -> str:
        """Mock validation — approve everything."""
        return json.dumps({
            "passed": True,
            "overall_confidence": 0.85,
            "issues": [],
            "approved_findings": [],
            "rejected_findings": [],
        })

    def _mock_reflection_response(self) -> str:
        """Mock reflection."""
        return json.dumps({
            "analysis": "Mock reflection — no real issues to fix",
            "actions": [],
            "drop_regulation_ids": [],
            "keep_regulation_ids": [],
        })

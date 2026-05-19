"""LLMOps CLI scripts — Phase 2+ R&D 실험/리포트 도구.

운영 컨테이너 안에서 docker exec 로 실행:
    docker exec llmops-backend python -m scripts.run_comparison \\
        --prompt-set scripts/prompts/allergy-rag-2026q2.yaml

또는 로컬 venv 에서:
    cd backend && .venv/bin/python -m scripts.run_comparison ...
"""

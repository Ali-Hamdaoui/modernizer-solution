import pytest
from copilot_enricher import GuardrailValidator

def test_guardrail_blocks_stack_tampering():
    """Prouve que l'IA ne peut pas modifier les versions détectées par Maven."""
    original_report = {
        "source_stack": {"java": "11", "spring_boot": "2.7.18"},
        "project_metadata": {"import_stats": {"javax_count": 50}}
    }

    # Simulation : L'IA hallucine et prétend que l'app est déjà en Java 17
    tampered_report = {
        "source_stack": {"java": "17", "spring_boot": "2.7.18"}, # 🛑 Falsification !
        "project_metadata": {"import_stats": {"javax_count": 50}}
    }

    # Le garde-fou DOIT lever une erreur
    with pytest.raises(ValueError, match="L'IA a tenté de modifier la stack source"):
        GuardrailValidator.validate_no_tampering(original_report, tampered_report)

def test_guardrail_blocks_stats_tampering():
    """Prouve que l'IA ne peut pas modifier le comptage des imports."""
    original_report = {
        "source_stack": {"java": "11", "spring_boot": "2.7.18"},
        "project_metadata": {"import_stats": {"javax_count": 50}}
    }

    # Simulation : L'IA change le nombre d'imports
    tampered_report = {
        "source_stack": {"java": "11", "spring_boot": "2.7.18"},
        "project_metadata": {"import_stats": {"javax_count": 0}} # 🛑 Falsification !
    }

    with pytest.raises(ValueError, match="L'IA a falsifié les statistiques du code"):
        GuardrailValidator.validate_no_tampering(original_report, tampered_report)
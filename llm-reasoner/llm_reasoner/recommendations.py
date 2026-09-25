"""Conservative recommendation triage, never authorization or execution."""
import re

RISK = {'inspection': 0, 'state_changing': 1, 'potentially_destructive': 2}


def minimum_action_type(text: str) -> str:
    """A lexical floor prevents obvious downgrades; unknown actions require review.

    This cannot establish safety of arbitrary natural language. A future approval
    layer must bind reviewed actions to an allowlisted executor, not execute text.
    """
    if re.search(r'\b(delet\w*|remov\w*|clean\w*|purg\w*|drop\w*|truncat\w*|'
                 r'overwrit\w*|wip\w*|format\w*|destroy\w*|rm|unlink)\b', text, re.I):
        return 'potentially_destructive'
    if re.search(r'\b(restart\w*|start\w*|stop\w*|reboot\w*|deploy\w*|updat\w*|'
                 r'chang\w*|edit\w*|modif\w*|resiz\w*|expand\w*|scal\w*|'
                 r'install\w*|creat\w*|set|enable\w*|disable\w*|kill|write\w*|'
                 r'restor\w*|reset\w*|apply|free\w*|resolv\w*|repair\w*|fix\w*)\b', text, re.I):
        return 'state_changing'
    if re.match(r'^\s*(inspect|check|verify|read|list|show|observe|review|measure)\b', text, re.I):
        return 'inspection'
    return 'state_changing'


def assess_recommendations(steps: list[str], changes: list[str]) -> list[dict]:
    """Application-owned requirements. Model claims never fulfill safeguards."""
    assessments = []
    for source, proposals in [('remediation_steps', steps), ('configuration_changes', changes)]:
        for index, text in enumerate(proposals):
            kind = minimum_action_type(text)
            if source == 'configuration_changes' and kind == 'inspection':
                kind = 'state_changing'
            preconditions = ['trusted_action_and_target_scope', 'authorized_operator_review']
            safeguards = ['verified_read_only_operation'] if kind == 'inspection' else [
                'reviewed_impact_and_dependencies', 'rollback_plan', 'post_action_verification_plan']
            if kind == 'potentially_destructive':
                safeguards += ['verified_backup_and_restore_readiness',
                               'explicit_data_scope_and_retention_review']
            assessments.append(dict(source=source, index=index, action_type=kind,
                required_preconditions=preconditions, required_safeguards=safeguards,
                missing_requirements=preconditions + safeguards,
                approval_eligible=False, executable=False))
    return assessments

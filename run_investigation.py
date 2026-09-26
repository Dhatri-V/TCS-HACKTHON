#!/usr/bin/env python3
"""Runner script to connect llm-reasoner to incident-platform API.

Usage:
    python run_investigation.py [INCIDENT_ID]

Example:
    python run_investigation.py INC-DEMO-001
"""
import os
import sys

# Ensure llm-reasoner is on sys.path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
LLM_REASONER_DIR = os.path.join(SCRIPT_DIR, "llm-reasoner")
if os.path.isdir(LLM_REASONER_DIR):
    sys.path.insert(0, LLM_REASONER_DIR)
else:
    sys.path.insert(0, SCRIPT_DIR)

from llm_reasoner.bridge import main

if __name__ == "__main__":
    main()

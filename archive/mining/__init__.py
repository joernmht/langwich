"""Mining pipeline — discover, extract, and classify vocabulary from open-access sources.

Requires the ``mining`` extra:  pip install langwich[mining]
"""

try:
    from langwich.mining.pipeline import MiningPipeline

    __all__ = ["MiningPipeline"]
except ImportError:
    # Mining extras (spacy, httpx, etc.) not installed — that's fine.
    # The core worksheet generator works without them via JSON import.
    __all__: list[str] = []

"""
Data source plugins.
"""
from govnotify.sources.base import AbstractSource
from govnotify.sources.registry import SourceRegistry
from govnotify.sources.egazette_source import GazetteSource
from govnotify.sources.pib_source import PIBSource
from govnotify.sources.rbi_source import RBICircularsSource, RBIPressReleasesSource
from govnotify.sources.income_tax_source import IncomeTaxSource
from govnotify.sources.mha_source import MHASource
from govnotify.sources.meity_source import MeitYSource
from govnotify.sources.sebi_source import SEBISource
from govnotify.sources.irdai_source import IRDAISource
from govnotify.sources.ibbi_source import IBBISource
from govnotify.sources.mca_source import MCASource

__all__ = [
    "AbstractSource",
    "SourceRegistry",
    "GazetteSource",
    "PIBSource",
    "RBICircularsSource",
    "RBIPressReleasesSource",
    "IncomeTaxSource",
    "MHASource",
    "MeitYSource",
    "SEBISource",
    "IRDAISource",
    "IBBISource",
    "MCASource",
]

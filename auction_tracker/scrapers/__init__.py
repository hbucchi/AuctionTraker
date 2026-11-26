from .alfa import AlfaScraper
from .base import BaseScraper, ScraperError
from .blueintra import BiasiScraper, FrazaoScraper
from .pgfn import PgfnScraper
from .picelli import PicelliScraper
from .superbid import SuperbidScraper
from .zuk import ZukScraper

#: every scraper, keyed by its CLI name
REGISTRY: dict[str, type[BaseScraper]] = {
    cls.name: cls
    for cls in (
        ZukScraper,
        BiasiScraper,
        FrazaoScraper,
        SuperbidScraper,
        PicelliScraper,
        AlfaScraper,
        PgfnScraper,
    )
}

__all__ = ["REGISTRY", "BaseScraper", "ScraperError"]

from __future__ import annotations

import argparse
import sys

import structlog

from offroad_scraper.config import Settings, load_sites
from offroad_scraper.logging_conf import configure_logging

logger = structlog.get_logger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="offroad-scraper",
        description="Scrape offroad trips and publish an ICS calendar.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("scrape", help="Fetch trip listings, extract trips, rebuild the ICS.")
    subparsers.add_parser("serve", help="Serve the ICS file over HTTP.")
    return parser


def run_scrape(settings: Settings) -> int:
    import openai

    from offroad_scraper.calendar_builder import write_calendar_atomic
    from offroad_scraper.extractor import Extractor
    from offroad_scraper.http_client import HttpClient, HttpClientError
    from offroad_scraper.store import StoreError, TripStore

    if settings.deepseek_api_key is None:
        logger.error("DEEPSEEK_API_KEY is required for the 'scrape' command")
        return 1

    sites = load_sites(settings.sites_file)
    if not sites:
        logger.warning("no sites loaded", path=str(settings.sites_file))

    client = HttpClient(
        timeout_seconds=settings.scrape_timeout_seconds,
        max_bytes=settings.scrape_max_bytes,
        user_agent=settings.scrape_user_agent,
    )
    extractor = Extractor(settings)
    store = TripStore(settings.output_dir)

    total_extracted = 0
    for site in sites:
        logger.info("scraping site", site=site.name, url=site.url)
        try:
            html = client.fetch(site.url)
        except HttpClientError as exc:
            logger.error("fetch failed", site=site.name, error=str(exc))
            continue
        try:
            trips = extractor.extract(site.name, html)
        except openai.OpenAIError as exc:
            logger.error("fatal llm error, aborting run", site=site.name, error=str(exc))
            return 1
        total_extracted += len(trips)
        try:
            added = store.merge(trips)
        except StoreError as exc:
            logger.error("failed to persist trips, aborting run", error=str(exc))
            return 1
        logger.info("merged trips", site=site.name, found=len(trips), added=added)

    try:
        all_trips = store.all_trips()
    except StoreError as exc:
        logger.error("failed to read trips store, aborting run", error=str(exc))
        return 1

    signature = store.content_signature()
    if signature == store.load_signature():
        logger.info("calendar unchanged, skipping rebuild", count=len(all_trips))
        return 0

    path = write_calendar_atomic(settings.output_dir, all_trips)
    store.save_signature(signature)
    logger.info("wrote calendar", path=str(path), count=len(all_trips), extracted=total_extracted)
    return 0


def run_serve(settings: Settings) -> int:
    import uvicorn

    from offroad_scraper.server import create_app

    app = create_app(settings)
    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None, access_log=False)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    configure_logging(settings.log_level)
    if args.command == "scrape":
        return run_scrape(settings)
    if args.command == "serve":
        return run_serve(settings)
    return 1


if __name__ == "__main__":
    sys.exit(main())
